"""Questions about the book, answered only from its text, with checked citations."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.entities import locate_quote
from app.llm.calls import TextModel
from app.models import FACT_PERMANENT, ChatMessage, ChatThread, Chunk, Entity, Project, new_id, now
from app.rag import agent
from app.rag.index import BookRetriever, _cut, _used_as_name, index_project, mentions, search
from app.scenes.service import entities_in

HISTORY_MESSAGES = 6
TITLE_CHARS = 60


@dataclass
class Status:
    """What the agent is doing, shown while the user waits."""

    code: str  # index | card | search | read | think
    detail: str = ""


@dataclass
class Reply:
    asked: ChatMessage
    reply: ChatMessage
    # Names the question asks about that occur in the book but have no card yet: the
    # reader is advised to run the character search (it is never started on its own).
    missing_cards: list[str] = field(default_factory=list)


def threads(session: Session, project_id: str) -> list[ChatThread]:
    """The project's conversations, the most recently used first."""
    return list(
        session.scalars(
            select(ChatThread)
            .where(ChatThread.project_id == project_id)
            .order_by(ChatThread.updated_at.desc(), ChatThread.id)
        ).all()
    )


def new_thread(project: Project) -> ChatThread:
    """A conversation over the whole book, not yet added to the session. The id is set
    here so messages can point at it before anything is written."""
    moment = now()
    return ChatThread(
        id=new_id(),
        project_id=project.id,
        title="",
        chapter_ids=[],
        created_at=moment,
        updated_at=moment,
    )


def _thread(session: Session, project: Project, thread: ChatThread | None) -> ChatThread:
    """The thread to talk in: the given one, else the latest, else a new one."""
    if thread is not None:
        return thread
    existing = threads(session, project.id)
    return existing[0] if existing else new_thread(project)


def scope(project: Project, thread: ChatThread) -> list[str]:
    """The thread's chapters that still exist, in book order; empty means the whole book."""
    chosen = set(thread.chapter_ids or [])
    return [c.id for c in project.chapters if c.id in chosen]


def _save(session: Session, thread: ChatThread, asked: ChatMessage, reply: ChatMessage) -> None:
    """Writes the exchange at the very end, together with the thread's name and time."""
    if not thread.title:
        line = " ".join(asked.content.split())
        thread.title = line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1] + "…"
    thread.updated_at = now()
    session.add(thread)
    session.flush()  # no ORM relationship orders the inserts: the thread goes first
    session.add_all([asked, reply])
    session.commit()


def history(session: Session, thread_id: str) -> list[ChatMessage]:
    return list(
        session.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at)
        ).all()
    )


def ask(
    session: Session,
    project: Project,
    model: TextModel,
    question: str,
    chapter_id: str = "",
    thread: ChatThread | None = None,
) -> tuple[ChatMessage, ChatMessage]:
    for event in ask_events(session, project, model, question, chapter_id, thread):
        if isinstance(event, Reply):
            return event.asked, event.reply
    raise RuntimeError("the chat ended without a reply")


