import hashlib
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

MODE_READER = "reader"  # finished book: illustrator tools only, text is read-only
MODE_WRITER = "writer"  # book in progress: editor, versions, plus illustrator tools

KIND_OPENAI = "openai"  # any OpenAI-compatible endpoint (OpenRouter, OmniRoute, ...)


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # lower case
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=now)


class PasswordReset(Base):
    """A one-time link sent by mail. Only the hash of the token is stored."""

    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    author: Mapped[str] = mapped_column(String(300), default="")
    mode: Mapped[str] = mapped_column(String(10))
    # Whose book it is. Empty on a machine without accounts, and for books made before
    # accounts existed: the owner's e-mail claims those when they register.
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    source_filename: Mapped[str] = mapped_column(String(300), default="")
    # How chapters were found on import: headings | pattern | sections | manual
    split_method: Mapped[str] = mapped_column(String(20), default="manual")
    # Visual style of every picture in the project: a preset id, "custom" or "" (not chosen).
    style_id: Mapped[str] = mapped_column(String(30), default="")
    style_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Chapter.position"
    )
    versions: Mapped[list["BookVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="BookVersion.number"
    )


class Chapter(Base):
    """Working copy of a chapter. Analysis results reference `content_hash`
    of the text they were computed from, which is how staleness is detected."""

    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))

    project: Mapped[Project] = relationship(back_populates="chapters")


class ChapterRevision(Base):
    """Immutable chapter text, stored once per distinct content."""

    __tablename__ = "chapter_revisions"
    __table_args__ = (UniqueConstraint("project_id", "content_hash"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)


class BookVersion(Base):
    """Snapshot of the whole book, like a commit."""

    __tablename__ = "book_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    number: Mapped[int]
    label: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=now)

    project: Mapped[Project] = relationship(back_populates="versions")
    entries: Mapped[list["VersionChapter"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="VersionChapter.position"
    )


class VersionChapter(Base):
    __tablename__ = "version_chapters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(ForeignKey("book_versions.id", ondelete="CASCADE"))
    # Not a foreign key: the working chapter may be deleted while the snapshot keeps it.
    chapter_id: Mapped[str] = mapped_column(String(32))
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(300))
    revision_id: Mapped[str] = mapped_column(ForeignKey("chapter_revisions.id"))

    version: Mapped[BookVersion] = relationship(back_populates="entries")
    revision: Mapped[ChapterRevision] = relationship()


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default=KIND_OPENAI)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


KIND_CHARACTER = "character"
KIND_LOCATION = "location"

FACT_PERMANENT = "permanent"  # face, build, age, scars: true for the whole book
FACT_STATE = "state"  # clothes, wounds, carried objects: true in one chapter
FACT_PROFILE = "profile"  # who they are, what they do, likes: the general description

RUN_RUNNING = "running"
RUN_DONE = "done"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"


