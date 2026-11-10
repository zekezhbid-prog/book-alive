"""Search over the book: small chunks for matching, their neighbours for context.

The embedding model reads about 128 tokens, so chunks are kept to a few sentences. A
few sentences are too little for a model to answer from, so every hit is returned
together with the chunks around it ("small to big").

Two rankings are fused: meaning (vector distance) and wording (the query's own words,
which is what finds a rare name the embedding model has never seen).
"""

import re
from dataclasses import dataclass

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from sqlalchemy import Integer, delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import Chapter, Chunk, Project
from app.rag.embeddings import get_embeddings

CHUNK_CHARS = 600
VECTOR_CANDIDATES = 12
KEYWORD_CANDIDATES = 12
RRF_K = 60  # the usual constant of reciprocal rank fusion


def split_chunks(text: str, limit: int = CHUNK_CHARS) -> list[tuple[int, str]]:
    """(index of the first paragraph, text) pairs. Paragraphs are kept whole when they
    fit; a long one is cut at sentence ends."""
    chunks: list[tuple[int, str]] = []
    start, current = 0, ""
    for index, paragraph in enumerate(text.split("\n\n")):
        pieces = [paragraph]
        if len(paragraph) > limit:
            pieces, piece = [], ""
            for sentence in re.split(r"(?<=[.!?…])\s+", paragraph):
                if piece and len(piece) + len(sentence) > limit:
                    pieces.append(piece)
                    piece = ""
                piece = f"{piece} {sentence}".strip()
            pieces.append(piece)
        for piece in pieces:
            if current and len(current) + len(piece) > limit:
                chunks.append((start, current))
                current = ""
            if not current:
                start = index
            current = f"{current}\n\n{piece}" if current else piece
    if current.strip():
        chunks.append((start, current))
    return chunks


def index_project(session: Session, project: Project) -> int:
    """Embed the chapters whose text changed since they were indexed. Returns how many."""
    indexed = dict(
        session.execute(
            select(Chunk.chapter_id, func.min(Chunk.chapter_hash))
            .where(Chunk.project_id == project.id)
            .group_by(Chunk.chapter_id)
        ).all()
    )
    current = {c.id for c in project.chapters}
    gone = [chapter_id for chapter_id in indexed if chapter_id not in current]
    if gone:
        session.execute(delete(Chunk).where(Chunk.chapter_id.in_(gone)))
    changed = [c for c in project.chapters if indexed.get(c.id) != c.content_hash]
    embeddings = get_embeddings()
    for chapter in changed:
        session.execute(delete(Chunk).where(Chunk.chapter_id == chapter.id))
        pieces = split_chunks(chapter.text) if chapter.text.strip() else []
        vectors = embeddings.embed_documents([text for _, text in pieces]) if pieces else []
        for position, ((paragraph, text), vector) in enumerate(zip(pieces, vectors, strict=True)):
            session.add(
                Chunk(
                    project_id=project.id,
                    chapter_id=chapter.id,
                    chapter_hash=chapter.content_hash,
                    position=position,
                    paragraph=paragraph,
                    text=text,
                    embedding=vector,
                )
            )
    session.commit()
    return len(changed)


def _stems(query: str) -> list[str]:
    """Query words cut to their stems: endings change in Slavic languages."""
    words = {w for w in re.findall(r"\w+", query.casefold()) if len(w) >= 4}
    return [w[:-2] if len(w) > 5 else w for w in words]


@dataclass
class Passage:
    """A hit widened with its neighbours: what the model actually reads."""

    chapter_id: str
    chapter_title: str
    paragraph: int  # index of the first paragraph in the chapter
    text: str


def search(
    session: Session,
    project_id: str,
    query: str,
    limit: int = 6,
    focus_chapter_id: str = "",
    chapter_ids: list[str] | None = None,
) -> list[Passage]:
    """Hybrid search over the book; `chapter_ids`, when given, keeps it inside those chapters."""
    scores: dict[str, float] = {}
    in_scope = [Chunk.project_id == project_id]
    if chapter_ids:
        in_scope.append(Chunk.chapter_id.in_(chapter_ids))

    def add(ranked: list[str]) -> None:
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    vector = get_embeddings().embed_query(query)
    by_meaning = select(Chunk.id).where(*in_scope)
    add(
        list(
            session.scalars(
                by_meaning.order_by(Chunk.embedding.cosine_distance(vector)).limit(
                    VECTOR_CANDIDATES
                )
            )
        )
    )
    if focus_chapter_id:
        # "What did he mean here?": the open chapter gets its own vote.
        add(
            list(
                session.scalars(
                    by_meaning.where(Chunk.chapter_id == focus_chapter_id)
                    .order_by(Chunk.embedding.cosine_distance(vector))
                    .limit(3)
                )
            )
        )
    stems = _stems(query)
    if stems:
        matches = sum(func.cast(Chunk.text.ilike(f"%{stem}%"), Integer) for stem in stems)
        add(
            list(
                session.scalars(
                    select(Chunk.id)
                    .where(
                        *in_scope,
                        or_(*(Chunk.text.ilike(f"%{stem}%") for stem in stems)),
                    )
                    .order_by(matches.desc(), Chunk.id)
                    .limit(KEYWORD_CANDIDATES)
                )
            )
        )
    best = sorted(scores, key=scores.get, reverse=True)[:limit]
    hits = session.scalars(select(Chunk).where(Chunk.id.in_(best))).all()
    return _widen(session, sorted(hits, key=lambda c: best.index(c.id)))


