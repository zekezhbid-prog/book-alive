"""Questions about the book, answered only from its text, with checked citations."""

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.entities import locate_quote
from app.llm.calls import TextModel
from app.models import FACT_PERMANENT, ChatMessage, Entity, Project
from app.rag.index import BookRetriever, index_project
from app.scenes.service import entities_in

HISTORY_MESSAGES = 6

SYSTEM = """You answer questions about one book. Below are numbered passages from it, found \
by search for this question.

Rules:
- Answer only from the passages. Do not use anything you know about this or any other book.
- If the passages do not contain the answer, say plainly that the book text found for this \
question does not answer it, and set "found" to false. Do not guess.
- Answer in the language of the question, even when the passages are in another language. \nBe brief and to the point.
- After each statement put the number of the passage it comes from, like [2].
- For every passage you relied on, give one short quote copied from it character for \
character (under 200 characters).

Reply with one JSON object and nothing else:
{{"found": true, "answer": "... [1] ... [3]", "citations": [{{"source": 1, "quote": ""}}]}}

Passages:

{passages}"""


class Citation(BaseModel):
    source: int
    quote: str = ""


class Answer(BaseModel):
    found: bool = True
    answer: str
    citations: list[Citation] = Field(default_factory=list)


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
    # Indexing is local and free; it happens here, on the user's first question,
    # and again only for chapters whose text has changed.
    index_project(session, project)
    earlier = history(session, project.id)[-HISTORY_MESSAGES:]
    # A follow-up ("and what then?") only makes sense with the question before it.
    previous = next((m.content for m in reversed(earlier) if m.role == "user"), "")
    retriever = BookRetriever(session=session, project_id=project.id, focus_chapter_id=chapter_id)
    documents = retriever.invoke(f"{previous}\n{question}".strip())

    asked = ChatMessage(project_id=project.id, role="user", content=question)
    session.add(asked)
    if not documents:
        reply = ChatMessage(project_id=project.id, role="assistant", content="", citations=[])
        session.add(reply)
        session.commit()
        return asked, reply

    passages = "\n\n".join(
        f"[{n}] ({doc.metadata['chapter_title'] or '—'})\n{doc.page_content}"
        for n, doc in enumerate(documents, 1)
    )
    messages: list[BaseMessage] = [SystemMessage(SYSTEM.format(passages=passages))]
    for message in earlier:
        messages.append(
            HumanMessage(message.content) if message.role == "user" else AIMessage(message.content)
        )
    messages.append(HumanMessage(question))
    answer = model.invoke_json("chat", messages, Answer)

    citations = []
    chapters = {c.id: c for c in project.chapters}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer.answer)}
    quotes = {c.source: c.quote for c in answer.citations}
    for n in sorted(cited | set(quotes)):
        if not 1 <= n <= len(documents):
            continue  # the model pointed at a passage it was never given
        doc = documents[n - 1]
        quote = quotes.get(n, "").strip()
        # The quote must be in the passage the model was given, not just somewhere in the book.
        in_passage = bool(quote) and locate_quote(quote, [doc.page_content]) is not None
        chapter = chapters.get(doc.metadata["chapter_id"])
        exact = locate_quote(quote, chapter.text.split("\n\n")) if in_passage and chapter else None
        citations.append(
            {
                "n": n,
                "chapter_id": doc.metadata["chapter_id"],
                "chapter_title": doc.metadata["chapter_title"],
                # Without a checked quote the link still leads to the start of the passage.
                "paragraph": exact if exact is not None else doc.metadata["paragraph"],
                "quote": quote if exact is not None else "",
            }
        )
    reply = ChatMessage(
        project_id=project.id,
        role="assistant",
        content=answer.answer,
        citations=citations if answer.found else [],
    )
    session.add(reply)
    session.commit()
    return asked, reply


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
    asked = ChatMessage(project_id=project.id, role="user", content=request)
    session.add(asked)
    if not tail.strip():
        reply = ChatMessage(project_id=project.id, role="assistant", content="", citations=[])
        session.add(reply)
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
    session.add(reply)
    session.commit()
    return asked, reply
