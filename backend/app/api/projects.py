import re
import shutil
from datetime import datetime
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionDep
from app.importing.chapters import detect_chapters
from app.importing.extract import UnsupportedBook, extract
from app.models import (
    MODE_READER,
    MODE_WRITER,
    BookVersion,
    Chapter,
    Project,
    text_hash,
)
from app.services import versions

router = APIRouter(prefix="/api", tags=["projects"])

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
TITLE_MAX = 300  # matches the column size


# ---------- schemas ----------


class ChapterBrief(BaseModel):
    id: str
    position: int
    title: str
    chars: int
    content_hash: str


class ChapterFull(ChapterBrief):
    text: str


class VersionOut(BaseModel):
    id: str
    number: int
    label: str
    created_at: datetime
    chapters: int


class ChangesOut(BaseModel):
    added: list[str]
    removed: list[str]
    edited: list[str]
    renamed: list[str]
    reordered: bool
    dirty: bool


class ProjectBrief(BaseModel):
    id: str
    title: str
    author: str
    mode: str
    created_at: datetime
    chapters: int
    chars: int


class ProjectOut(BaseModel):
    id: str
    title: str
    author: str
    mode: str
    source_filename: str
    split_method: str
    style_id: str
    style_text: str
    created_at: datetime
    chapters: list[ChapterBrief]
    # Writer projects only.
    version: VersionOut | None = None
    changes: ChangesOut | None = None


class ProjectPatch(BaseModel):
    title: str | None = None
    author: str | None = None


class ChapterPatch(BaseModel):
    title: str | None = None
    text: str | None = None


class ChapterCreate(BaseModel):
    title: str = ""
    after_id: str | None = None


class SplitRequest(BaseModel):
    # The new chapter starts at this paragraph (0-based) of the current one.
    paragraph: int
    title: str = ""
    # That paragraph is the heading itself: it becomes the title and leaves the text.
    drop_heading: bool = False


class ReorderRequest(BaseModel):
    chapter_ids: list[str]


class CommitRequest(BaseModel):
    label: str = ""


class SearchHit(BaseModel):
    chapter_id: str
    chapter_title: str
    paragraph: int
    snippet: str


# ---------- helpers ----------


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project_not_found")
    return project


def _chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(404, "chapter_not_found")
    return chapter


def _writer_only(project: Project) -> None:
    if project.mode != MODE_WRITER:
        raise HTTPException(409, "reader_mode_readonly")


def _set_text(chapter: Chapter, text: str) -> None:
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
    chapter.text = text
    chapter.content_hash = text_hash(text)


def _title(value: str) -> str:
    value = value.strip()
    if len(value) > TITLE_MAX:
        raise HTTPException(422, "title_too_long")
    return value


def _renumber(project: Project, ordered: list[Chapter]) -> None:
    for position, chapter in enumerate(ordered):
        chapter.position = position


def _ordered(project: Project) -> list[Chapter]:
    return sorted(project.chapters, key=lambda c: c.position)


def _brief(chapter: Chapter) -> ChapterBrief:
    return ChapterBrief(
        id=chapter.id,
        position=chapter.position,
        title=chapter.title,
        chars=len(chapter.text),
        content_hash=chapter.content_hash,
    )


def _full(chapter: Chapter) -> ChapterFull:
    return ChapterFull(**_brief(chapter).model_dump(), text=chapter.text)


def _version_out(version: BookVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        number=version.number,
        label=version.label,
        created_at=version.created_at,
        chapters=len(version.entries),
    )


def _project_out(session: Session, project: Project) -> ProjectOut:
    out = ProjectOut(
        id=project.id,
        title=project.title,
        author=project.author,
        mode=project.mode,
        source_filename=project.source_filename,
        split_method=project.split_method,
        style_id=project.style_id,
        style_text=project.style_text,
        created_at=project.created_at,
        chapters=[_brief(c) for c in _ordered(project)],
    )
    if project.mode == MODE_WRITER:
        latest = versions.latest_version(session, project.id)
        changes = versions.changes_since(project, latest)
        out.version = _version_out(latest) if latest else None
        out.changes = ChangesOut(**vars(changes), dirty=changes.dirty)
    return out


# ---------- projects ----------