def ask_events(
    session: Session,
    project: Project,
    model: TextModel,
    question: str,
    chapter_id: str = "",
    thread: ChatThread | None = None,
) -> Iterator[Status | Reply]:
    """Answer a question in a thread (the latest one if none is given), reporting each
    step as it starts. The last event is the Reply."""
    yield Status("index")
    # Indexing is local and free; it happens here, on the user's first question,
    # and again only for chapters whose text has changed.
    index_project(session, project)
    thread = _thread(session, project, thread)
    chapters = scope(project, thread)
    # The open chapter only counts when the thread may look into it.
    focus = chapter_id if not chapters or chapter_id in chapters else ""
    earlier = history(session, thread.id)[-HISTORY_MESSAGES:]
    # A follow-up ("and what then?") only makes sense with the question before it.
    previous = next((m.content for m in reversed(earlier) if m.role == "user"), "")

    # Saved together with the reply, at the end: a pending write would keep the database
    # connection for as long as the model thinks (see `db.release_connection`).
    asked = ChatMessage(
        project_id=project.id,
        thread_id=thread.id,
        role="user",
        content=question,
        created_at=now(),
    )
    if not any(c.text.strip() for c in project.chapters):
        reply = ChatMessage(
            project_id=project.id,
            thread_id=thread.id,
            role="assistant",
            content="",
            citations=[],
        )
        _save(session, thread, asked, reply)
        yield Reply(asked, reply)
        return

    # A first search for the question itself: often enough, and it shows the agent where
    # in the book to look. Words only match in the book's own language, so a question asked
    # in another one is first put into it.
    query = f"{previous}\n{question}".strip()
    sample = _book_sample(project)
    if needs_translation(query, sample):
        query = _translate(model, query, sample)
    yield Status("search", query)
    found_passages = search(session, project.id, query, 6, focus, chapters or None)
    # Everywhere the names of the question occur: "her maid" is found next to "her" name.
    seen = {(p.chapter_id, p.paragraph) for p in found_passages}
    found_passages += [
        p
        # The question too: a translation may garble a name the question spells well.
        for p in mentions(session, project.id, f"{query} {question}", chapters or None)
        if (p.chapter_id, p.paragraph) not in seen
    ]
    sources = [
        agent.passage_document(p.chapter_id, p.chapter_title, p.paragraph, p.text)
        for p in found_passages
    ]
    found = ", ".join(f"[{n}]" for n in range(1, len(sources) + 1)) or "nothing"
    state: agent.State = {
        "question": question,
        "sources": sources,
        "log": [f"searched the book for the question: {found}"],
        "notes": [],
        "steps": 0,
        "decision": None,
    }
    config = {
        "configurable": {
            "session": session,
            "model": model,
            "project": project,
            "open_chapter_id": focus,
            # Sources in the book's language pull the answer into it; say it outright.
            "language_note": (
                LANGUAGE_NOTE.format(question) if needs_translation(question, sample) else ""
            ),
            "scope": chapters,
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
            if decision.action == "card":
                yield Status("card", decision.name)
            elif decision.action == "search":
                yield Status("search", decision.query)
            elif decision.action == "read":
                chapters = project.chapters
                number = decision.chapter
                title = chapters[number - 1].title if 1 <= number <= len(chapters) else ""
                yield Status("read", title or str(number))

    decision = state["decision"]
    if other_language(question, decision.answer):
        # The sources pull some models into the book's language: the reader asked in theirs.
        decision.answer = _in_language_of(model, question, decision.answer)
    reply = ChatMessage(
        project_id=project.id,
        thread_id=thread.id,
        role="assistant",
        content=decision.answer,
        citations=_citations(project, decision, state["sources"]),
    )
    _save(session, thread, asked, reply)
    yield Reply(asked, reply, cardless_names(session, project, query, question))


class Answer(BaseModel):
    answer: str = ""


def _in_language_of(model: TextModel, question: str, answer: str) -> str:
    """The answer rewritten in the question's language; as it was if that fails."""
    try:
        rewritten = model.invoke_json(
            "chat",
            [
                SystemMessage(
                    "Translate the answer into the language of the question. Keep every "
                    "source marker like [2] where it is, keep quotes in «» as they are, "
                    'change nothing else. Reply with one JSON object: {"answer": "..."}'
                ),
                HumanMessage(f"Question: {question}\n\nAnswer: {answer}"),
            ],
            Answer,
        )
    except Exception:  # noqa: BLE001 - an answer in the wrong language beats none
        return answer
    return rewritten.answer.strip() or answer


NAME = re.compile(r"[^\W\d_][\w'’]{2,}")


def _capitalised(text: str, skip_sentence_starts: bool) -> list[str]:
    words = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        found = [w for w in NAME.findall(sentence) if w[0].isupper()]
        if skip_sentence_starts and found and sentence.lstrip().startswith(found[0]):
            found = found[1:]
        words += found
    return words


def cardless_names(session: Session, project: Project, query: str, question: str) -> list[str]:
    """Names the reader asks about (capitalised words: all of the search query, which is
    key words in the book's language, and those of the question that do not start a
    sentence) that the book uses at least twice with the capital and no card answers to."""
    words = _capitalised(query, False) + _capitalised(question, True)
    missing: dict[str, str] = {}
    for word in words:
        stem = word[: len(word) - _cut(word)]
        if stem.casefold() in missing or agent.find_card(session, project, word):
            continue
        if len(word) == 3 and not _used_as_name(session, [Chunk.project_id == project.id], stem):
            continue  # "Хто" starting a sentence, not a name
        uses = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.project_id == project.id, Chunk.text.like(f"%{stem}%"))
        )
        if uses >= 2:
            missing[stem.casefold()] = word
    return list(missing.values())[:3]


LANGUAGE_NOTE = (
    "The question is not in the language of the book. Write the answer in the language of "
    "the question, not of the book; quotes stay as the book has them. The question: «{}»"
)


class SearchQuery(BaseModel):
    query: str = ""


