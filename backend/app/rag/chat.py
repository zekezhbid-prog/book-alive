"""Questions about the book, answered only from its text, with checked citations."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.entities import locate_quote
from app.llm.calls import TextModel
from app.models import FACT_PERMANENT, ChatMessage, Entity, Project, now
from app.rag import agent
from app.rag.index import BookRetriever, index_project, search
from app.scenes.service import entities_in

HISTORY_MESSAGES = 6


@dataclass
class Status:
    """What the agent is doing, shown while the user waits."""

    code: str  # index | search | read | think
    detail: str = ""


@dataclass
class Reply:
    asked: ChatMessage
    reply: ChatMessage


def history(session: Session, project_id: str) -> list[ChatMessage]:
    return list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.project_id == project_id)
            .order_by(ChatMessage.created_at)
        ).all()
    )


def ask(
    session: Session, project: Project, model: TextModel, question: str, chapter_id: str = ""
) -> tuple[ChatMessage, ChatMessage]:
    for event in ask_events(session, project, model, question, chapter_id):
        if isinstance(event, Reply):
            return event.asked, event.reply
    raise RuntimeError("the chat ended without a reply")


def ask_events(
    session: Session, project: Project, model: TextModel, question: str, chapter_id: str = ""
) -> Iterator[Status | Reply]:
    """Answer a question, reporting each step as it starts. The last event is the Reply."""
    yield Status("index")
    # Indexing is local and free; it happens here, on the user's first question,
    # and again only for chapters whose text has changed.
    index_project(session, project)
    earlier = history(session, project.id)[-HISTORY_MESSAGES:]
    # A follow-up ("and what then?") only makes sense with the question before it.
    previous = next((m.content for m in reversed(earlier) if m.role == "user"), "")

    # Saved together with the reply, at the end: a pending write would keep the database
    # connection for as long as the model thinks (see `db.release_connection`).
    asked = ChatMessage(project_id=project.id, role="user", content=question, created_at=now())
    if not any(c.text.strip() for c in project.chapters):
        reply = ChatMessage(project_id=project.id, role="assistant", content="", citations=[])
        session.add_all([asked, reply])
        session.commit()
        yield Reply(asked, reply)
        return

    # A first search for the question itself: often enough, and it shows the agent where
    # in the book to look.
    yield Status("search", question)
    sources = [
        agent.passage_document(p.chapter_id, p.chapter_title, p.paragraph, p.text)
        for p in search(session, project.id, f"{previous}\n{question}".strip(), 6, chapter_id)
    ]
    found = ", ".join(f"[{n}]" for n in range(1, len(sources) + 1)) or "nothing"
    state: agent.State = {
        "question": question,
        "sources": sources,
        "log": [f"searched the book for the question: {found}"],
        "steps": 0,
        "decision": None,
    }
    config = {
        "configurable": {
            "session": session,
            "model": model,
            "project": project,
            "open_chapter_id": chapter_id,
            "history": [
                HumanMessage(m.content) if m.role == "user" else AIMessage(m.content)
                for m in earlier
            ],
        }
    }
    yield Status("think")
    for update in agent.GRAPH.stream(state, config, stream_mode="updates"):
        for node, change in update.items():
            state.update(change)
            if node != "decide":
                yield Status("think")
                continue
            decision = state["decision"]
            if decision.action == "search":
                yield Status("search", decision.query)
            elif decision.action == "read":
                chapters = project.chapters
                number = decision.chapter
                title = chapters[number - 1].title if 1 <= number <= len(chapters) else ""
                yield Status("read", title or str(number))

    decision = state["decision"]
    reply = ChatMessage(
        project_id=project.id,
        role="assistant",
        content=decision.answer,
        citations=_citations(project, decision, state["sources"]),
    )
    session.add_all([asked, reply])
    session.commit()
    yield Reply(asked, reply)


def _citations(project: Project, decision: agent.Decision, sources: list[Document]) -> list[dict]:
    citations = []
    chapters = {c.id: c for c in project.chapters}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", decision.answer)}
    quotes = {c.source: c.quote for c in decision.citations}
    for n in sorted(cited | set(quotes)):
        if not 1 <= n <= len(sources):
            continue  # the model pointed at a source it was never given
        doc = sources[n - 1]
        quote = quotes.get(n, "").strip()
        # The quote must be in the source the model was given, not just somewhere in the book.
        in_source = bool(quote) and locate_quote(quote, [doc.page_content]) is not None
        chapter = chapters.get(doc.metadata["chapter_id"])
        exact = locate_quote(quote, chapter.text.split("\n\n")) if in_source and chapter else None
        citations.append(
            {
                "n": n,
                "chapter_id": doc.metadata["chapter_id"],
                "chapter_title": doc.metadata["chapter_title"],
                # Without a checked quote the link still leads to the start of the source.
                "paragraph": exact if exact is not None else doc.metadata["paragraph"],
                "quote": quote if exact is not None else "",
            }
        )
    return citations


SUGGEST_SYSTEM = """You help the author of a book that is being written. Below are the \
last pages written so far, what is known about the characters in them, and related \
passages from earlier in the book.

