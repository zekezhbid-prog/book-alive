"""Improve one card: keep what it has, add what is missing, hear the author."""

# ruff: noqa: F811 - the fixtures come from test_analysis

from app.analysis import card as card_rebuild
from app.analysis import card_rules, deep, runner
from app.analysis import entities as analysis
from app.api import analysis as analysis_api
from app.models import AnalysisRun, Entity
from tests.test_analysis import (  # noqa: F401 - fixtures
    FakeModel,
    cast,
    no_pause,
    project,
    run,
    session,
)


class Improver(FakeModel):
    """Chapter "Мельница": one new fact, the cloak is wrong, note 1 is in the text."""

    def __init__(self):
        super().__init__()
        self.requests: list[str] = []

    def invoke_json(self, operation, messages, schema):
        self.requests.append(messages[0].content + "\n" + messages[-1].content)
        if schema is card_rebuild.Improvement:
            self.calls.append(operation)
            text = messages[-1].content
            if "Мельница" not in text:
                return card_rebuild.Improvement(present=True)
            assert "Known facts:" in text and "длинная седая борода" in text
            cloak = next(
                int(line[1 : line.index("]")])
                for line in text.split("\n")
                if line.startswith("[") and "чёрный плащ" in line
            )
            return card_rebuild.Improvement(
                facts=[
                    analysis.ExtractedFact(
                        category="permanent", text="шрам", quote="шрам через левую бровь"
                    ),
                    # Says again what is known: not added twice.
                    analysis.ExtractedFact(
                        category="permanent",
                        text="длинная седая борода",
                        quote="длинная седая борода",
                    ),
                ],
                wrong=[cloak, 99],
                confirmed=[1],
            )
        return super().invoke_json(operation, messages, schema)


def improve(session, entity, model, wishes="", mode=card_rebuild.MODE_IMPROVE):
    record = AnalysisRun(
        project_id=entity.project_id,
        kind=entity.kind,
        chapter_ids=[],
        entity_id=entity.id,
        parts=list(card_rebuild.PARTS),
        mode=mode,
        wishes=wishes,
    )
    session.add(record)
    session.commit()
    runner.execute(session, record, model)
    return record


def test_improve_keeps_good_facts_adds_new_and_drops_wrong(session, project):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]
    rostan.summary = "Мельник и дед."
    rostan.author_notes = ["шрам через бровь", "ему 70 лет"]
    session.commit()
    model = Improver()
    record = improve(session, rostan, model, wishes="Он не носит плаща")
    assert record.status == "done", record.error
    assert model.calls.count("improve_characters") == 2
    rostan = cast(session, project)["Ростан"]
    texts = [f.text for f in rostan.facts if f.text]
    assert "длинная седая борода" in texts and texts.count("длинная седая борода") == 1
    assert "шрам" in texts  # new
    assert "кольчуга" in texts  # the other chapter keeps its facts
    assert "чёрный плащ" not in texts  # the wish says it is wrong
    # Note 1 is in the text now, so it is a fact; the rest and the wish stay notes.
    assert rostan.author_notes == ["ему 70 лет", "Он не носит плаща"]
    # The description is improved, not thrown away: the old one goes into the request.
    summary_request = next(r for r in model.requests if "description so far: Мельник и дед." in r)
    assert "author's notes: ему 70 лет; Он не носит плаща" in summary_request
    assert any("author's notes:" in r and "appearance" in r for r in model.requests)


def test_scratch_still_replaces_the_facts(session, project):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]

    class Reader(FakeModel):
        def invoke_json(self, operation, messages, schema):
            if schema is card_rebuild.CardFacts:
                self.calls.append(operation)
                assert "the author says: высокий" in messages[0].content
                return card_rebuild.CardFacts(present=True)
            return super().invoke_json(operation, messages, schema)

    reader = Reader()
    record = improve(session, rostan, reader, wishes="высокий", mode="")
    assert record.status == "done", record.error
    assert "rebuild_characters" in reader.calls
    assert not [f for f in cast(session, project)["Ростан"].facts if f.text]


def card(session, project, name, chapters, uncertain=False, facts=0):
    entity = Entity(project_id=project.id, kind="character", name=name, uncertain=uncertain)
    for number in range(chapters):
        chapter = project.chapters[number % len(project.chapters)]
        entity.facts.append(
            analysis.EntityFact(
                chapter_id=chapter.id if number < len(project.chapters) else f"x{number}",
                chapter_hash="",
                category=analysis.FACT_MENTION,
            )
        )
    for number in range(facts):
        entity.facts.append(
            analysis.EntityFact(
                chapter_id=project.chapters[0].id,
                chapter_hash="",
                category="permanent",
                text=f"факт {number}",
            )
        )
    return entity


def test_merge_keeps_the_named_card_then_the_more_frequent(session, project):
    named = card(session, project, "Ростан", 1)
    word = card(session, project, "старик", 2, uncertain=True)
    assert card_rules.merge_main(word, named) == (named, word)
    often = card(session, project, "Узей", 2)
    assert card_rules.merge_main(named, often) == (often, named)
    rich = card(session, project, "Лана", 1, facts=3)
    assert card_rules.merge_main(named, rich) == (rich, named)
    twin = card(session, project, "Зміцер", 1)
    assert card_rules.merge_main(named, twin) == (named, twin)  # a tie: the first one stays