MENTION_CHUNKS = 20
MENTION_CANDIDATES = 400


def _name_stems(query: str) -> list[str]:
    """Words written with a capital letter (names, in a search query of key words), cut
    to a stem that survives case endings: "Журэі" -> "журэ", "Люты" -> "лют". A name of
    three letters ("Зур") is kept whole; whether it is a name at all, and not "Кто" at the
    start of a question, `mentions` checks against the book."""
    words = {w for w in re.findall(r"\w+", query) if len(w) >= 3 and w[0].isupper()}
    return sorted({w.casefold()[: len(w) - _cut(w)] for w in words})


def _cut(word: str) -> int:
    return 0 if len(word) <= 3 else 1 if len(word) <= 5 else 2


# Before a name inside a sentence: a word or a comma, then spaces ("ваявода Зур").
INSIDE_SENTENCE = r"[\w,;:]\s+$"
NAME_SAMPLE = 60


def _used_as_name(session: Session, scope: list, stem: str) -> bool:
    """True when the book writes the stem with a capital inside a sentence somewhere: a
    name, not a word that is capitalised only where a sentence starts."""
    word = stem[:1].upper() + stem[1:]
    texts = session.scalars(
        select(Chunk.text).where(*scope, Chunk.text.like(f"%{word}%")).limit(NAME_SAMPLE)
    ).all()
    for text in texts:
        for match in re.finditer(re.escape(word), text):
            start = match.start()
            if start and text[start - 1].isalnum():
                continue  # inside another word
            if re.search(INSIDE_SENTENCE, text[max(0, start - 40) : start]):
                return True
    return False


def mentions(
    session: Session, project_id: str, query: str, chapter_ids: list[str] | None = None
) -> list[Passage]:
    """Every place the names of the query occur, not just the few best hits: a question
    about someone ("her maid") is answered by what surrounds their name across the book.
    Every chapter the name is in gets a place first, so a late chapter is not crowded out
    by the early ones; within that, places that also share the other words of the query
    come first, then book order."""
    in_scope = [Chunk.project_id == project_id]
    if chapter_ids:
        in_scope.append(Chunk.chapter_id.in_(chapter_ids))
    short = {w.casefold() for w in re.findall(r"\w+", query) if len(w) == 3}
    names = [n for n in _name_stems(query) if n not in short or _used_as_name(session, in_scope, n)]
    if not names:
        return []
    others = [s for s in _stems(query) if not any(s.startswith(n) for n in names)]
    shared = sum((func.cast(Chunk.text.ilike(f"%{w}%"), Integer) for w in others), start=0)
    rows = session.execute(
        select(Chunk, Chapter.position)
        .join(Chapter, Chapter.id == Chunk.chapter_id)
        .where(*in_scope, or_(*(Chunk.text.ilike(f"%{n}%") for n in names)))
        .order_by(desc(shared) if others else Chapter.position, Chapter.position, Chunk.position)
        .limit(MENTION_CANDIDATES)
    ).all()
    picked: list = []
    chapters: set[str] = set()
    for row in rows:  # the best place of each chapter
        if row[0].chapter_id not in chapters:
            chapters.add(row[0].chapter_id)
            picked.append(row)
    picked += [r for r in rows if r not in picked]
    picked = picked[:MENTION_CHUNKS]
    # Read in book order: the story of a person unfolds chapter by chapter.
    return _widen(session, [c for c, _ in sorted(picked, key=lambda r: (r[1], r[0].position))])


def _widen(session: Session, hits: list[Chunk]) -> list[Passage]:
    """Each hit with the chunk before and after it, without repeating text."""
    passages: list[Passage] = []
    used: set[tuple[str, int]] = set()
    for hit in hits:
        if (hit.chapter_id, hit.position) in used:
            continue  # already inside a neighbour's passage
        around = session.scalars(
            select(Chunk)
            .where(
                Chunk.chapter_id == hit.chapter_id,
                Chunk.position.between(hit.position - 1, hit.position + 1),
            )
            .order_by(Chunk.position)
        ).all()
        around = [c for c in around if (c.chapter_id, c.position) not in used]
        used.update((c.chapter_id, c.position) for c in around)
        chapter = session.get(Chapter, hit.chapter_id)
        passages.append(
            Passage(
                chapter_id=hit.chapter_id,
                chapter_title=chapter.title if chapter else "",
                paragraph=around[0].paragraph,
                text="\n\n".join(c.text for c in around),
            )
        )
    return passages


class BookRetriever(BaseRetriever):
    """The same search as a LangChain retriever, for use inside chains."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session: Session
    project_id: str
    focus_chapter_id: str = ""
    limit: int = 6

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return [
            Document(
                page_content=p.text,
                metadata={
                    "chapter_id": p.chapter_id,
                    "chapter_title": p.chapter_title,
                    "paragraph": p.paragraph,
                },
            )
            for p in search(self.session, self.project_id, query, self.limit, self.focus_chapter_id)
        ]
