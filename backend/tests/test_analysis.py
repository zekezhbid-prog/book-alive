import re

import pytest
from sqlalchemy.orm import Session

from app.analysis import entities as analysis
from app.analysis import prompts, runner
from app.api import analysis as analysis_api
from app.db import get_engine
from app.llm.calls import BadModelOutput, _parse, estimate_tokens
from app.models import (
    AnalysisRun,
    Chapter,
    ChapterExtraction,
    Entity,
    EntityFact,
    Project,
    text_hash,
)

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
                "named": False,
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
        if schema is analysis.Looks:
            return analysis.Looks(appearance="Облик: " + messages[-1].content.split("\n")[0])
        if schema is analysis.GeneralTexts:
            # The check returns every description unchanged.
            found = re.findall(r"^\[(\d+)\] [^\n]*\n([^\n]*)", messages[-1].content, re.MULTILINE)
            return analysis.GeneralTexts(
                texts=[analysis.GeneralText(number=int(n), text=t) for n, t in found]
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
        "check_characters",
        "looks_characters",  # one per card that has looks: only Рыхташ
    ]

    people = cast(session, project)
    assert set(people) == {"Рыхташ", "Люта"}  # "Дед" was merged into "Рыхташ"
    assert record.report == {"merged": [["Дед", "Рыхташ"]], "adopted": []}  # shown at the end
    assert record.finished_at is not None  # how long it took is shown too
    assert (
        record.stage == "looks" and record.stage_done == record.stage_total - 1
    )  # last step shown
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
    assert model.calls == [
        "find_characters",
        "merge_characters",
        "summarize_characters",
        "check_characters",
        "looks_characters",
    ]


def test_rerun_is_idempotent(session, project):
    model = FakeModel()
    run(session, project, model)
    before = {n: len(e.facts) for n, e in cast(session, project).items()}
    model.calls.clear()
    run(session, project, model)
    assert {n: len(e.facts) for n, e in cast(session, project).items()} == before
    assert model.calls == [
        "merge_characters",
        "summarize_characters",
        "check_characters",
        "looks_characters",
    ]


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


def test_unnamed_and_group_entries_are_kept_apart_and_not_fed_back(client, session, project):
    class Vague(FakeModel):
        def invoke_json(self, operation, messages, schema):
            if schema is analysis.ChapterEntities:
                text = messages[-1].content
                assert "Купцы" not in text.split("Chapter")[0]
                entries = [
                    {"name": "Рыхташ", "facts": []},
                    {"name": "Стары", "named": False, "facts": []},
                    {"name": "Купцы", "group": True, "facts": [{"text": "в шубах"}]},
                    {"name": "птушка", "facts": []},  # a bare mention, lower case
                    {"name": "стары", "aliases": ["Дед"], "facts": [{"text": "сівы"}]},
                ]
                if 'Chapter "Дорога"' in text:
                    entries.append({"name": "Стары", "named": True, "facts": []})
                return schema.model_validate({"entities": entries})
            if schema is analysis.Groups:
                return analysis.Groups(groups=[])
            return super().invoke_json(operation, messages, schema)

    run(session, project, Vague())
    cards = {
        c["name"]: c["uncertain"]
        for c in client.get(
            f"/api/projects/{project.id}/entities", params={"kind": "character"}
        ).json()
    }
    # "Стары" was named in the second chapter, so it is a character after all.
    # "птушка" was only mentioned: no card. "стары (also Дед)" took the proper name.
    assert cards == {"Рыхташ": False, "Стары": False, "Купцы": True, "Дед": False}