class Entity(Base):
    """A character or a location. Everything known about it lives in `facts`."""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    # The user's own decisions, which later runs must respect:
    # names the user attached to this card by merging,
    pinned_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    # and a card the user split off, which is never merged away again.
    standalone: Mapped[bool] = mapped_column(default=False)
    # Found without a proper name (an old man, the merchants) or as a group: probably someone
    # already known, shown apart "in question" until the user merges it or a chapter names it.
    uncertain: Mapped[bool] = mapped_column(default=False)
    # The author's own words about the card (a writer describes people and places in text
    # only); the facts below are what a search read out of the chapters.
    description: Mapped[str] = mapped_column(Text, default="")
    # A coherent description (who it is, its role, what is known), written by the model at
    # the end of a run from the card's facts. Empty until a run has finished or was cancelled.
    summary: Mapped[str] = mapped_column(Text, default="")
    # How it looks as a whole (a character's age, build, face, hair, usual clothes; a place's
    # kind, size, materials, colours), written by the model with the summary. Pictures are
    # drawn from it. `appearance_own` is the user's version: when set, it wins and runs
    # never touch it.
    appearance: Mapped[str] = mapped_column(Text, default="")
    appearance_own: Mapped[str] = mapped_column(Text, default="")

    facts: Mapped[list["EntityFact"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    # No delete cascade: pictures are never removed as a side effect.
    images: Mapped[list["Image"]] = relationship(back_populates="entity", passive_deletes=True)


class EntityFact(Base):
    """One statement about an entity, tied to the chapter text it came from."""

    __tablename__ = "entity_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    # Not a foreign key: facts outlive a deleted chapter until the user refreshes.
    chapter_id: Mapped[str] = mapped_column(String(32))
    # Hash of the chapter text the fact was read from; a different hash now means stale.
    chapter_hash: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    # Verbatim quote and its paragraph; empty/None when the model's quote is not in the text.
    quote: Mapped[str] = mapped_column(Text, default="")
    paragraph: Mapped[int | None] = mapped_column(default=None)

    entity: Mapped[Entity] = relationship(back_populates="facts")


class ChapterExtraction(Base):
    """Raw model output for one chapter. Makes runs resumable and re-runs free."""

    __tablename__ = "chapter_extractions"
    __table_args__ = (UniqueConstraint("chapter_id", "kind"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chapter_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(20))
    chapter_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=RUN_RUNNING)
    chapter_ids: Mapped[list[str]] = mapped_column(JSON)
    done_chapter_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class UsageEvent(Base):
    """One model call: the journal of where tokens went."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    operation: Mapped[str] = mapped_column(String(50))
    connection_name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)


EMBEDDING_DIMENSIONS = 384


class Chunk(Base):
    """A few sentences of a chapter with their embedding: the search index."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chapter_id: Mapped[str] = mapped_column(String(32), index=True)
    chapter_hash: Mapped[str] = mapped_column(String(64))
    position: Mapped[int]  # order inside the chapter
    paragraph: Mapped[int]  # first paragraph of the chapter covered by the chunk
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class ChatThread(Base):
    """One conversation about the book. Each keeps its own history (the agent sees only
    this thread's earlier messages) and its own scope: the whole book or chosen chapters."""

    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Empty until the first question, which then names the thread.
    title: Mapped[str] = mapped_column(String(200), default="")
    # Chapters the agent may search and read; empty means the whole book.
    chapter_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=now)
    # Last question asked: the list shows the most recent conversations first.
    updated_at: Mapped[datetime] = mapped_column(default=now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # For assistant messages: [{"n", "chapter_id", "chapter_title", "paragraph", "quote"}]
    citations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Image(Base):
    """A reference picture: of a character, of a location, or of the project in general."""

    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), default=None
    )
    # Set for a generated first frame of a scene; such a picture belongs to no card.
    scene_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenes.id", ondelete="SET NULL"), default=None
    )
    origin: Mapped[str] = mapped_column(String(20))  # upload | generated
    # The project style the picture was made in; see app/images/styles.py.
    style_key: Mapped[str] = mapped_column(String(40), default="")
    # Main pictures define face and build, one view each; the others are looks drawn from them.
    is_main: Mapped[bool] = mapped_column(default=False)
    angle: Mapped[str] = mapped_column(String(20), default="")  # see app/images/angles.py
    look_label: Mapped[str] = mapped_column(String(200), default="")
    # Part of the story the look belongs to; empty means an open end.
    chapter_from_id: Mapped[str] = mapped_column(String(32), default="")
    chapter_to_id: Mapped[str] = mapped_column(String(32), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    path: Mapped[str] = mapped_column(String(300))  # relative to the files directory
    mime: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=now)

    entity: Mapped[Entity | None] = relationship(back_populates="images")


class Scene(Base):
    """A stretch of one chapter to bring to life. Read-only for the user, except the prompt."""

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chapter_id: Mapped[str] = mapped_column(String(32), index=True)
    # Paragraph numbers refer to the chapter text with this hash.
    chapter_hash: Mapped[str] = mapped_column(String(64))
    paragraph_from: Mapped[int]
    paragraph_to: Mapped[int]  # inclusive
    title: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    vivid: Mapped[bool] = mapped_column(default=False)
    origin: Mapped[str] = mapped_column(String(10))  # auto | manual
    entity_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # The video prompt: only the latest version is kept.
    prompt: Mapped[str] = mapped_column(Text, default="")
    # The pictures the model chose for that prompt, in order; empty until it is built.
    reference_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=now)
