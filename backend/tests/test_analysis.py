import pytest
from sqlalchemy.orm import Session

from app.analysis import entities as analysis
from app.analysis import runner
from app.db import get_engine
from app.llm.calls import _parse, estimate_tokens
from app.models import AnalysisRun, Chapter, Entity, Project, text_hash

CHAPTER_1 = (
    "Рыхташ вошёл в мельницу. На нём был чёрный плащ.\n\n"
    "У старика была длинная седая борода и шрам через левую бровь."
)
CHAPTER_2 = "Дед снял плащ и надел кольчугу.\n\nЛюта стояла у окна в красном платье."

ANSWERS = {
    "Мельница": {
        "entities": [
            {
                "name": "Рыхташ",
                "aliases": ["старик", "Мельник"],
                "facts": [
                    {
                        "category": "permanent",
                        "text": "длинная седая борода",
                        "quote": "длинная седая  борода",  # spacing differs: still found
                    },
                    {"category": "state", "text": "чёрный плащ", "quote": "На нём был чёрный плащ"},
                    {
                        "category": "state",
                        "text": "хромает",
                        "quote": "Он сильно хромал",
                    },  # made up
                ],
            }
        ]
    },
    "Дорога": {
        "entities": [
            {
                "name": "Дед",
                "facts": [{"category": "state", "text": "кольчуга", "quote": "надел кольчугу"}],
            },
            {"name": "Люта", "facts": []},
        ]
    },
}


class FakeModel:
    """Stands in for TextModel: answers from the table above, counts calls."""

    def __init__(self):
        self.calls: list[str] = []
        self.fail_on: str | None = None

    def invoke_json(self, operation, messages, schema):
        self.calls.append(operation)
        if schema is analysis.Groups:
            # "Дед" and "Рыхташ" are the same man: entries 1 and 3 in name order.
            return analysis.Groups(groups=[[1, 3]])
        title = next(t for t in ANSWERS if f'Chapter "{t}"' in messages[-1].content)
        if title == self.fail_on:
            raise RuntimeError("rate limit")
        return schema.model_validate(ANSWERS[title])


@pytest.fixture
def session(client):
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db


@pytest.fixture
def project(session):
    book = Project(title="Тест", mode="writer")
    for position, (title, text) in enumerate([("Мельница", CHAPTER_1), ("Дорога", CHAPTER_2)]):
        book.chapters.append(
            Chapter(position=position, title=title, text=text, content_hash=text_hash(text))
        )
    session.add(book)
    session.commit()
    return book


def run(session, project, model, chapters=None):
    record = AnalysisRun(
        project_id=project.id,
        kind="character",
        chapter_ids=[c.id for c in (chapters or project.chapters)],
    )
    session.add(record)
    session.commit()
    runner.execute(session, record, model)
    return record


def cast(session, project):
    session.expire_all()
    rows = session.query(Entity).filter_by(project_id=project.id, kind="character").all()
    return {e.name: e for e in rows}


def test_full_run_builds_cards_with_verified_quotes(session, project):
    model = FakeModel()
    record = run(session, project, model)
    assert record.status == "done"
    assert len(record.done_chapter_ids) == 2
    assert model.calls == ["find_characters", "find_characters", "merge_characters"]

    people = cast(session, project)
    assert set(people) == {"Рыхташ", "Люта"}  # "Дед" was merged into "Рыхташ"
    rykhtash = people["Рыхташ"]
    # "старик" is a common noun, not a name: it is not kept as an alias.
    assert set(rykhtash.aliases) == {"Мельник", "Дед"}
    facts = {f.text: f for f in rykhtash.facts if f.category != analysis.FACT_MENTION}
    assert set(facts) == {"длинная седая борода", "чёрный плащ", "хромает", "кольчуга"}
    assert facts["длинная седая борода"].paragraph == 1
    assert facts["чёрный плащ"].paragraph == 0
    # The invented quote is dropped; the fact stays, without a source.
    assert (facts["хромает"].quote, facts["хромает"].paragraph) == ("", None)
    # Present in both chapters, one mention each.
    mentions = [f for f in rykhtash.facts if f.category == analysis.FACT_MENTION]
    assert len(mentions) == 2


def test_failed_run_resumes_without_paying_twice(session, project):
    model = FakeModel()
    model.fail_on = "Дорога"
    record = run(session, project, model)
    assert record.status == "failed"
    assert "rate limit" in record.error
    assert len(record.done_chapter_ids) == 1
    assert set(cast(session, project)) == {"Рыхташ"}

    model.fail_on = None
    model.calls.clear()
    again = run(session, project, model)
    assert again.status == "done"
    # The first chapter comes from the stored answer: only the second one is read.
    assert model.calls == ["find_characters", "merge_characters"]


def test_rerun_is_idempotent(session, project):
    model = FakeModel()
    run(session, project, model)
    before = {n: len(e.facts) for n, e in cast(session, project).items()}
    model.calls.clear()
    run(session, project, model)
    assert {n: len(e.facts) for n, e in cast(session, project).items()} == before
    assert model.calls == ["merge_characters"]


def test_estimate_skips_chapters_already_read(session, project):
    first = analysis.estimate(session, project.chapters, "character")
    assert (first.chapters, first.cached, first.requests) == (2, 0, 3)
    run(session, project, FakeModel())
    assert analysis.estimate(session, project.chapters, "character").requests == 0

    # Editing a chapter makes its stored answer useless: it has to be read again.
    chapter = project.chapters[0]
    chapter.text += "\n\nНовый абзац."
    chapter.content_hash = text_hash(chapter.text)
    session.commit()
    after = analysis.estimate(session, project.chapters, "character")
    assert (after.cached, after.requests) == (1, 2)


def test_api_reports_stale_cards_after_an_edit(client, session, project):
    run(session, project, FakeModel())
    cards = client.get(f"/api/projects/{project.id}/entities", params={"kind": "character"}).json()
    assert [c["name"] for c in cards] == ["Рыхташ", "Люта"]  # most chapters first
    assert not any(c["stale"] for c in cards)

    first = project.chapters[0].id
    client.patch(f"/api/chapters/{first}", json={"text": CHAPTER_1 + "\n\nПравка."})
    cards = client.get(f"/api/projects/{project.id}/entities", params={"kind": "character"}).json()
    assert {c["name"]: c["stale"] for c in cards} == {"Рыхташ": True, "Люта": False}

    card = client.get(f"/api/entities/{cards[0]['id']}").json()
    assert [f["text"] for f in card["permanent"]] == ["длинная седая борода"]
    assert [(t["chapter_title"], t["stale"]) for t in card["timeline"]] == [
        ("Мельница", True),
        ("Дорога", False),
    ]
    assert [f["text"] for f in card["timeline"][1]["facts"]] == ["кольчуга"]


def test_run_needs_a_configured_model(client, project):
    response = client.post(f"/api/projects/{project.id}/analysis", json={"kind": "character"})
    assert (response.status_code, response.json()["detail"]) == (409, "text_model_not_configured")


def test_parse_accepts_fenced_json():
    reply = 'Вот результат:\n```json\n{"groups": [[1, 2]]}\n```'
    assert _parse(reply, analysis.Groups).groups == [[1, 2]]


def test_token_estimate_counts_cyrillic_denser():
    assert estimate_tokens("привет" * 10) > estimate_tokens("hello!" * 10)