@router.get("/projects")
def list_projects(request: Request, session: SessionDep) -> list[ProjectBrief]:
    # Sizes are computed in the database: loading every chapter's text for a list is wasteful.
    sizes = {
        project_id: (count, chars)
        for project_id, count, chars in session.execute(
            select(Chapter.project_id, func.count(), func.sum(func.length(Chapter.text))).group_by(
                Chapter.project_id
            )
        )
    }
    query = select(Project).order_by(Project.created_at.desc())
    if request.state.user_id:  # with accounts, only the user's own books
        query = query.where(Project.owner_id == request.state.user_id)
    projects = session.scalars(query).all()
    return [
        ProjectBrief(
            id=p.id,
            title=p.title,
            author=p.author,
            mode=p.mode,
            created_at=p.created_at,
            chapters=sizes.get(p.id, (0, 0))[0],
            chars=sizes.get(p.id, (0, 0))[1] or 0,
        )
        for p in projects
    ]


@router.post("/projects")
def create_project(
    request: Request,
    session: SessionDep,
    mode: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    file: UploadFile | None = None,
) -> ProjectOut:
    if mode not in (MODE_READER, MODE_WRITER):
        raise HTTPException(422, "bad_mode")
    if mode == MODE_READER and file is None:
        raise HTTPException(422, "book_file_required")

    project = Project(title=_title(title), mode=mode, owner_id=request.state.user_id)
    if file is not None:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file_too_large")
        # Only the last path component, and never a name that is itself a directory.
        filename = PurePath(file.filename or "").name[-TITLE_MAX:].strip(". ") or "book"
        try:
            book = extract(data, filename)
        except UnsupportedBook as exc:
            raise HTTPException(422, f"unsupported_book: {exc}") from exc
        if not book.paragraphs:
            raise HTTPException(422, "empty_book")
        project.split_method, detected = detect_chapters(book.paragraphs)
        opening = detected[0]
        if not opening.title and len(detected) > 1 and len(opening.text) <= 100:
            # One short line before the first chapter is the book's title, not a chapter.
            book.title = book.title or opening.text.replace("\n\n", " ")
            detected = detected[1:]
        project.source_filename = filename
        project.author = book.author[:TITLE_MAX]
        project.title = project.title or book.title[:TITLE_MAX] or PurePath(filename).stem
        for position, chapter in enumerate(detected):
            project.chapters.append(
                Chapter(
                    position=position,
                    title=chapter.title[:TITLE_MAX],
                    text=chapter.text,
                    content_hash=text_hash(chapter.text),
                )
            )
    project.title = project.title or "Untitled"
    session.add(project)
    session.flush()

    if file is not None:
        # The original upload is kept untouched next to the database.
        source_dir = settings.files_dir / project.id / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / project.source_filename).write_bytes(data)
    if mode == MODE_WRITER:
        versions.commit(session, project, "import" if file is not None else "start")
    session.commit()
    return _project_out(session, project)


@router.get("/projects/{project_id}")
def get_project(project_id: str, session: SessionDep) -> ProjectOut:
    return _project_out(session, _project(session, project_id))


@router.patch("/projects/{project_id}")
def update_project(project_id: str, patch: ProjectPatch, session: SessionDep) -> ProjectOut:
    project = _project(session, project_id)
    if patch.title is not None and patch.title.strip():
        project.title = _title(patch.title)
    if patch.author is not None:
        project.author = _title(patch.author)
    session.commit()
    return _project_out(session, project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, session: SessionDep) -> None:
    project = _project(session, project_id)
    session.delete(project)
    session.commit()
    shutil.rmtree(settings.files_dir / project_id, ignore_errors=True)


@router.get("/projects/{project_id}/search")
def search(project_id: str, q: str, session: SessionDep) -> list[SearchHit]:
    project = _project(session, project_id)
    needle = q.strip().casefold()
    if len(needle) < 2:
        return []
    hits: list[SearchHit] = []
    for chapter in _ordered(project):
        for index, paragraph in enumerate(chapter.text.split("\n\n")):
            at = paragraph.casefold().find(needle)
            if at < 0:
                continue
            start = max(0, at - 60)
            hits.append(
                SearchHit(
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    paragraph=index,
                    snippet=paragraph[start : at + len(needle) + 60],
                )
            )
            if len(hits) >= 200:
                return hits
    return hits


# ---------- chapters ----------


@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: str, session: SessionDep) -> ChapterFull:
    return _full(_chapter(session, chapter_id))


@router.patch("/chapters/{chapter_id}")
def update_chapter(chapter_id: str, patch: ChapterPatch, session: SessionDep) -> ChapterFull:
    chapter = _chapter(session, chapter_id)
    if patch.text is not None:
        _writer_only(chapter.project)
        _set_text(chapter, patch.text)
    if patch.title is not None:
        chapter.title = _title(patch.title)
    session.commit()
    return _full(chapter)


