"""Whole-book versions: commit the working chapters, list changes, roll back."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BookVersion, Chapter, ChapterRevision, Project, VersionChapter


@dataclass
class Changes:
    added: list[str]
    removed: list[str]
    edited: list[str]  # text changed
    renamed: list[str]
    reordered: bool

    @property
    def dirty(self) -> bool:
        return bool(self.added or self.removed or self.edited or self.renamed or self.reordered)


def latest_version(session: Session, project_id: str) -> BookVersion | None:
    return session.scalars(
        select(BookVersion)
        .where(BookVersion.project_id == project_id)
        .order_by(BookVersion.number.desc())
        .limit(1)
    ).first()


def changes_since(project: Project, version: BookVersion | None) -> Changes:
    """Working copy compared with a version. Chapter ids in the lists."""
    saved = {e.chapter_id: e for e in version.entries} if version else {}
    working = {c.id: c for c in sorted(project.chapters, key=lambda c: c.position)}
    common = [cid for cid in working if cid in saved]
    return Changes(
        added=[cid for cid in working if cid not in saved],
        removed=[cid for cid in saved if cid not in working],
        edited=[
            cid for cid in common if working[cid].content_hash != saved[cid].revision.content_hash
        ],
        renamed=[cid for cid in common if working[cid].title != saved[cid].title],
        reordered=common != [cid for cid in saved if cid in working],
    )


def _revision(session: Session, chapter: Chapter) -> ChapterRevision:
    revision = session.scalars(
        select(ChapterRevision).where(
            ChapterRevision.project_id == chapter.project_id,
            ChapterRevision.content_hash == chapter.content_hash,
        )
    ).first()
    if revision is None:
        revision = ChapterRevision(
            project_id=chapter.project_id, content_hash=chapter.content_hash, text=chapter.text
        )
        session.add(revision)
    return revision


def commit(session: Session, project: Project, label: str = "") -> BookVersion:
    previous = latest_version(session, project.id)
    version = BookVersion(
        project_id=project.id, number=(previous.number + 1 if previous else 1), label=label
    )
    for chapter in project.chapters:
        version.entries.append(
            VersionChapter(
                chapter_id=chapter.id,
                position=chapter.position,
                title=chapter.title,
                revision=_revision(session, chapter),
            )
        )
    session.add(version)
    session.flush()
    return version


def rollback(session: Session, project: Project, version: BookVersion, autosave_label: str) -> None:
    """Make the working copy equal to `version`. Uncommitted work is committed first,
    so a rollback never loses text."""
    if changes_since(project, latest_version(session, project.id)).dirty:
        commit(session, project, autosave_label)
    working = {c.id: c for c in project.chapters}
    kept = set()
    for entry in version.entries:
        # Same id as before, so analysis results that reference it still line up.
        chapter = working.get(entry.chapter_id) or Chapter(id=entry.chapter_id)
        chapter.position = entry.position
        chapter.title = entry.title
        chapter.text = entry.revision.text
        chapter.content_hash = entry.revision.content_hash
        if chapter.id not in working:
            project.chapters.append(chapter)
        kept.add(chapter.id)
    for chapter in list(project.chapters):
        if chapter.id not in kept:
            project.chapters.remove(chapter)
    session.flush()