def test_a_chapter_calling_a_known_card_by_a_word_joins_it_through_the_alias(session, project):
    class Words(FakeModel):
        def invoke_json(self, operation, messages, schema):
            if schema is analysis.ChapterEntities:
                text = messages[-1].content
                if 'Chapter "Мельница"' in text:
                    entry = {
                        "name": "Рыхташ",
                        "facts": [{"category": "permanent", "text": "седая борода"}],
                    }
                else:
                    assert "- Рыхташ - седая борода" in text  # known, with a hint
                    entry = {"name": "Дзед", "aliases": ["Рыхташ"], "facts": [{"text": "кольчуга"}]}
                return schema.model_validate({"entities": [entry]})
            if schema is analysis.Groups:
                return analysis.Groups(groups=[])
            return super().invoke_json(operation, messages, schema)

    run(session, project, Words())
    people = cast(session, project)
    assert set(people) == {"Рыхташ"}
    assert {f.text for f in people["Рыхташ"].facts if f.text} == {"седая борода", "кольчуга"}


def test_new_summary_builds_on_the_old_one_and_skips_moments(session, project):
    run(session, project, FakeModel())
    card = cast(session, project)["Рыхташ"]
    card.summary = "Старый мельник, связной князя."
    card.facts.append(
        EntityFact(
            category="state",
            text="Сегодня злой и в мокром плаще",
            chapter_id=card.facts[0].chapter_id,
            chapter_hash=card.facts[0].chapter_hash,
        )
    )
    session.commit()
    seen = []

    class Watching(FakeModel):
        def invoke_json(self, operation, messages, schema):
            seen.append((schema, messages[-1].content))
            return super().invoke_json(operation, messages, schema)

    analysis.summarize_cards(session, Watching(), project.id, "character")
    listing = next(
        text for schema, text in seen if schema is analysis.Summaries and "Рыхташ" in text
    )
    assert "description so far: Старый мельник, связной князя." in listing
    # One chapter's state is not a lasting fact: not in the description, only in the looks.
    assert "Сегодня злой" not in listing
    looks = next(text for schema, text in seen if schema is analysis.Looks and "Рыхташ" in text)
    assert "] Сегодня злой и в мокром плаще (this chapter)" in looks
    assert "Люта" not in looks  # one card per request: nothing crosses over
    assert card.appearance.startswith("Облик: Рыхташ")


def test_summary_facts_come_from_every_chapter_in_turn():
    """A main character's description must cover the whole book, not its first chapters."""
    from types import SimpleNamespace

    facts = [
        SimpleNamespace(chapter_id=chapter, text=f"{chapter}-{n}", quote="")
        for chapter in ("a", "b", "c")
        for n in range(5)
    ]
    picked = analysis._spread(facts, {"a": 0, "b": 1, "c": 2}, 4, set())
    assert [f.text for f in picked] == ["a-0", "b-0", "c-0", "a-1"]


def test_a_card_without_a_name_joins_the_named_one_it_matches(session, project):
    first, second = project.chapters

    def card(name, chapter, text, uncertain=False):
        entity = Entity(project_id=project.id, kind="character", name=name, aliases=[])
        entity.uncertain = uncertain
        entity.facts = [
            EntityFact(chapter_id=chapter.id, chapter_hash="", category="permanent", text=text)
        ]
        session.add(entity)
        return entity

    named = card("Рыхташ", first, "седая борода")
    card("Люта", second, "красное платье")
    card("Люта", first, "рыжая").name = "Зіхцінка"
    old = card("старик", second, "седая борода", uncertain=True)
    session.commit()
    asked = []

    class Judge:
        def invoke_json(self, operation, messages, schema):
            asked.append(messages[-1].content)
            return analysis.Adoptions(matches=[analysis.Adoption(number=1, candidate="A")])

    analysis.adopt_uncertain(session, Judge(), project.id, "character")
    listing = asked[0]
    # The candidates are the named ones sharing its chapters or its company, best first.
    assert listing.startswith("[1] старик (no proper name)") and "A) Люта" in listing
    assert session.get(Entity, old.id) is None
    lyuta = next(
        e for e in analysis._entities(session, project.id, "character") if e.name == "Люта"
    )
    assert "старик" in lyuta.aliases and named.id


