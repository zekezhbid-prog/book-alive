import json

import pytest
from sqlalchemy.orm import Session

from app.api.chat import _text_model
from app.db import get_engine
from app.llm.calls import BadModelOutput
from app.main import app
from app.models import Chapter, Chunk, Project, text_hash
from app.rag import agent, chat
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
    """Replies in turn; the last one repeats. Records each prompt as one text."""

    def __init__(self, *replies: dict):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def invoke_json(self, operation, messages, schema):
        self.prompts.append("\n\n".join(str(m.content) for m in messages))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return schema.model_validate(reply)


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
    assert "[1] (Дорога, passage)" in model.prompts[0]
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
    # The earlier exchange is in the prompt too, before the new question.
    assert "Что мельник достал из сундука?" in model.prompts[0]
    # The follow-up alone shares no words with the mill chapter; the previous question does.
    assert "(Мельница, passage)" in model.prompts[0]


def test_agent_searches_and_reads_a_whole_chapter(session, project):
    model = FakeModel(
        {"action": "search", "query": "серебряный ключ"},
        {"action": "read", "chapter": 1},
        {
            "found": True,
            "answer": "Мельник спрятал ключ за пазуху [3].",
            "citations": [{"source": 3, "quote": "спрятал его за пазуху"}],
        },
    )
    statuses = []
    for event in chat.ask_events(session, project, model, "Куда делся ключ?"):
        if isinstance(event, chat.Status):
            statuses.append((event.code, event.detail))
        else:
            reply = event.reply
    assert [code for code, _ in statuses] == [
        "index",
        "search",
        "think",
        "search",
        "think",
        "read",
        "think",
    ]
    assert ("read", "Мельница") in statuses
    # The table of contents is in every prompt; the whole chapter reaches the last one.
    assert "1. Мельница" in model.prompts[0]
    assert "whole chapter" in model.prompts[2]
    assert MILL in model.prompts[2]
    (only,) = reply.citations
    assert (only["n"], only["chapter_title"], only["paragraph"]) == (3, "Мельница", 2)


def test_agent_must_answer_within_its_steps(session, project):
    model = FakeModel({"action": "search", "query": "ключ"})
    with pytest.raises(BadModelOutput):
        chat.ask(session, project, model, "Куда делся ключ?")
    assert len(model.prompts) == agent.MAX_STEPS
    assert agent.FORCE_ANSWER in model.prompts[-1]


def test_reading_a_missing_chapter_is_reported_to_the_agent(session, project):
    model = FakeModel(
        {"action": "read", "chapter": 7},
        {"found": False, "answer": "В книге нет седьмой главы.", "citations": []},
    )
    chat.ask(session, project, model, "Что в седьмой главе?")
    assert "read chapter 7: there is no such chapter" in model.prompts[1]


@pytest.fixture
def stream_model():
    """Puts a fake model behind `/chat/stream`; the test sets its replies."""
    holder: dict = {}
    app.dependency_overrides[_text_model] = lambda: holder["model"]
    yield holder
    app.dependency_overrides.pop(_text_model, None)


def _stream(client, project_id: str, question: str) -> list[dict]:
    response = client.post(f"/api/projects/{project_id}/chat/stream", json={"question": question})
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines()]


def test_chat_stream_reports_steps_then_messages(client, project, stream_model):
    stream_model["model"] = FakeModel({"found": True, "answer": "Посох [1].", "citations": []})
    lines = _stream(client, project.id, "Что несла Люта?")
    assert [(line["type"], line["code"]) for line in lines[:3]] == [
        ("status", "index"),
        ("status", "search"),
        ("status", "think"),
    ]
    assert lines[-1]["type"] == "done"
    assert [m["role"] for m in lines[-1]["messages"]] == ["user", "assistant"]


def test_chat_stream_reports_a_model_failure_as_its_last_line(client, project, stream_model):
    class BrokenModel:
        def invoke_json(self, operation, messages, schema):
            raise RuntimeError("rate limit")

    stream_model["model"] = BrokenModel()
    lines = _stream(client, project.id, "Что несла Люта?")
    assert lines[0]["type"] == "status"  # the response had already begun
    assert (lines[-1]["type"], lines[-1]["detail"]) == ("error", "provider_error: rate limit")


def test_chat_stream_without_a_model_fails_before_streaming(client, project):
    response = client.post(f"/api/projects/{project.id}/chat/stream", json={"question": "Кто?"})
    assert (response.status_code, response.json()["detail"]) == (409, "text_model_not_configured")


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


class ReleasingModel(FakeModel):
    """Like `TextModel`: gives the connection back before the model answers, and records
    whether it could."""

    def __init__(self, session, *replies: dict):
        super().__init__(*replies)
        self.session = session
        self.held: list[bool] = []

    def invoke_json(self, operation, messages, schema):
        from app.db import release_connection

        release_connection(self.session)
        self.held.append(self.session.in_transaction())
        return super().invoke_json(operation, messages, schema)


def test_chat_holds_no_connection_while_the_model_answers(session, project):
    answer = {"found": True, "answer": "Посох [1].", "citations": []}
    model = ReleasingModel(session, answer)
    asked, reply = chat.ask(session, project, model, "Что было в руках у Люты?")
    assert model.held and not any(model.held)
    assert asked.created_at <= reply.created_at
    roles = [m.role for m in chat.history(session, project.id)]
    assert roles[-2:] == ["user", "assistant"]


def test_plot_suggestions_hold_no_connection_while_the_model_answers(session, project):
    options = {"options": [{"title": "А", "text": "Б"}]}
    model = ReleasingModel(session, options)
    chat.suggest(session, project, model, "Что дальше?", project.chapters[-1].id)
    assert model.held == [False]