def _book_sample(project: Project, size: int = 6000) -> str:
    text = ""
    for chapter in project.chapters:
        text += chapter.text[: size - len(text)]
        if len(text) >= size:
            break
    return text


# Letters that tell close languages apart: Russian и щ ъ, Belarusian і ў, Ukrainian ї є ґ.
MARKER_LETTERS = set("ищъіўїєґ")


def _script(letters: set[str]) -> set[str]:
    return {"latin" if c.isascii() else "other" for c in letters}


def needs_translation(question: str, sample: str) -> bool:
    """True when the question is in another language than the book: another script, or
    a letter that marks a close language the book never uses ("и" in a Belarusian book)."""
    book = {c for c in sample.casefold() if c.isalpha()}
    asked = {c for c in question.casefold() if c.isalpha()}
    if not book or not asked:
        return False
    if not _script(asked) & _script(book):
        return True
    return bool((asked & MARKER_LETTERS) - book)


def _language(text: str) -> str:
    """ "latin", "uk", "be", "ru", or "" when the text does not tell, by the letters only
    one of the close languages uses. Quotes in «» are left out: an answer quotes the book
    in the book's language."""
    letters = [c for c in re.sub(r"«[^»]*»", "", text).casefold() if c.isalpha()]
    if not letters:
        return ""
    if sum(c.isascii() for c in letters) > len(letters) / 2:
        return "latin"
    if any(c in "їєґ" for c in letters):
        return "uk"
    russian = sum(c in "иыэъ" for c in letters)
    belarusian = sum(c in "іў" for c in letters)
    if russian == belarusian:
        return ""
    return "ru" if russian > belarusian else "be"


def other_language(question: str, answer: str) -> bool:
    """True when the answer is plainly in another language than the question."""
    asked, answered = _language(question), _language(answer)
    return bool(asked and answered and asked != answered)


# Translated queries, so that the same question searches the same way every time: a
# model rewrites it a little differently on each call, and the first search with it.
TRANSLATIONS: dict[tuple[str, str], str] = {}
TRANSLATIONS_KEPT = 500


def _translate(model: TextModel, query: str, sample: str) -> str:
    """The question as a search query in the book's language; the question itself if the
    model cannot help."""
    key = (sample[:1500], query)
    if key in TRANSLATIONS:
        return TRANSLATIONS[key]
    translated = _translate_once(model, query, sample)
    if translated != query:
        if len(TRANSLATIONS) >= TRANSLATIONS_KEPT:
            TRANSLATIONS.pop(next(iter(TRANSLATIONS)))
        TRANSLATIONS[key] = translated
    return translated


def _translate_once(model: TextModel, query: str, sample: str) -> str:
    try:
        answer = model.invoke_json(
            "chat",
            [
                SystemMessage(
                    "Rewrite the user's question as a short search query in the language of "
                    "the book excerpt below: the key words only (names, things, actions), "
                    "not a whole question. Keep every name of the question, spelt in the "
                    "book's alphabet and in its base form; never put another name in its "
                    "place. "
                    'Reply with one JSON object: {"query": "..."}\n\n'
                    "Book excerpt:\n" + sample[:1500]
                ),
                HumanMessage(query),
            ],
            SearchQuery,
        )
    except Exception:  # noqa: BLE001 - a failed rewrite only costs a worse first search
        return query
    return answer.query.strip() or query


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
    session: Session,
    project: Project,
    model: TextModel,
    request: str,
    chapter_id: str,
    thread: ChatThread | None = None,
) -> tuple[ChatMessage, ChatMessage]:
    """Three ways to continue from the end of a chapter. The request text is only what
    the user sees in the conversation; nothing is ever written into the book."""
    index_project(session, project)
    thread = _thread(session, project, thread)
    chapter = next((c for c in project.chapters if c.id == chapter_id), None)
    tail = (chapter.text if chapter else "")[-TAIL_CHARS:]
    # As in `ask_events`: nothing is written until the model has answered.
    asked = ChatMessage(
        project_id=project.id,
        thread_id=thread.id,
        role="user",
        content=request,
        created_at=now(),
    )
    if not tail.strip():
        reply = ChatMessage(
            project_id=project.id,
            thread_id=thread.id,
            role="assistant",
            content="",
            citations=[],
        )
        _save(session, thread, asked, reply)
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
    reply = ChatMessage(
        project_id=project.id,
        thread_id=thread.id,
        role="assistant",
        content=content,
        citations=[],
    )
    _save(session, thread, asked, reply)
    return asked, reply
