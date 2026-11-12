import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Chapter, ChapterExtraction, Entity, EntityFact, Project, text_hash
from app.review import checks, continuity, prompts, service, typography

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


# ---- whole-book contradictions beyond the card facts ----


def _items(*ids):
    return [checks.BY_ID[i] for i in ids]


def test_new_contradiction_items_are_offered():
    ids = {c.id for c in checks.offered("ru") if c.kind == "contradictions"}
    assert {"name_variants", "timeline", "age", "knowledge", "missing", "revived"} <= ids
    assert checks.BY_ID["missing"].engine == checks.CODE
    assert {c.id for c in checks.CHECKS if c.reads_text} == {
        "timeline",
        "age",
        "knowledge",
        "revived",
    }


def test_chapter_notes_are_read_once_and_quotes_verified(session, book):
    chapter = book.chapters[0]
    model = FakeModel(
        {
            "notes": [
                {"paragraph": 0, "quote": "шла по дороге", "type": "time", "note": "утро"},
                {"paragraph": 1, "quote": "нет такого", "type": "time", "note": "выдумка"},
            ]
        }
    )
    assert continuity.read_notes(session, model, book, chapter) is True
    assert continuity.read_notes(session, model, book, chapter) is False  # same text: cached
    assert model.operations == ["review_notes"]
    notes = continuity.stored_notes(session, book)[chapter.id]
    assert [n.note for n in notes] == ["утро"]
    # Changed text: the old notes no longer count.
    chapter.text += "\n\nНаступила ночь."
    chapter.content_hash = text_hash(chapter.text)
    session.commit()
    assert chapter.id not in continuity.stored_notes(session, book)


def test_timeline_compares_notes_of_both_chapters(session, book):
    for chapter, quote, note in [
        (book.chapters[0], "шла по дороге", "через два дня"),
        (book.chapters[1], "вошла в дом", "прошла неделя"),
    ]:
        session.add(
            ChapterExtraction(
                project_id=book.id,
                chapter_id=chapter.id,
                kind=continuity.NOTES_KIND,
                chapter_hash=chapter.content_hash,
                payload={
                    "version": prompts.NOTES_VERSION,
                    "notes": [{"paragraph": 0, "quote": quote, "type": "time", "note": note}],
                },
            )
        )
    session.commit()
    model = FakeModel(
        {"contradictions": [{"check": "timeline", "facts": [1, 2], "problem": "не сходится"}]}
    )
    remarks = service.check_contradictions(session, model, book, _items("timeline"))
    assert len(remarks) == 1
    assert remarks[0].category == "timeline"
    assert [p.quote for p in remarks[0].places] == ["шла по дороге", "вошла в дом"]
    assert model.operations == ["review_continuity"]


def test_name_variants_need_both_spellings_in_the_text(session, book):
    book.chapters[1].text = "Лютa вошла в дом.\n\nЛюте было весело. Люта Гельга."
    session.add(Entity(project_id=book.id, kind="character", name="Люта", aliases=["Лютта"]))
    session.commit()
    model = FakeModel(
        {
            "variants": [
                {"names": ["Люта", "Лютта"], "problem": "два написания"},  # Лютта not in text
            ]
        }
    )
    assert service.check_contradictions(session, model, book, _items("name_variants")) == []
    book.chapters[0].text = "Лютта шла по дороге."
    session.commit()
    remarks = service.check_contradictions(session, model, book, _items("name_variants"))
    assert [p.chapter_title for p in remarks[0].places] == ["Дом", "Дорога"]


def test_missing_character_found_without_a_model(session):
    project = Project(title="Длинная", mode="writer")
    for n in range(12):
        text = "Мирон пришёл." if n < 4 else "Пусто."
        project.chapters.append(
            Chapter(position=n, title=f"Глава {n + 1}", text=text, content_hash=text_hash(text))
        )
    session.add(project)
    session.commit()
    session.add(Entity(project_id=project.id, kind="character", name="Мирон"))
    session.commit()
    remarks = service.check_contradictions(session, None, project, _items("missing"))
    assert len(remarks) == 1
    assert "Глава 4" in remarks[0].problem and "8" in remarks[0].problem
    assert remarks[0].places[0].chapter_title == "Глава 4"


