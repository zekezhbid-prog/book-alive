import pytest
from sqlalchemy.orm import Session

from app.analysis import deep, runner
from app.analysis import entities as analysis
from app.db import get_engine
from app.models import AnalysisRun, Chapter, ChapterExtraction, Entity, Project, text_hash
from tests.test_analysis import FakeModel

CHAPTER_1 = (
    "Рыхташ вошёл в мельницу. На нём был чёрный плащ.\n\n"
    "У старика была длинная седая борода и шрам через левую бровь."
)
CHAPTER_2 = (
    "Дед снял плащ и надел кольчугу.\n\n"
    "Люта стояла у окна в красном платье. «Надзейка, внучка моя», — соврал дед стражнику."
)

MENTIONS = {
    "Мельница": [
        {"name": "Рыхташ", "paragraphs": [0, 1]},
        {"name": "старик", "named": False, "paragraphs": [1, 7]},  # 7 does not exist
    ],
    "Дорога": [
        {"name": "Дед", "named": False, "paragraphs": [0, 1]},
        {"name": "Люта", "paragraphs": [1]},
        {"name": "Надзейка", "paragraphs": [1]},
    ],
}

CAST = {
    "beings": [
        {
            "name": "Рыхташ",
            "sources": [
                {"name": "Рыхташ"},
                {"name": "старик", "chapters": [1]},
                {"name": "Дед", "chapters": [2]},
            ],
        },
        {"name": "Люта", "sources": [{"name": "Люта"}]},
    ],
    "false_names": [{"name": "Надзейка", "belongs_to": "Люта", "reason": "ложь деда"}],
}

CARDS = {
    "Рыхташ": {
        "age": "около 70 (оценка)",
        "facts": [
            {
                "category": "permanent",
                "text": "длинная седая борода",
                "quote": "длинная седая борода",
                "chapter": 1,
            },
            {
                "category": "state",
                "text": "чёрный плащ",
                "quote": "На нём был чёрный плащ",
                "chapter": 1,
            },
            {"category": "permanent", "text": "хромает", "quote": "Он сильно хромал", "chapter": 1},
            {
                "category": "profile",
                "text": "дед Люты",
                "quote": "Надзейка, внучка моя",
                "chapter": 2,
                "doubtful": True,
            },
            {"category": "state", "text": "кольчуга", "quote": "надел кольчугу", "chapter": 1},
        ],
    },
    "Люта": {
        "age": "",
        "facts": [
            {
                "category": "state",
                "text": "красное платье",
                "quote": "в красном платье",
                "chapter": 2,
            }
        ],
    },
}


class DeepModel(FakeModel):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.prompts: list[str] = []

    def invoke_json(self, operation, messages, schema):
        self.calls.append(operation)
        text = messages[-1].content
        self.prompts.append(text)
        if schema is deep.ChapterMentions:
            title = next(t for t in MENTIONS if f'Chapter "{t}"' in text)
            return deep.ChapterMentions.model_validate({"mentions": MENTIONS[title]})
        if schema is deep.Cast:
            return deep.Cast.model_validate(CAST)
        if schema is deep.CardDraft:
            name = text.split("\n")[0].removeprefix("Character: ")
            return deep.CardDraft.model_validate(CARDS[name])
        if schema is deep.Wrong:
            # The cloak is taken off in chapter 2 by the "grandad": say the cloak is wrong.
            numbers = [
                int(line[1 : line.index("]")])
                for line in text.split("\n")
                if line.startswith("[") and "чёрный плащ" in line
            ]
            return deep.Wrong(wrong=numbers)
        self.calls.pop()
        return super().invoke_json(operation, messages, schema)


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
def small_book(monkeypatch):
    monkeypatch.setattr(runner, "RESTART_PAUSE", 0)
    monkeypatch.setattr(deep, "MAIN_MIN_CHAPTERS", 2)  # Рыхташ (2 chapters) is main here


def run_deep(session, project, light, strong):
    record = AnalysisRun(
        project_id=project.id,
        kind="character",
        chapter_ids=[c.id for c in project.chapters],
        mode=deep.MODE_DEEP,
    )
    session.add(record)
    session.commit()
    runner.execute(session, record, light, strong)
    return record