@router.post("/projects/{project_id}/chapters")
def create_chapter(project_id: str, body: ChapterCreate, session: SessionDep) -> ChapterFull:
    project = _project(session, project_id)
    _writer_only(project)
    ordered = _ordered(project)
    index = len(ordered)
    if body.after_id:
        index = next((i + 1 for i, c in enumerate(ordered) if c.id == body.after_id), index)
    chapter = Chapter(title=_title(body.title), text="", content_hash=text_hash(""), position=index)
    project.chapters.append(chapter)
    ordered.insert(index, chapter)
    _renumber(project, ordered)
    session.commit()
    return _full(chapter)


@router.delete("/chapters/{chapter_id}", status_code=204)
def delete_chapter(chapter_id: str, session: SessionDep) -> None:
    """Allowed in both modes: an imported book often starts with a title page or a
    table of contents that should not be analysed."""
    chapter = _chapter(session, chapter_id)
    project = chapter.project
    project.chapters.remove(chapter)
    _renumber(project, _ordered(project))
    session.commit()


@router.post("/chapters/{chapter_id}/merge-next")
def merge_next(chapter_id: str, session: SessionDep) -> ChapterFull:
    chapter = _chapter(session, chapter_id)
    project = chapter.project
    ordered = _ordered(project)
    index = ordered.index(chapter)
    if index + 1 >= len(ordered):
        raise HTTPException(409, "no_next_chapter")
    following = ordered[index + 1]
    # The heading of the absorbed chapter stays in the text as an ordinary line.
    _set_text(chapter, "\n\n".join(filter(None, [chapter.text, following.title, following.text])))
    project.chapters.remove(following)
    _renumber(project, _ordered(project))
    session.commit()
    return _full(chapter)


@router.post("/chapters/{chapter_id}/split")
def split_chapter(chapter_id: str, body: SplitRequest, session: SessionDep) -> list[ChapterFull]:
    chapter = _chapter(session, chapter_id)
    project = chapter.project
    paragraphs = chapter.text.split("\n\n")
    if not 0 < body.paragraph < len(paragraphs):
        raise HTTPException(422, "bad_split_point")
    ordered = _ordered(project)
    tail = Chapter(title=_title(body.title), position=0, content_hash="")
    _set_text(tail, "\n\n".join(paragraphs[body.paragraph + body.drop_heading :]))
    _set_text(chapter, "\n\n".join(paragraphs[: body.paragraph]))
    project.chapters.append(tail)
    ordered.insert(ordered.index(chapter) + 1, tail)
    _renumber(project, ordered)
    session.commit()
    return [_full(chapter), _full(tail)]


@router.post("/projects/{project_id}/reorder")
def reorder(project_id: str, body: ReorderRequest, session: SessionDep) -> ProjectOut:
    project = _project(session, project_id)
    _writer_only(project)
    by_id = {c.id: c for c in project.chapters}
    if set(body.chapter_ids) != set(by_id) or len(body.chapter_ids) != len(by_id):
        raise HTTPException(422, "bad_chapter_list")
    _renumber(project, [by_id[cid] for cid in body.chapter_ids])
    session.commit()
    return _project_out(session, project)


# ---------- versions ----------


@router.get("/projects/{project_id}/versions")
def list_versions(project_id: str, session: SessionDep) -> list[VersionOut]:
    project = _project(session, project_id)
    return [_version_out(v) for v in reversed(project.versions)]


@router.post("/projects/{project_id}/versions")
def commit_version(project_id: str, body: CommitRequest, session: SessionDep) -> ProjectOut:
    project = _project(session, project_id)
    _writer_only(project)
    if not versions.changes_since(project, versions.latest_version(session, project.id)).dirty:
        raise HTTPException(409, "nothing_to_commit")
    versions.commit(session, project, body.label.strip())
    session.commit()
    return _project_out(session, project)


@router.post("/projects/{project_id}/versions/{version_id}/rollback")
def rollback_version(project_id: str, version_id: str, session: SessionDep) -> ProjectOut:
    project = _project(session, project_id)
    _writer_only(project)
    version = session.get(BookVersion, version_id)
    if version is None or version.project_id != project.id:
        raise HTTPException(404, "version_not_found")
    versions.rollback(session, project, version, autosave_label="autosave")
    # The restored state becomes a version of its own, so history stays linear.
    if versions.changes_since(project, versions.latest_version(session, project.id)).dirty:
        versions.commit(session, project, f"rollback:{version.number}")
    session.commit()
    session.refresh(project)
    return _project_out(session, project)