def test_improve_api_merges_by_the_rules_and_starts_the_run(client, session, project, monkeypatch):
    run(session, project, FakeModel())
    people = cast(session, project)
    word = Entity(
        project_id=project.id,
        kind="character",
        name="старик",
        uncertain=True,
        author_notes=["седой"],
    )
    session.add(word)
    session.commit()
    people["Ростан"].author_notes = ["мельник"]
    session.commit()
    word_id = word.id
    started = []
    monkeypatch.setattr(runner, "start", started.append)
    monkeypatch.setattr(analysis_api, "TextModel", lambda *a: None)
    # Started from the word card: the named one stays all the same.
    data = client.post(
        f"/api/entities/{word_id}/improve",
        json={"wishes": "  ему 70  ", "merge_with": people["Ростан"].id},
    ).json()
    assert data["entity_id"] == people["Ростан"].id and len(started) == 1
    record = session.get(AnalysisRun, data["run"]["id"])
    assert record.mode == card_rebuild.MODE_IMPROVE and record.wishes == "ему 70"
    session.expire_all()
    assert session.get(Entity, word_id) is None
    assert session.get(Entity, people["Ростан"].id).author_notes == ["мельник", "седой"]
    record.status = "done"  # nothing really ran: other tests must not see it running
    session.commit()
    scratch = client.post(
        f"/api/entities/{people['Ростан'].id}/improve", json={"scratch": True}
    ).json()
    assert session.get(AnalysisRun, scratch["run"]["id"]).mode == ""
    session.get(AnalysisRun, scratch["run"]["id"]).status = "done"
    session.commit()


def test_merge_with_a_card_of_another_kind_is_refused(client, session, project, monkeypatch):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]
    mill = Entity(project_id=project.id, kind="location", name="Мельница")
    session.add(mill)
    session.commit()
    monkeypatch.setattr(analysis_api, "TextModel", lambda *a: None)
    response = client.post(f"/api/entities/{rostan.id}/improve", json={"merge_with": mill.id})
    assert response.status_code == 422


def test_notes_can_be_edited(client, session, project):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]
    data = client.put(
        f"/api/entities/{rostan.id}/notes", json={"notes": [" высокий ", "", "седой"]}
    ).json()
    assert data["author_notes"] == ["высокий", "седой"]


def test_a_main_card_is_improved_by_the_strong_model(session, project, monkeypatch):
    run(session, project, FakeModel())
    people = cast(session, project)
    monkeypatch.setattr(deep, "MAIN_MIN_CHAPTERS", 2)
    assert card_rules.is_main(session, people["Ростан"].id)  # 2 chapters
    assert not card_rules.is_main(session, people["Лана"].id)  # 1 chapter
    monkeypatch.setattr(card_rules.settings, "deep_main_limit", 0)
    assert not card_rules.is_main(session, people["Ростан"].id)


def test_merge_only_calls_no_model(client, session, project, monkeypatch):
    run(session, project, FakeModel())
    people = cast(session, project)
    word = Entity(project_id=project.id, kind="character", name="старик", uncertain=True)
    session.add(word)
    session.commit()
    word_id, named_id = word.id, people["Ростан"].id
    monkeypatch.setattr(runner, "start", lambda run_id: (_ for _ in ()).throw(AssertionError()))
    data = client.post(
        f"/api/entities/{word_id}/improve", json={"merge_with": named_id, "merge_only": True}
    ).json()
    assert data == {"run": None, "entity_id": named_id}
    session.expire_all()
    assert session.get(Entity, word_id) is None


class NoteReader(FakeModel):
    """Answers the wish check with a given note, or breaks."""

    def __init__(self, note: str | None):
        super().__init__()
        self.note = note

    def invoke_json(self, operation, messages, schema):
        if schema is card_rebuild.WishNote:
            self.calls.append(operation)
            assert "Это Нюточка" in messages[-1].content
            if self.note is None:
                raise analysis.BadModelOutput("broken")
            return card_rebuild.WishNote(note=self.note)
        if schema is card_rebuild.Improvement:
            return card_rebuild.Improvement(present=False)
        return super().invoke_json(operation, messages, schema)


def test_only_what_the_author_says_about_the_card_becomes_a_note(session, project):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]
    model = NoteReader("Ей 1 год.")
    improve(session, rostan, model, wishes="Это Нюточка. Ей 1 год по контексту")
    assert "wish_note" in model.calls
    assert cast(session, project)["Ростан"].author_notes == ["Ей 1 год."]


def test_a_wish_that_is_only_a_command_leaves_no_note(session, project):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]
    improve(session, rostan, NoteReader(""), wishes="Это Нюточка")
    assert cast(session, project)["Ростан"].author_notes == []


def test_a_broken_wish_check_keeps_the_whole_wish(session, project):
    run(session, project, FakeModel())
    rostan = cast(session, project)["Ростан"]
    improve(session, rostan, NoteReader(None), wishes="Это Нюточка. Ей 1 год")
    assert cast(session, project)["Ростан"].author_notes == ["Это Нюточка. Ей 1 год"]


def test_descriptions_keep_the_origin_of_a_card():
    from app.analysis import prompts

    for text in (prompts.general_system("character"), prompts.summary_system("character")):
        assert "origin" in text
