"""Questions about the book, answered only from its text, with checked citations."""

import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.entities import locate_quote
from app.llm.calls import TextModel
from app.models import ChatMessage, Project
from app.rag.index import BookRetriever, index_project

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
