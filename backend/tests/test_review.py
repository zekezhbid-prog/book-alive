import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Chapter, Entity, EntityFact, Project, text_hash
from app.review import service

FIRST = "Люта шла по дороге.\n\nУ неё были голубые глаза и красный платок."
SECOND = "Люта вошла в дом.\n\nЕё карие глаза блестели."


class FakeModel:
    def __init__(self, *replies: dict):
        self.replies = list(replies)
        self.operations: list[str] = []

    def invoke_json(self, operation, messages, schema):
        self.operations.append(operation)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return schema.model_validate(reply)


@pytest.fixture
def session(client):
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db


@pytest.fixture
def book(session):
    project = Project(title="Тест", mode="writer")
    for position, (title, text) in enumerate([("Дорога", FIRST), ("Дом", SECOND)]):
        project.chapters.append(
            Chapter(position=position, title=title, text=text, content_hash=text_hash(text))
        )
    session.add(project)
    session.commit()
    return project


def test_remark_with_unverifiable_quote_is_dropped(book):
    chapter = book.chapters[0]
    model = FakeModel(
        {
            "remarks": [
                {"paragraph": 1, "quote": "голубые глаза", "category": "other", "problem": "p"},
                {"paragraph": 0, "quote": "этого нет в тексте", "problem": "выдумка"},
            ]
        }
    )
    remarks = service.check_text(model, chapter, service.KIND_EDITORIAL)
    assert len(remarks) == 1
    assert remarks[0].places[0].paragraph == 1
    assert model.operations == ["review_editorial"]


def test_wrong_paragraph_number_is_corrected_by_the_quote(book):
    model = FakeModel({"remarks": [{"paragraph": 0, "quote": "красный платок", "problem": "p"}]})
    remarks = service.check_text(model, book.chapters[0], service.KIND_GRAMMAR)
    assert remarks[0].places[0].paragraph == 1


def test_long_chapter_goes_in_several_calls():
    paragraphs = ["слово " * 100] * 30
    pieces = service.windows(paragraphs, limit=6000)
    assert len(pieces) > 1
    assert [i for piece in pieces for i in piece] == list(range(30))


def test_contradictions_cite_both_chapters(session, book):
    hero = Entity(project_id=book.id, kind="character", name="Люта")
    for chapter, text, quote in [
        (book.chapters[0], "голубые глаза", "голубые глаза"),
        (book.chapters[1], "карие глаза", "карие глаза"),
    ]:
        hero.facts.append(
            EntityFact(
                chapter_id=chapter.id,
                chapter_hash=chapter.content_hash,
                category="permanent",
                text=text,
                quote=quote,
                paragraph=1,
            )
        )
    session.add(hero)
    session.commit()
    model = FakeModel(
        {
            "contradictions": [
                {"facts": [1, 2], "problem": "цвет глаз"},
                {"facts": [1], "problem": "x"},
            ]
        }
    )
    remarks = service.check_contradictions(session, model, book)
    assert len(remarks) == 1  # a single-fact "contradiction" is dropped
    assert [p.chapter_title for p in remarks[0].places] == ["Дорога", "Дом"]


def test_review_api_is_for_writer_projects_only(client, session, book):
    book.mode = "reader"
    session.commit()
    answer = client.post(f"/api/projects/{book.id}/review", json={"kind": "contradictions"})
    assert answer.status_code == 409
    assert answer.json()["detail"] == "reader_mode_readonly"


def test_review_api_needs_a_configured_model(client, book):
    answer = client.post(
        f"/api/projects/{book.id}/review",
        json={"kind": "grammar", "chapter_id": book.chapters[0].id},
    )
    assert answer.status_code == 409
    assert answer.json()["detail"] == "text_model_not_configured"