def test_review_api_reads_notes_chapter_by_chapter(client, session, book, monkeypatch):
    calls = []
    monkeypatch.setattr(continuity, "read_notes", lambda s, m, p, c: calls.append(c.id) or True)
    monkeypatch.setattr("app.api.review.TextModel", lambda *a, **k: object())
    answer = client.post(
        f"/api/projects/{book.id}/review",
        json={"kind": "contradictions", "chapter_id": book.chapters[0].id, "checks": ["timeline"]},
    )
    assert answer.status_code == 200 and answer.json()["remarks"] == []
    assert calls == [book.chapters[0].id]
    # A chapter with only card items ticked needs no reading at all.
    answer = client.post(
        f"/api/projects/{book.id}/review",
        json={"kind": "contradictions", "chapter_id": book.chapters[0].id, "checks": ["looks"]},
    )
    assert answer.status_code == 200 and calls == [book.chapters[0].id]


# ---- beta reader ----


class FakeTextModel:
    def __init__(self, reply):
        self.reply = reply
        self.messages = []

    def invoke(self, operation, messages):
        self.messages.append(messages)
        return self.reply


def test_beta_review_is_kept_with_the_chapter(client, session, book, monkeypatch):
    session.add(
        Entity(project_id=book.id, kind="character", name="Люта", summary="Княжна. Смелая.")
    )
    session.commit()
    fake = FakeTextModel("## Что понравилось\n**Платок** запомнился.")
    monkeypatch.setattr("app.api.review.TextModel", lambda *a, **k: fake)
    chapter = book.chapters[1]
    answer = client.post(
        f"/api/projects/{book.id}/beta",
        json={
            "chapter_id": chapter.id,
            "reader": "critic",
            "tone": "honest",
            "asks": ["liked", "x"],
        },
    )
    assert answer.status_code == 200
    data = answer.json()
    assert data["text"] == "Что понравилось\nПлаток запомнился."  # Markdown stripped
    assert data["asks"] == ["liked"] and data["reader"] == "critic" and not data["outdated"]
    system, human = fake.messages[0]
    assert "critic" in system.content and "what you liked" in system.content
    assert "boring" not in system.content
    assert "chapter 2 of 2" in human.content and "Люта: Княжна" in human.content
    assert "Дорога" in human.content  # the title of the chapter before

    chapter.text += "\n\nНовое."
    chapter.content_hash = text_hash(chapter.text)
    session.commit()
    listed = client.get(f"/api/projects/{book.id}/beta").json()
    assert [r["outdated"] for r in listed] == [True]
    assert client.delete(f"/api/projects/{book.id}/beta/{data['id']}").status_code == 204
    assert client.get(f"/api/projects/{book.id}/beta").json() == []


# ---------------------------------------------------------------- numbers by chapter

from app.review import stats


def test_sentences_end_on_marks_with_closing_quotes():
    found = stats.sentences("Он ушёл. «Куда?» — спросила она… И всё!")
    assert found == ["Он ушёл.", "«Куда?» — спросила она…", "И всё!"]


def test_dialogue_counts_the_lines_but_not_the_authors_words():
    line = "— Иду домой, — сказал Пётр. — Жди меня."
    assert stats.dialogue_words(line, "ru") == 4  # «Иду домой» + «Жди меня»
    assert stats.dialogue_words("Он прочёл «Войну и мир» за ночь.", "ru") == 0
    assert stats.dialogue_words("Она сказала: «Я сюда больше не приду».", "ru") == 5
    assert stats.dialogue_words('"I will not come back here," she said.', "en") == 6


def test_chapter_numbers_skip_service_words():
    text = (
        "Люта шла по дороге и думала о доме. Дорога была длинной.\n\n"
        "— Люта, иди сюда, — позвал отец. — Дорога ждёт.\n\n"
        "И она пошла по дороге, потому что дорога вела домой, и Люта это знала давно."
    )
    chapter, _ = stats.chapter_stats("c1", "Дорога", text, "ru")
    assert chapter.paragraphs == 3
    assert chapter.sentences == 5
    assert chapter.longest[0].paragraph == 2
    top = {w.word: w.count for w in chapter.top_words}
    assert top["люта"] == 3
    assert "что" not in top and "она" not in top
    assert 0 < chapter.dialogue < 0.3


def test_stats_api_gives_every_chapter_and_the_book(client, session, book):
    answer = client.get(f"/api/projects/{book.id}/review/stats")
    assert answer.status_code == 200
    data = answer.json()
    assert [c["title"] for c in data["chapters"]] == ["Дорога", "Дом"]
    assert data["words"] == sum(c["words"] for c in data["chapters"])
    assert data["language"] == "ru"
    assert data["chapters"][0]["longest"][0]["paragraph"] == 1


def test_stats_of_an_empty_chapter_are_zero():
    chapter, _ = stats.chapter_stats("c", "", "", "ru")
    assert (chapter.words, chapter.sentences, chapter.avg_sentence, chapter.dialogue) == (
        0,
        0,
        0.0,
        0.0,
    )
