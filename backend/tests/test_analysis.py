import re

import pytest
from sqlalchemy.orm import Session

from app.analysis import entities as analysis
from app.analysis import prompts, runner
from app.api import analysis as analysis_api
from app.db import get_engine
from app.llm.calls import BadModelOutput, _parse, estimate_tokens
from app.models import AnalysisRun, Chapter, ChapterExtraction, Entity, Project, text_hash

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
        self.bad_json_times = 0  # that many chapter reads answer with broken JSON first

    def invoke_json(self, operation, messages, schema):
        self.calls.append(operation)
        if schema is analysis.Summaries:
            numbers = re.findall(r"^\[(\d+)\]", messages[-1].content, re.MULTILINE)
            return analysis.Summaries(
                summaries=[
                    analysis.CardSummary(number=int(n), text=f"Связный рассказ {n}.")
                    for n in numbers
                ]
            )
        if operation.startswith("find_") and self.bad_json_times:
            self.bad_json_times -= 1
            raise BadModelOutput("Expecting property name enclosed in double quotes")
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


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(runner, "RESTART_PAUSE", 0)


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
    assert model.calls == [
        "find_characters",
        "find_characters",
        "merge_characters",
        "summarize_characters",
    ]

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
    assert model.calls == ["find_characters", "merge_characters", "summarize_characters"]


def test_rerun_is_idempotent(session, project):
    model = FakeModel()
    run(session, project, model)
    before = {n: len(e.facts) for n, e in cast(session, project).items()}
    model.calls.clear()
    run(session, project, model)
    assert {n: len(e.facts) for n, e in cast(session, project).items()} == before
    assert model.calls == ["merge_characters", "summarize_characters"]


def test_estimate_skips_chapters_already_read(session, project):
    first = analysis.estimate(session, project.chapters, "character")
    assert (first.chapters, first.cached, first.requests) == (2, 0, 4)
    run(session, project, FakeModel())
    assert analysis.estimate(session, project.chapters, "character").requests == 0

    # Editing a chapter makes its stored answer useless: it has to be read again.
    chapter = project.chapters[0]
    chapter.text += "\n\nНовый абзац."
    chapter.content_hash = text_hash(chapter.text)
    session.commit()
    after = analysis.estimate(session, project.chapters, "character")
    assert (after.cached, after.requests) == (1, 3)


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


def test_user_can_split_a_wrongly_merged_name_and_merge_it_back(client, session, project):
    run(session, project, FakeModel())
    rykhtash = cast(session, project)["Рыхташ"]
    assert "Дед" in rykhtash.aliases

    # "Дед" is someone else: he gets his own card with the facts the book gives under that name.
    separate = client.post(f"/api/entities/{rykhtash.id}/split", json={"name": "Дед"}).json()
    assert separate["name"] == "Дед"
    assert [f["text"] for f in separate["timeline"][0]["facts"]] == ["кольчуга"]
    people = cast(session, project)
    assert "Дед" not in people["Рыхташ"].aliases
    assert "кольчуга" not in {f.text for f in people["Рыхташ"].facts}

    # A later run over the whole book does not undo the user's decision.
    model = FakeModel()
    run(session, project, model)
    people = cast(session, project)
    assert set(people) == {"Рыхташ", "Люта", "Дед"}
    assert "Дед" not in people["Рыхташ"].aliases

    # And the opposite decision: the user merges them, which also survives a full run.
    client.post(f"/api/entities/{people['Рыхташ'].id}/merge", json={"other_id": people["Дед"].id})
    run(session, project, FakeModel())
    people = cast(session, project)
    assert set(people) == {"Рыхташ", "Люта"}
    assert "Дед" in people["Рыхташ"].aliases
    assert "кольчуга" in {f.text for f in people["Рыхташ"].facts}


def test_merge_rejects_cards_of_different_kinds(client, session, project):
    run(session, project, FakeModel())
    person = cast(session, project)["Люта"]
    assert (
        client.post(f"/api/entities/{person.id}/merge", json={"other_id": person.id}).status_code
        == 422
    )


