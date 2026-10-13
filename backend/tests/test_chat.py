import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Chapter, Chunk, Project, text_hash
from app.rag import chat
from app.rag.index import index_project, search, split_chunks

MILL = (
    "Рыхташ вошёл в старую мельницу у реки.\n\n"
    "На стене висел ржавый серп, а в углу стоял дубовый сундук.\n\n"
    "Мельник достал из сундука серебряный ключ и спрятал его за пазуху."
)
ROAD = (
    "Люта шла по лесной дороге к замку князя.\n\n"
    "В руках у неё был посох из орешника, на плечах красный платок."
)


class FakeModel:
    def __init__(self, reply: dict):
        self.reply = reply
        self.prompts: list[str] = []

    def invoke_json(self, operation, messages, schema):
        self.prompts.append(messages[0].content)
        return schema.model_validate(self.reply)


@pytest.fixture
def session(client):
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db


@pytest.fixture
def project(session):
    book = Project(title="Тест", mode="writer")
    for position, (title, text) in enumerate([("Мельница", MILL), ("Дорога", ROAD)]):
        book.chapters.append(
            Chapter(position=position, title=title, text=text, content_hash=text_hash(text))
        )
    session.add(book)
    session.commit()
    return book


def test_long_paragraph_is_cut_at_sentence_ends():
    text = "Короткий абзац.\n\n" + "Это длинное предложение в длинном абзаце. " * 30
    pieces = split_chunks(text, limit=200)
    assert all(len(piece) <= 260 for _, piece in pieces)
    assert pieces[0][0] == 0
    assert pieces[0][1].startswith("Короткий абзац.\n\nЭто длинное")
    assert {start for start, _ in pieces[1:]} == {1}  # the rest are parts of paragraph 1
    assert all(piece.endswith(".") for _, piece in pieces)


def test_index_is_incremental(session, project):
    assert index_project(session, project) == 2
    assert index_project(session, project) == 0  # nothing changed: nothing is embedded again

    chapter = project.chapters[1]
    chapter.text = ROAD + "\n\nУ ворот её встретил стражник."
    chapter.content_hash = text_hash(chapter.text)
    session.commit()
    assert index_project(session, project) == 1

    project.chapters.remove(chapter)
    session.commit()
    index_project(session, project)
    assert session.query(Chunk).filter_by(chapter_id=chapter.id).count() == 0


def test_search_finds_the_passage_by_its_words(session, project):
    index_project(session, project)
    passages = search(session, project.id, "Что было в руках у Люты?")
    assert passages[0].chapter_title == "Дорога"
    assert "посох из орешника" in passages[0].text
    assert passages[0].paragraph == 0  # the passage starts at the chapter's first paragraph


def test_answer_keeps_only_citations_that_check_out(session, project):
    model = FakeModel(
        {
            "found": True,
            "answer": "У неё был посох из орешника [1] и меч [9].",
            "citations": [
                {"source": 1, "quote": "посох из орешника"},
                {"source": 9, "quote": "острый меч"},  # there is no passage 9
            ],
        }
    )
    asked, reply = chat.ask(session, project, model, "Что было в руках у Люты?")
    assert asked.role == "user"
    assert "[1] (Дорога)" in model.prompts[0]
    assert [c["n"] for c in reply.citations] == [1]
    only = reply.citations[0]
    assert (only["chapter_title"], only["paragraph"], only["quote"]) == (
        "Дорога",
        1,
        "посох из орешника",
    )


def test_invented_quote_is_not_shown_as_a_source(session, project):
    model = FakeModel(
        {
            "found": True,
            "answer": "Она несла посох [1].",
            "citations": [{"source": 1, "quote": "она несла волшебный жезл"}],
        }
    )
    _, reply = chat.ask(session, project, model, "Что несла Люта по дороге?")
    assert reply.citations[0]["quote"] == ""
    assert reply.citations[0]["paragraph"] == 0  # still links to where the passage starts


def test_not_found_answer_has_no_citations(session, project):
    model = FakeModel({"found": False, "answer": "В найденном тексте этого нет.", "citations": []})
    _, reply = chat.ask(session, project, model, "Как звали коня князя?")
    assert reply.citations == []
    assert reply.content == "В найденном тексте этого нет."


def test_follow_up_question_is_searched_with_the_previous_one(session, project):
    answer = {"found": True, "answer": "Ключ [1].", "citations": []}
    chat.ask(session, project, FakeModel(answer), "Что мельник достал из сундука?")
    model = FakeModel(answer)
    chat.ask(session, project, model, "А куда он это спрятал?")
    # The follow-up alone shares no words with the mill chapter; the previous question does.
    assert "(Мельница)" in model.prompts[0]


def test_chat_api_history_and_clear(client, project):
    assert client.get(f"/api/projects/{project.id}/chat").json() == []
    response = client.post(f"/api/projects/{project.id}/chat", json={"question": "Кто такая Люта?"})
    assert (response.status_code, response.json()["detail"]) == (409, "text_model_not_configured")
    assert client.delete(f"/api/projects/{project.id}/chat").status_code == 204


def test_plot_suggestions_for_the_writer(session, project):
    options = {
        "options": [
            {"title": "Погоня", "text": "Стражник узнаёт Люту."},
            {"title": "Обман", "text": "Она выдаёт себя за служанку."},
            {"title": "Ночь", "text": "Люта ждёт темноты у стены."},
        ]
    }
    model = FakeModel(options)
    road = project.chapters[1]
    asked, reply = chat.suggest(session, project, model, "Предложи развитие событий", road.id)
    assert asked.content == "Предложи развитие событий"
    assert reply.content.startswith("1. Погоня\nСтражник узнаёт Люту.\n\n2. Обман")
    assert reply.citations == []
    # The prompt carries the end of the open chapter and passages from elsewhere in the book.
    assert "посох из орешника" in model.prompts[0]
    assert "(Мельница)" in model.prompts[0]


def test_suggestions_are_for_writer_projects_only(client, session, project):
    project.mode = "reader"
    session.commit()
    response = client.post(f"/api/projects/{project.id}/chat/suggest", json={"question": "x"})
    assert (response.status_code, response.json()["detail"]) == (409, "reader_mode_readonly")
