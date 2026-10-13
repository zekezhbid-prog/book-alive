import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

MODE_READER = "reader"  # finished book: illustrator tools only, text is read-only
MODE_WRITER = "writer"  # book in progress: editor, versions, plus illustrator tools

KIND_OPENAI = "openai"  # any OpenAI-compatible endpoint (OpenRouter, OmniRoute, ...)
KIND_CLAUDE_CLI = "claude_cli"  # local Claude Code CLI, billed to the user's subscription


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    author: Mapped[str] = mapped_column(String(300), default="")
    mode: Mapped[str] = mapped_column(String(10))
    source_filename: Mapped[str] = mapped_column(String(300), default="")
    # How chapters were found on import: headings | pattern | sections | manual
    split_method: Mapped[str] = mapped_column(String(20), default="manual")
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