def cast(session, project):
    session.expire_all()
    rows = session.query(Entity).filter_by(project_id=project.id, kind="character").all()
    return {e.name: e for e in rows}


def test_cast_merges_names_and_drops_false_ones(session, project):
    record = run_deep(session, project, DeepModel("light"), DeepModel("strong"))
    assert record.status == "done", record.error
    cards = cast(session, project)
    assert set(cards) == {"Рыхташ", "Люта"}
    # "старик" and "Дед" are words, not names; "Надзейка" is a lie, not Люта's name.
    assert cards["Рыхташ"].aliases == []
    assert cards["Люта"].aliases == []
    assert not cards["Рыхташ"].uncertain


def test_card_keeps_only_quoted_sure_facts_of_this_character(session, project):
    run_deep(session, project, DeepModel("light"), DeepModel("strong"))
    facts = {f.text: f for f in cast(session, project)["Рыхташ"].facts if f.text}
    # Made up quote, doubtful claim, quote from another chapter, and the cloak the check
    # found wrong are all gone.
    assert set(facts) == {"длинная седая борода"}
    assert facts["длинная седая борода"].paragraph == 1


def test_mentions_cover_both_chapters(session, project):
    run_deep(session, project, DeepModel("light"), DeepModel("strong"))
    rykhtash = cast(session, project)["Рыхташ"]
    chapters = {f.chapter_id for f in rykhtash.facts if f.category == analysis.FACT_MENTION}
    assert chapters == {c.id for c in project.chapters}


def test_strong_model_only_for_cast_and_main_cards(session, project):
    light, strong = DeepModel("light"), DeepModel("strong")
    run_deep(session, project, light, strong)
    assert strong.calls.count("cast_characters") == 1
    assert strong.calls.count("card_characters") == 1  # Рыхташ only
    assert light.calls.count("card_characters") == 1  # Люта
    assert light.calls.count("index_characters") == 2
    assert "index_characters" not in strong.calls


def test_no_main_characters_leaves_strong_model_only_the_cast(session, project, monkeypatch):
    monkeypatch.setattr(deep.settings, "deep_main_limit", 0)
    light, strong = DeepModel("light"), DeepModel("strong")
    record = run_deep(session, project, light, strong)
    assert record.status == "done", record.error
    assert strong.calls == ["cast_characters"]
    assert light.calls.count("card_characters") == 2  # Рыхташ and Люта


def test_ages_of_main_characters_reach_the_others(session, project):
    light = DeepModel("light")
    run_deep(session, project, light, DeepModel("strong"))
    luta = next(p for p in light.prompts if p.startswith("Character: Люта"))
    assert "Рыхташ: около 70 (оценка)" in luta


def test_index_is_kept_and_not_read_again(session, project):
    run_deep(session, project, DeepModel("light"), DeepModel("strong"))
    again = DeepModel("light")
    run_deep(session, project, again, DeepModel("strong"))
    assert "index_characters" not in again.calls
    stored = (
        session.query(ChapterExtraction)
        .filter_by(kind=deep.INDEX_KIND, project_id=project.id)
        .all()
    )
    assert len(stored) == 2
    # Paragraph 7 of a two-paragraph chapter was dropped.
    first = next(s for s in stored if s.chapter_id == project.chapters[0].id)
    starik = next(m for m in first.payload["mentions"] if m["name"] == "старик")
    assert starik["paragraphs"] == [1]


def test_from_scratch_reads_the_chapters_again(session, project):
    run_deep(session, project, DeepModel("light"), DeepModel("strong"))
    analysis.start_fresh(session, project.id, project.chapters, "character")
    session.commit()
    again = DeepModel("light")
    run_deep(session, project, again, DeepModel("strong"))
    assert again.calls.count("index_characters") == 2


def test_user_card_with_pictures_or_split_stays(session, project):
    session.add(Entity(project_id=project.id, kind="character", name="Призрак", standalone=True))
    session.commit()
    run_deep(session, project, DeepModel("light"), DeepModel("strong"))
    assert "Призрак" in cast(session, project)