Offer three different ways the story could go on from here. Rules:
- Each must follow from what is already written: the characters' natures, their stated \
intentions, unresolved threads. Do not contradict the text.
- Make the three really different from one another (in direction, not in detail).
- Two or three sentences each. Describe what happens; do not write the prose itself: \
the author writes the book.
- Write in the language of the book.

Reply with one JSON object and nothing else:
{{"options": [{{"title": "", "text": ""}}, {{"title": "", "text": ""}}, {{"title": "", "text": ""}}]}}

The last pages:

{tail}

Characters and places in them:

{cast}

Related passages from earlier:

{passages}"""

TAIL_CHARS = 4000


class Option(BaseModel):
    title: str = ""
    text: str


class Options(BaseModel):
    options: list[Option]


def suggest(
    session: Session, project: Project, model: TextModel, request: str, chapter_id: str
) -> tuple[ChatMessage, ChatMessage]:
    """Three ways to continue from the end of a chapter. The request text is only what
    the user sees in the conversation; nothing is ever written into the book."""
    index_project(session, project)
    chapter = next((c for c in project.chapters if c.id == chapter_id), None)
    tail = (chapter.text if chapter else "")[-TAIL_CHARS:]
    # As in `ask_events`: nothing is written until the model has answered.
    asked = ChatMessage(project_id=project.id, role="user", content=request, created_at=now())
    if not tail.strip():
        reply = ChatMessage(project_id=project.id, role="assistant", content="", citations=[])
        session.add_all([asked, reply])
        session.commit()
        return asked, reply

    cast = []
    for entity_id in entities_in(session, project.id, tail, []):
        entity = session.get(Entity, entity_id)
        traits = [f.text for f in entity.facts if f.category == FACT_PERMANENT][:5]
        cast.append(f"- {entity.name}" + (f": {'; '.join(traits)}" if traits else ""))
    retriever = BookRetriever(session=session, project_id=project.id, limit=5)
    # The closing paragraphs say best what the story is about right now.
    documents = [
        doc
        for doc in retriever.invoke(tail[-800:])
        if doc.page_content not in tail  # the tail itself is already in the prompt
    ]
    passages = "\n\n".join(
        f"({doc.metadata['chapter_title'] or '—'}) {doc.page_content}" for doc in documents
    )
    system = SUGGEST_SYSTEM.format(
        tail=tail, cast="\n".join(cast) or "(no cards yet)", passages=passages or "(none)"
    )
    answer = model.invoke_json(
        "suggest_plot", [SystemMessage(system), HumanMessage(request)], Options
    )
    content = "\n\n".join(
        f"{n}. {option.title.strip()}\n{option.text.strip()}".replace(f"{n}. \n", f"{n}. ")
        for n, option in enumerate(answer.options[:3], 1)
    )
    reply = ChatMessage(project_id=project.id, role="assistant", content=content, citations=[])
    session.add_all([asked, reply])
    session.commit()
    return asked, reply
