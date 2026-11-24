"""The beta reader: a living response to a chapter, as from a reader the author knows, not
a list of mistakes. The reader sees the chapter, who the people in it are (from the cards)
and how far into the book it is; never the chapters that follow."""

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.card import name_matcher
from app.llm.calls import TextModel
from app.models import BetaReview, Chapter, Entity, Project, text_hash

# What the reader is asked about, in the order the review answers.
ASKS = {
    "liked": "what you liked and what stayed with you (a scene, a line, a character)",
    "boring": "where you got bored, skimmed or wanted to skip, and why",
    "disbelief": "where you did not believe it: a character acting out of character, "
    "a convenient coincidence, a feeling that came from nowhere",
    "unclear": "what stayed unclear or confusing: who is who, where we are, what happened",
    "expect": "what you expect or want to happen next, and what you are afraid will happen",
}
READERS = {
    "fan": "a devoted reader of this genre who has read a lot of it: you notice what is fresh "
    "and what is the hundredth time, and you love it when the genre is done well",
    "casual": "an ordinary reader who picked the book up by chance: no special knowledge of "
    "the genre, you read for the story and the people, and you put a book down when lost "
    "or bored",
    "critic": "a demanding critic and experienced editor: you judge the craft (structure, "
    "pace, character, voice) and say plainly what does not work",
}
TONES = {
    "soft": "Be warm and encouraging: start with what works, phrase problems as your "
    "impressions and wishes, never harsh. Still name the real problems.",
    "honest": "Be honest and direct, like a friend who wants the book to be good: no "
    "flattery, no padding, say what does not work and why. Not rude.",
}
DEFAULT_ASKS = list(ASKS)
CHAPTER_CHARS = 60_000  # longer chapters are cut: the review is of the reading, not every page
MAX_CARDS = 15


def _system(reader: str, tone: str, asks: list[str]) -> str:
    points = "\n".join(f"- {ASKS[a]}" for a in asks)
    return f"""You are a beta reader of a book in progress. You are {READERS[reader]}.
You have just read one chapter. Tell the author how it read for you, as a person, not as a \
proofreader: no spelling, no punctuation, no lists of typos.
Answer these, each under its own short heading, in this order:
{points}
Point at concrete places: quote a few words or name the scene. Short paragraphs, plain \
words. If there is nothing to say on a point, say so in one line. Do not retell the \
chapter. Do not guess at what later chapters hold: you have not read them.
{TONES[tone]}
Write in the language of the chapter. Plain text: headings on their own line, no Markdown \
symbols (no #, no **)."""


def _context(session: Session, project: Project, chapter: Chapter) -> str:
    """How far into the book the chapter is, and who the named people in it are."""
    chapters = [c for c in project.chapters if c.text.strip()]
    number = next((i for i, c in enumerate(chapters, 1) if c.id == chapter.id), 0)
    lines = [f"This is chapter {number} of {len(chapters)} written so far."]
    before = [c.title for c in chapters[: max(number - 1, 0)] if c.title]
    if before:
        lines.append("Chapters before it: " + "; ".join(before[-20:]))
    entities = session.scalars(select(Entity).where(Entity.project_id == project.id)).all()
    cards = []
    for entity in entities:
        about = (entity.summary or entity.description).split(". ")[0].strip()
        if about and name_matcher(entity)(chapter.text):
            cards.append(f"- {entity.name}: {about[:200]}")
    if cards:
        lines.append(
            "Who the named people and places are (what earlier chapters told you):\n"
            + "\n".join(cards[:MAX_CARDS])
        )
    return "\n".join(lines)


def review_chapter(
    session: Session,
    model: TextModel,
    project: Project,
    chapter: Chapter,
    reader: str,
    tone: str,
    asks: list[str],
) -> BetaReview:
    """Ask the reader about one chapter and keep the answer with it."""
    asks = [a for a in ASKS if a in asks] or DEFAULT_ASKS
    reader = reader if reader in READERS else "casual"
    tone = tone if tone in TONES else "soft"
    text = chapter.text[:CHAPTER_CHARS]
    body = f'{_context(session, project, chapter)}\n\nChapter "{chapter.title}":\n\n{text}'
    answer = model.invoke(
        "beta_reader", [SystemMessage(_system(reader, tone, asks)), HumanMessage(body)]
    )
    review = BetaReview(
        project_id=project.id,
        chapter_id=chapter.id,
        chapter_hash=chapter.content_hash,
        reader=reader,
        tone=tone,
        asks=asks,
        text=_plain(answer),
    )
    session.add(review)
    session.commit()
    return review