def test_namesakes_split_by_chapters():
    names = deep.gather(
        [
            [deep.Mention(name="Цмок", paragraphs=[0])],
            [deep.Mention(name="Цмок", paragraphs=[2])],
        ]
    )
    plans = deep.plan_cards(
        names,
        deep.Cast(
            beings=[
                deep.Being(name="Цмок", sources=[deep.Source(name="Цмок", chapters=[1])]),
                deep.Being(name="Маленький Цмок", sources=[deep.Source(name="Цмок", chapters=[2])]),
            ]
        ),
    )
    places = {p.name: p.places for p in plans}
    assert places == {"Цмок": {0: {0}}, "Маленький Цмок": {1: {2}}}


def test_dossier_is_in_story_order_with_neighbours():
    chapter = Chapter(position=0, title="Один", text="а\n\nб\n\nв\n\nг", content_hash="x")
    book = deep.Book([chapter])
    plan = deep.Plan("Х", [], {0: {2}}, True)
    assert deep.dossier(book, plan) == "=== Chapter 1 «Один» ===\n[1] б\n\n[2] в\n\n[3] г"
    # Too long with the neighbours: only the paragraph itself.
    assert deep.dossier(book, plan, limit=30) == "=== Chapter 1 «Один» ===\n[2] в"


def plans_of(mentions, cast):
    return {p.name: p for p in deep.plan_cards(deep.gather(mentions), cast)}


def test_word_given_for_the_whole_book_means_the_being_only_where_it_is_named():
    plans = plans_of(
        [
            [
                deep.Mention(name="Уцей", paragraphs=[0]),
                deep.Mention(name="стары", named=False, paragraphs=[1]),
            ],
            [deep.Mention(name="стары", named=False, paragraphs=[3])],
            [deep.Mention(name="стары", named=False, paragraphs=[5, 6])],
        ],
        deep.Cast(
            beings=[
                deep.Being(
                    name="Уцей", sources=[deep.Source(name="Уцей"), deep.Source(name="стары")]
                )
            ]
        ),
    )
    assert plans["Уцей"].places == {0: {0, 1}}
    # Nobody was found for "стары" elsewhere: in chapter 3 he is more than a passing word,
    # so a card in question of that chapter only; in chapter 2 he is mentioned once.
    assert set(plans) == {"Уцей", "стары (гл. 3)"}
    assert plans["стары (гл. 3)"].places == {2: {5, 6}}
    assert not plans["стары (гл. 3)"].named


def test_name_given_in_some_chapters_is_no_card_of_its_own_there():
    plans = plans_of(
        [
            [
                deep.Mention(name="Цмок", paragraphs=[0]),
                deep.Mention(name="Уладар", paragraphs=[1]),
            ],
            [
                deep.Mention(name="Цмок", paragraphs=[2]),
                deep.Mention(name="Уладар", paragraphs=[4]),
            ],
        ],
        deep.Cast(
            beings=[
                deep.Being(
                    name="Цмок",
                    sources=[deep.Source(name="Цмок"), deep.Source(name="Уладар", chapters=[1, 2])],
                )
            ]
        ),
    )
    assert set(plans) == {"Цмок"}


def test_crowds_headings_and_lone_words_get_no_card():
    plans = plans_of(
        [
            [
                deep.Mention(name="людзі", named=False, paragraphs=[0]),
                deep.Mention(name="ПАСЛАНЦЫ", paragraphs=[0]),
                deep.Mention(name="маці", named=False, paragraphs=[1]),
                deep.Mention(name="Аўтар Кнігі", paragraphs=[0]),
            ],
            [deep.Mention(name="людзі", named=False, paragraphs=[2])],
        ],
        deep.Cast(not_characters=["людзі", "Аўтар Кнігі"]),
    )
    assert plans == {}


def test_main_and_other_cards_are_written_side_by_side(session, project, monkeypatch):
    import threading

    seen: set[str] = set()
    light = DeepModel("light")
    original = light.invoke_json

    def spy(operation, messages, schema):
        seen.add(threading.current_thread().name)
        return original(operation, messages, schema)

    monkeypatch.setattr(light, "invoke_json", spy)
    record = run_deep(session, project, light, DeepModel("strong"))
    assert record.status == "done", record.error
    assert any(name.startswith("model") for name in seen)
