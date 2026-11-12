import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Chapter, Entity, EntityFact, Project, text_hash
from app.review import checks, prompts, service, typography

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


# ---------- ticks, languages, checks without a model ----------



def test_language_is_found_from_the_letters():
    assert checks.detect_language("Люта шла по дороге и щурилась. " * 5) == "ru"
    assert checks.detect_language("Люта ішла па дарозе і ўсміхалася. " * 5) == "be"
    assert checks.detect_language("Luta walked down the road. " * 5) == "en"
    assert checks.detect_language("12345") == "ru"  # too little text: the default


def test_russian_items_are_offered_only_for_russian_books():
    ru = {c.id for c in checks.offered("ru")}
    be = {c.id for c in checks.offered("be")}
    assert {"typography_ru", "participle_ru", "spelling"} <= ru
    assert "spelling" in be and not any(i.endswith("_ru") for i in be)


def test_chosen_falls_back_to_defaults_and_drops_foreign_items():
    defaults = checks.chosen("editorial", "ru", None)
    assert all(c.default for c in defaults) and defaults
    picked = checks.chosen("grammar", "be", ["spelling", "typography_ru", "nonsense"])
    assert [c.id for c in picked] == ["spelling"]


def test_prompt_lists_only_the_ticked_items():
    items = checks.chosen("editorial", "ru", ["participle_ru"])
    text = prompts.editorial([c.instruction for c in items], ["participle"])
    assert "Подъезжая" in text and "clichés" not in text


def test_typography_finds_and_fixes_russian_typesetting():
    text = '- Привет , - сказал он. "Ну..."  Да.\n\nВторой абзац - тоже.'
    found = typography.typography_findings(text.split("\n\n"))
    problems = " ".join(f.problem for f in found)
    for word in ("кавычки", "дефиса", "тире", "многоточия", "пробелы", "Пробел перед"):
        assert word in problems
    for f in found:
        assert f.quote in text.split("\n\n")[f.paragraph]
    assert (
        typography.fix_typography(text)
        == "— Привет, — сказал он. «Ну…» Да.\n\nВторой абзац — тоже."
    )


def test_yo_is_flagged_where_the_book_uses_it_elsewhere():
    known = typography.yo_words(["Он ещё шёл. Всё было тихо."])
    assert "все" not in known  # все/всё are different words
    found = typography.yo_findings(["Он еще шел домой."], known)
    assert {target for target, _ in found} == {"ещё", "шёл"}


def test_rhythm_finds_three_openings_in_a_row():
    found = typography.rhythm_findings(["Он встал. Он вышел. Он закурил. Ночь."], "ru")
    assert len(found) == 1 and "«он»: 3" in found[0].problem


def test_code_checks_run_without_a_model(client, session, book):
    book.chapters[0].text = 'Она сказала: "да".'
    session.commit()
    answer = client.post(
        f"/api/projects/{book.id}/review",
        json={"kind": "grammar", "chapter_id": book.chapters[0].id, "checks": ["typography_ru"]},
    )
    assert answer.status_code == 200
    remarks = answer.json()["remarks"]
    assert remarks and all(r["fixable"] for r in remarks)


def test_checks_api_reports_the_language(client, book):
    answer = client.get(f"/api/projects/{book.id}/review/checks").json()
    assert answer["language"] == "ru"
    assert any(c["id"] == "typography_ru" for c in answer["checks"])


def test_fix_saves_a_version_of_unsaved_work_first(client, session, book):
    from app.services import versions

    versions.commit(session, book, "start")
    book.chapters[0].text = 'Она сказала: "да"...'
    book.chapters[0].content_hash = text_hash(book.chapters[0].text)
    session.commit()
    answer = client.post(
        f"/api/projects/{book.id}/review/fix", json={"chapter_ids": [book.chapters[0].id]}
    ).json()
    assert answer["changed"] == [book.chapters[0].id]
    assert answer["version"] == 2
    session.expire_all()
    assert session.get(Chapter, book.chapters[0].id).text == "Она сказала: «да»…"
    saved = versions.latest_version(session, book.id)
    assert saved.label == "typography"
    assert saved.entries[0].revision.text == 'Она сказала: "да"...'