# ---- one review of several chapters (the whole book) ----
# A book does not fit one request: the reader first reads chapter by chapter and keeps short
# private notes (one request each, nothing stored), then writes one review from all of them.
NOTES_WORDS = 250
NOTES_CHARS = 4_000  # per chapter, what the client sends back


def chapters_hash(chapters: list[Chapter]) -> str:
    """Changes when any of the chapters read changes."""
    return text_hash("|".join(c.content_hash for c in chapters))


def _notes_system(reader: str) -> str:
    return f"""You are a beta reader of a book in progress. You are {READERS[reader]}.
You are reading the book chapter by chapter and will write the author one review of the \
whole book at the end. Now write short private notes on the chapter you have just read, for \
yourself, at most {NOTES_WORDS} words: what you liked and what stayed with you, where you got \
bored, where you did not believe it, what stayed unclear, what you expect next. Quote a few \
words or name the scene so you can point at it later. Do not retell the chapter. Plain text, \
in the language of the chapter."""


def chapter_notes(
    session: Session, model: TextModel, project: Project, chapter: Chapter, reader: str
) -> str:
    """The reader's private notes on one chapter, for the review of the whole book."""
    reader = reader if reader in READERS else "casual"
    text = chapter.text[:CHAPTER_CHARS]
    body = f'{_context(session, project, chapter)}\n\nChapter "{chapter.title}":\n\n{text}'
    answer = model.invoke("beta_reader", [SystemMessage(_notes_system(reader)), HumanMessage(body)])
    return _plain(answer)[:NOTES_CHARS]


def _book_system(reader: str, tone: str, asks: list[str], count: int) -> str:
    points = "\n".join(f"- {ASKS[a]}" for a in asks)
    return f"""You are a beta reader of a book in progress. You are {READERS[reader]}.
You have just read {count} chapters of it, and while reading you kept the notes below. Now \
write the author ONE review of the whole read, as a person, not as a proofreader: no \
spelling, no punctuation, no lists of typos. Do not go chapter by chapter: speak about the \
book as a whole (the story, the people, the pace, how it holds together), and point at a \
chapter by its number or title where it helps.
Answer these, each under its own short heading, in this order:
{points}
Short paragraphs, plain words. If there is nothing to say on a point, say so in one line. \
Do not retell the book.
{TONES[tone]}
Write in the language of the notes. Plain text: headings on their own line, no Markdown \
symbols (no #, no **)."""


def review_book(
    session: Session,
    model: TextModel,
    project: Project,
    chapters: list[Chapter],
    notes: list[str],
    reader: str,
    tone: str,
    asks: list[str],
) -> BetaReview:
    """One review of the chapters read, written from the notes kept on each of them."""
    asks = [a for a in ASKS if a in asks] or DEFAULT_ASKS
    reader = reader if reader in READERS else "casual"
    tone = tone if tone in TONES else "soft"
    numbers = {c.id: n for n, c in enumerate(project.chapters, 1)}
    body = "\n\n".join(
        f'Chapter {numbers.get(c.id, "?")} "{c.title}":\n{note.strip()[:NOTES_CHARS]}'
        for c, note in zip(chapters, notes, strict=True)
    )
    answer = model.invoke(
        "beta_reader",
        [SystemMessage(_book_system(reader, tone, asks, len(chapters))), HumanMessage(body)],
    )
    review = BetaReview(
        project_id=project.id,
        chapter_id="",
        chapter_ids=[c.id for c in chapters],
        chapter_hash=chapters_hash(chapters),
        reader=reader,
        tone=tone,
        asks=asks,
        text=_plain(answer),
    )
    session.add(review)
    session.commit()
    return review


def _plain(text: str) -> str:
    """Models put Markdown in anyway: strip the marks, keep the words."""
    lines = []
    for line in text.strip().splitlines():
        line = line.strip()
        line = line.lstrip("#").strip() if line.startswith("#") else line
        lines.append(line.replace("**", "").replace("__", ""))
    return "\n".join(lines).strip()