def test_stale_chapters_are_listed_and_deleted_ones_forgotten(client, session, project):
    run(session, project, FakeModel())
    url = f"/api/projects/{project.id}/stale"
    assert client.get(url, params={"kind": "character"}).json() == {
        "chapter_ids": [],
        "orphaned_facts": 0,
    }
    first, second = project.chapters
    client.patch(f"/api/chapters/{first.id}", json={"text": CHAPTER_1 + "\n\nПравка."})
    client.delete(f"/api/chapters/{second.id}")
    report = client.get(url, params={"kind": "character"}).json()
    assert report["chapter_ids"] == [first.id]
    assert report["orphaned_facts"] > 0

    # Reading the changed chapter again also drops what came from the deleted one.
    session.expire_all()
    project = session.get(type(project), project.id)
    run(session, project, FakeModel(), chapters=[project.chapters[0]])
    assert client.get(url, params={"kind": "character"}).json() == {
        "chapter_ids": [],
        "orphaned_facts": 0,
    }
    assert set(cast(session, project)) == {"Рыхташ"}  # "Люта" lived only in the deleted chapter


class ProfileModel(FakeModel):
    """Adds a general-description fact to one answer."""

    def invoke_json(self, operation, messages, schema):
        result = super().invoke_json(operation, messages, schema)
        if schema is analysis.ChapterEntities and 'Chapter "Мельница"' in messages[-1].content:
            for item in result.entities:
                if item.name == "Рыхташ":
                    item.facts.append(
                        analysis.ExtractedFact(
                            category="profile", text="старый мельник, живёт один"
                        )
                    )
        return result


def test_profile_facts_go_to_the_top_of_the_card_not_to_looks_or_timeline(session, project, client):
    run(session, project, ProfileModel())
    rykhtash = cast(session, project)["Рыхташ"]
    card = client.get(f"/api/entities/{rykhtash.id}").json()
    assert [f["text"] for f in card["profile"]] == ["старый мельник, живёт один"]
    assert "старый мельник, живёт один" not in [f["text"] for f in card["permanent"]]
    assert all(
        f["text"] != "старый мельник, живёт один" for e in card["timeline"] for f in e["facts"]
    )


def test_parse_forgives_trailing_commas():
    reply = '{"groups": [[1, 2,],],}'
    assert _parse(reply, analysis.Groups).groups == [[1, 2]]


def test_broken_model_answers_are_retried_by_the_run_itself(session, project):
    model = FakeModel()
    model.bad_json_times = 2
    record = run(session, project, model)
    assert record.status == "done"
    assert len(record.done_chapter_ids) == 2


def test_run_gives_up_after_repeated_failures(session, project):
    model = FakeModel()
    model.bad_json_times = 100
    record = run(session, project, model)
    assert record.status == "failed"
    assert "double quotes" in record.error
    # No coherent description is written from a run that broke off.
    assert all(e.summary == "" for e in cast(session, project).values())


def test_finished_run_writes_a_coherent_description_of_each_card(session, project, client):
    run(session, project, FakeModel())
    people = cast(session, project)
    assert people["Рыхташ"].summary.startswith("Связный рассказ")
    # Люта has no facts but her name: there is nothing to tell about her yet.
    assert people["Люта"].summary == ""
    card = client.get(f"/api/entities/{people['Рыхташ'].id}").json()
    assert card["summary"] == people["Рыхташ"].summary


def test_cancelled_run_describes_what_was_found_so_far(session, project):
    class Cancelling(FakeModel):
        def invoke_json(self, operation, messages, schema):
            result = super().invoke_json(operation, messages, schema)
            if operation == "find_characters":
                record = session.query(AnalysisRun).filter_by(project_id=project.id).one()
                record.cancel_requested = True
                session.commit()
            return result

    record = run(session, project, Cancelling())
    assert record.status == "cancelled", record.error
    assert len(record.done_chapter_ids) == 1
    assert cast(session, project)["Рыхташ"].summary