def test_general_check_takes_out_one_chapter_and_never_adds(session, project):
    run(session, project, FakeModel())
    people = cast(session, project)
    people["Рыхташ"].summary = "Старый мельник, связной князя. Он напоминает ей поесть."
    people["Люта"].summary = "Княжна."
    session.commit()
    seen = []

    class Checker:
        def invoke_json(self, operation, messages, schema):
            seen.append(messages[-1].content)
            return analysis.GeneralTexts(
                texts=[
                    analysis.GeneralText(number=1, text="Княжна, дочь князя, смелая и умная."),
                    analysis.GeneralText(number=2, text="Старый мельник, связной князя."),
                ]
            )

    analysis.keep_general(session, Checker(), [people["Люта"], people["Рыхташ"]], "character")
    assert "[2] Рыхташ\nСтарый мельник, связной князя. Он напоминает ей поесть." in seen[0]
    assert people["Рыхташ"].summary == "Старый мельник, связной князя."
    assert people["Люта"].summary == "Княжна."  # the answer grew: it added, so it is ignored


def test_usage_shows_one_line_per_action_with_rubles_and_balance(
    client, session, project, monkeypatch
):
    from sqlalchemy import select

    from app.llm import registry
    from app.models import Connection, UsageEvent

    made = session.scalar(select(Connection).where(Connection.name == "Hubris")) is None
    if made:
        session.add(Connection(name="Hubris", kind="openai", base_url="https://x/v1"))
    for operation, tokens in [("find_characters", 1_000_000), ("summarize_characters", 0)]:
        session.add(
            UsageEvent(
                project_id=project.id,
                operation=operation,
                connection_name="Hubris",
                model="m/one",
                input_tokens=tokens,
                output_tokens=tokens // 2,
                action_id="run1",
            )
        )
    session.add(
        UsageEvent(
            project_id=project.id,
            operation="chat",
            connection_name="Hubris",
            model="m/unpriced",
            input_tokens=10,
        )
    )
    session.commit()
    monkeypatch.setattr(registry, "model_prices", lambda c: {"m/one": (10.0, 40.0)})
    monkeypatch.setattr(registry, "balance_rub", lambda c: 1520.3)

    data = client.get(f"/api/projects/{project.id}/usage").json()
    assert data["total_rows"] == 2  # the search is one line, the question another
    run_row = next(r for r in data["rows"] if r["operation"] == "find_characters")
    assert run_row["calls"] == 2 and run_row["cost_rub"] == 30.0  # 10 + 0.5 * 40
    assert next(r for r in data["rows"] if r["operation"] == "chat")["cost_rub"] is None
    assert data["cost_rub"] == 30.0
    assert data["balance_rub"] == 1520.3
    page = client.get(f"/api/projects/{project.id}/usage?offset=1&limit=1").json()
    assert len(page["rows"]) == 1 and page["total_rows"] == 2
    later = client.get(f"/api/projects/{project.id}/usage?since=2999-01-01T00:00:00Z").json()
    assert later["total_rows"] == 0 and later["input_tokens"] == 0  # the period bounds rows
    monkeypatch.setattr(registry, "balance_rub", lambda c: registry.BALANCE_NO_LIMIT)
    data = client.get(f"/api/projects/{project.id}/usage").json()
    assert data["balance_rub"] is None and data["balance_problem"] == "no_limit"
    if made:  # other tests expect no such connection
        session.delete(session.scalar(select(Connection).where(Connection.name == "Hubris")))
        session.commit()


def test_two_named_cards_are_never_merged(session, project):
    """The model may say "Люта" and "Рыхташ" are one: both have proper names, so they stay
    apart; only a card without a proper name joins a named one."""

    class SaysNamedAreOne(FakeModel):
        def invoke_json(self, operation, messages, schema):
            if schema is analysis.Groups:
                # In name order: 1 Дед, 2 Люта, 3 Рыхташ.
                self.calls.append(operation)
                return analysis.Groups(groups=[[2, 3]])
            if schema is analysis.Adoptions:
                self.calls.append(operation)
                return analysis.Adoptions(matches=[])
            return super().invoke_json(operation, messages, schema)

    record = run(session, project, SaysNamedAreOne())
    assert {"Люта", "Рыхташ"} <= set(cast(session, project))
    assert record.report["merged"] == []


def test_rebuild_one_card_reads_its_chapters_and_rewrites_it(session, project):
    """ "Rebuild" on one card: only the chapters it is in or named in are read, and only
    for it; its facts, description and appearance are written anew, others stay."""
    from app.analysis import card as card_rebuild

    model = FakeModel()
    run(session, project, model)
    people = cast(session, project)
    lyuta_facts = len(people["Люта"].facts)
    rykhtash = people["Рыхташ"]
    rykhtash.summary = "Старое описание с ошибкой."
    session.commit()

    class Reader(FakeModel):
        def invoke_json(self, operation, messages, schema):
            if schema is card_rebuild.CardFacts:
                self.calls.append(operation)
                assert '"Рыхташ"' in messages[0].content
                if "Мельница" in messages[-1].content:
                    return card_rebuild.CardFacts(
                        facts=[
                            analysis.ExtractedFact(
                                category="permanent",
                                text="седая борода",
                                quote="длинная седая борода",
                            )
                        ]
                    )
                return card_rebuild.CardFacts(present=False)
            return super().invoke_json(operation, messages, schema)

    reader = Reader()
    record = AnalysisRun(
        project_id=project.id,
        kind="character",
        chapter_ids=[],
        entity_id=rykhtash.id,
        parts=["facts", "summary", "appearance"],
    )
    session.add(record)
    session.commit()
    runner.execute(session, record, reader)

    assert record.status == "done" and record.finished_at is not None
    assert reader.calls.count("rebuild_characters") == 2  # both chapters have it
    people = cast(session, project)
    texts = [f.text for f in people["Рыхташ"].facts if f.text]
    assert "седая борода" in texts and "хромает" not in texts
    assert "кольчуга" in texts  # "not here" where it was found before keeps the old facts
    assert people["Рыхташ"].summary.startswith("Связный рассказ")
    assert people["Рыхташ"].appearance.startswith("Облик")
    assert len(people["Люта"].facts) == lyuta_facts  # nobody else is touched
    assert "merge_characters" not in reader.calls


def test_rebuild_api_starts_a_card_run(client, session, project, monkeypatch):
    model = FakeModel()
    run(session, project, model)
    rykhtash = cast(session, project)["Рыхташ"]
    started = []
    monkeypatch.setattr(runner, "start", started.append)
    monkeypatch.setattr(analysis_api, "TextModel", lambda *a: None)
    data = client.post(f"/api/entities/{rykhtash.id}/rebuild", json={"parts": ["summary"]}).json()
    assert data["entity_id"] == rykhtash.id and data["entity_name"] == "Рыхташ"
    assert data["parts"] == ["summary"] and len(started) == 1
    stray = session.get(AnalysisRun, data["id"])
    stray.status = "done"  # nothing really ran: other tests must not see it running
    session.commit()


def test_balance_reads_hubris_key_answer(monkeypatch):
    """GET /v1/key wraps its answer in "data" (Hubris docs): the old reader looked at the
    top level and never found the balance."""
    import httpx

    from app.llm import registry as reg
    from app.models import Connection as Conn

    answers = {
        "account": {"data": {"money_view": "account", "balance_kopecks": 152030}},
        "own": {"data": {"money_view": "own", "balance_kopecks": None}},
        "limit": {"data": {"money_view": "own", "limit_remaining_kopecks": "19488"}},
    }
    for name, body in answers.items():
        monkeypatch.setattr(reg, "decrypt", lambda _: "sk-gw-test")
        monkeypatch.setattr(
            httpx,
            "get",
            lambda *a, _b=body, **k: httpx.Response(
                200, json=_b, request=httpx.Request("GET", "https://x/v1/key")
            ),
        )
        got = reg.balance_rub(Conn(name="Hubris", base_url="https://x/v1", api_key_encrypted="e"))
        assert got == {"account": 1520.3, "own": reg.BALANCE_NO_LIMIT, "limit": 194.88}[name]