def test_rescan_from_scratch_reads_again_and_forgets_old_cards(session, project):
    run(session, project, FakeModel())
    people = cast(session, project)
    people["Люта"].standalone = True  # the user's own decision: the card stays
    session.commit()

    class Forgetful(FakeModel):
        """The new prompt no longer finds "Люта" nor the old man in the second chapter."""

        def invoke_json(self, operation, messages, schema):
            answer = super().invoke_json(operation, messages, schema)
            if isinstance(answer, analysis.ChapterEntities):
                answer.entities = [e for e in answer.entities if e.name == "Рыхташ"]
            return answer

    assert analysis.estimate(session, project.chapters, "character", fresh=True).cached == 0
    analysis.start_fresh(session, project.id, project.chapters, "character")
    session.commit()
    model = Forgetful()
    run(session, project, model)
    # Both chapters are read again although their text did not change.
    assert model.calls.count("find_characters") == 2
    people = cast(session, project)
    assert set(people) == {"Рыхташ", "Люта"}
    assert people["Люта"].facts == []  # kept, but nothing from the old run is left on it
    assert "Дед" not in people["Рыхташ"].aliases  # nothing carried over from the old run


def test_api_rescan_from_scratch_drops_stored_answers(client, session, project, monkeypatch):
    run(session, project, FakeModel())
    started = []
    monkeypatch.setattr(analysis_api.runner, "start", started.append)
    monkeypatch.setattr(
        analysis_api, "TextModel", lambda *a: type("M", (), {"request_overhead": 0})
    )
    body = {"kind": "character", "chapter_ids": [], "fresh": True}
    assert (
        client.post(f"/api/projects/{project.id}/analysis/estimate", json=body).json()["cached"]
        == 0
    )
    assert client.post(f"/api/projects/{project.id}/analysis", json=body).status_code == 200
    session.expire_all()
    assert session.query(ChapterExtraction).filter_by(project_id=project.id).count() == 0
    assert cast(session, project) == {}
    assert len(started) == 1


def test_characters_are_living_beings_and_objects_go_with_locations():
    characters = prompts.extract_system("character")
    assert "living, animate beings only" in characters
    assert "Never list objects" in characters
    locations = prompts.extract_system("location")
    assert "notable inanimate things" in locations
    assert prompts.summary_system("location").count("locations and objects") == 1


def test_dialog_knows_which_chapters_are_read_and_which_changed(client, session, project):
    url = f"/api/projects/{project.id}/analysis/chapters"
    assert client.get(url, params={"kind": "character"}).json() == {"read": [], "changed": []}
    run(session, project, FakeModel(), chapters=project.chapters[:1])
    first, second = project.chapters
    status = client.get(url, params={"kind": "character"}).json()
    assert status == {"read": [first.id], "changed": []}

    first.text += "\n\nНовый абзац."
    first.content_hash = text_hash(first.text)
    session.commit()
    status = client.get(url, params={"kind": "character"}).json()
    assert status == {"read": [], "changed": [first.id]}
    assert second.id not in status["read"]


def test_a_wrong_alias_does_not_swallow_another_character(session, project):
    """The model once gave a friend's name as a nickname: the friend keeps a card of his own."""

    class Confused(FakeModel):
        def invoke_json(self, operation, messages, schema):
            if schema is analysis.ChapterEntities:
                text = messages[-1].content
                if 'Chapter "Мельница"' in text:
                    return schema.model_validate(
                        {"entities": [{"name": "Рыхташ", "aliases": ["Люта"], "facts": []}]}
                    )
                assert "Люта" not in text.split("Chapter")[0]  # not fed back as known
                return schema.model_validate(
                    {
                        "entities": [
                            {"name": "Рыхташ", "aliases": ["Люта"], "facts": []},
                            {"name": "Люта", "facts": []},
                        ]
                    }
                )
            if schema is analysis.Groups:
                return analysis.Groups(groups=[])
            return super().invoke_json(operation, messages, schema)

    run(session, project, Confused())
    people = cast(session, project)
    assert set(people) == {"Рыхташ", "Люта"}
    assert people["Рыхташ"].aliases == []
