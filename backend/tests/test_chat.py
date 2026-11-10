import json
import threading
import time

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.api.chat import _model_factory
from app.db import get_engine
from app.llm.calls import BadModelOutput
from app.main import app
from app.models import Chapter, ChatThread, Chunk, Entity, EntityFact, Project, text_hash
from app.rag import agent, chat, jobs
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
    assert len(model.prompts) == agent.MAX_STEPS + 1  # the last step is asked twice
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
    app.dependency_overrides[_model_factory] = lambda: lambda own: holder["model"]
    yield holder
    app.dependency_overrides.pop(_model_factory, None)


def _new_chat(client, project_id: str, **fields) -> str:
    response = client.post(f"/api/projects/{project_id}/chats", json=fields)
    assert response.status_code == 200
    return response.json()["id"]


def _stream(client, project_id: str, question: str) -> list[dict]:
    thread = _new_chat(client, project_id)
    response = client.post(
        f"/api/projects/{project_id}/chats/{thread}/stream", json={"question": question}
    )
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
    # The reader gets a plain message; the details stay in the server log.
    assert (lines[-1]["type"], lines[-1]["detail"]) == ("error", "chat_failed")


def test_chat_stream_without_a_model_fails_before_streaming(client, project):
    thread = _new_chat(client, project.id)
    response = client.post(
        f"/api/projects/{project.id}/chats/{thread}/stream", json={"question": "Кто?"}
    )
    assert (response.status_code, response.json()["detail"]) == (409, "text_model_not_configured")


def test_chat_api_threads(client, project):
    base = f"/api/projects/{project.id}/chats"
    assert client.get(base).json() == []
    road = project.chapters[1].id
    thread = _new_chat(client, project.id, chapter_ids=[road, "nope", road])
    (listed,) = client.get(base).json()
    assert (listed["id"], listed["title"], listed["chapter_ids"]) == (thread, "", [road])
    assert client.get(f"{base}/{thread}/messages").json() == []
    changed = client.patch(f"{base}/{thread}", json={"title": " Про  ключ ", "chapter_ids": []})
    assert (changed.json()["title"], changed.json()["chapter_ids"]) == ("Про ключ", [])
    response = client.post(f"{base}/{thread}/ask", json={"question": "Кто такая Люта?"})
    assert (response.status_code, response.json()["detail"]) == (409, "text_model_not_configured")
    assert client.get(f"/api/projects/{project.id}/chats/missing/messages").status_code == 404
    assert client.delete(f"{base}/{thread}").status_code == 204
    assert client.get(base).json() == []


def test_threads_keep_their_own_history(session, project):
    answer = {"found": True, "answer": "Ключ [1].", "citations": []}
    first = chat.new_thread(project)
    chat.ask(session, project, FakeModel(answer), "Что мельник достал из сундука?", thread=first)
    assert first.title == "Что мельник достал из сундука?"
    second = chat.new_thread(project)
    model = FakeModel(answer)
    chat.ask(session, project, model, "Что несла Люта?", thread=second)
    assert "мельник" not in model.prompts[0]
    assert chat.history(session, second.id)[0].content == "Что несла Люта?"
    # Without a thread the latest one is used.
    assert chat.threads(session, project.id)[0].id == second.id


def test_thread_limited_to_chapters_searches_and_reads_only_them(session, project):
    road = project.chapters[1]
    thread = chat.new_thread(project)
    thread.chapter_ids = [road.id]
    model = FakeModel(
        {"action": "search", "query": "серебряный ключ мельник сундук"},
        {"action": "read", "chapter": 1},
        {"found": False, "answer": "В этих главах нет.", "citations": []},
    )
    chat.ask(session, project, model, "Что мельник достал из сундука?", thread=thread)
    assert "2. Дорога" in model.prompts[0] and "1. Мельница" not in model.prompts[0]
    assert agent.SCOPE_RULE.splitlines()[0] in model.prompts[0]
    assert "(Мельница" not in model.prompts[1]
    assert "read chapter 1: outside this conversation's chapters" in model.prompts[2]
    assert all(
        p.chapter_id == road.id
        for p in search(session, project.id, "мельник сундук ключ", chapter_ids=[road.id])
    )


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
    thread = _new_chat(client, project.id)
    response = client.post(
        f"/api/projects/{project.id}/chats/{thread}/suggest", json={"question": "x"}
    )
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
    roles = [m.role for m in chat.history(session, asked.thread_id)]
    assert roles[-2:] == ["user", "assistant"]


def test_plot_suggestions_hold_no_connection_while_the_model_answers(session, project):
    options = {"options": [{"title": "А", "text": "Б"}]}
    model = ReleasingModel(session, options)
    chat.suggest(session, project, model, "Что дальше?", project.chapters[-1].id)
    assert model.held == [False]


def test_question_in_another_language_is_put_into_the_books_language():
    belarusian = "Уцей мімаволі падаўся бліжэй і раптам зразумеў, што не так з дзяўчынай."
    assert chat.needs_translation("где встретились Уцей и Люта?", belarusian)
    assert not chat.needs_translation("дзе сустрэліся Уцей і Люта?", belarusian)
    assert chat.needs_translation("where did they meet", belarusian)
    assert not chat.needs_translation("Что несла Люта?", "Люта несла корзину. Что это было?")


def test_agent_reads_a_chapter_before_saying_the_book_does_not_answer(session, project):
    model = FakeModel(
        {"found": False, "answer": "В книге этого нет."},
        {"action": "read", "chapter": 1},
        {
            "found": True,
            "answer": "За пазуху [2].",
            "citations": [{"source": 2, "quote": "спрятал его за пазуху"}],
        },
    )
    _, reply = chat.ask(session, project, model, "Куда делся ключ?")
    assert "You have not read any chapter yet" in model.prompts[1]
    assert reply.content == "За пазуху [2]."


def test_agent_out_of_steps_is_asked_once_more_to_answer(session, project):
    looking = {"action": "search", "query": "ключ"}
    replies = [looking] * agent.MAX_STEPS + [
        {"found": True, "answer": "Ключ у мельника [1].", "citations": []}
    ]
    model = FakeModel(*replies)
    _, reply = chat.ask(session, project, model, "Куда делся ключ?")
    assert reply.content == "Ключ у мельника [1]."


def test_one_unreadable_reply_is_tried_again(session, project):
    class OnceBroken(FakeModel):
        broken = True

        def invoke_json(self, operation, messages, schema):
            if self.broken:
                self.broken = False
                raise BadModelOutput("not JSON")
            return super().invoke_json(operation, messages, schema)

    model = OnceBroken({"found": True, "answer": "Посох [1].", "citations": []})
    _, reply = chat.ask(session, project, model, "Что несла Люта?")
    assert reply.content == "Посох [1]."


def test_answer_is_finished_and_saved_when_nobody_waits_for_it(client, session, project):
    """The reader may leave the page while the agent works: the answer still lands in
    the history, and meanwhile the thread shows the question being answered."""
    gate = threading.Event()

    class Slow(FakeModel):
        def invoke_json(self, operation, messages, schema):
            gate.wait(10)
            return super().invoke_json(operation, messages, schema)

    model = Slow({"found": True, "answer": "Посох [1].", "citations": []})
    thread = chat.new_thread(project)
    session.add(thread)
    session.commit()

    def work(own):
        yield from chat.ask_events(
            own,
            own.get(Project, project.id),
            model,
            "Что несла Люта?",
            "",
            own.get(ChatThread, thread.id),
        )

    jobs.start(thread.id, "Что несла Люта?", work)  # nobody reads its events
    base = f"/api/projects/{project.id}/chats/{thread.id}"
    assert client.get(base).json()["pending_question"] == "Что несла Люта?"
    with pytest.raises(jobs.Busy):
        jobs.start(thread.id, "Ещё вопрос", work)
    gate.set()
    deadline = time.monotonic() + 30
    while jobs.running(thread.id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.get(base).json()["pending_question"] == ""
    roles = [m["role"] for m in client.get(f"{base}/messages").json()]
    assert roles == ["user", "assistant"]


def test_agent_looks_at_a_card_to_learn_who_to_look_for(session, project):
    mill = project.chapters[0]
    lyuta = Entity(project_id=project.id, kind="character", name="Люта", aliases=[])
    lyuta.facts.append(
        EntityFact(
            chapter_id=mill.id,
            chapter_hash=mill.content_hash,
            category="profile",
            text="Её служанка — Рымка.",
        )
    )
    session.add(lyuta)
    session.commit()
    model = FakeModel(
        {"action": "card", "name": "Люты"},  # another case ending of the name
        {"action": "card", "name": "Цмок"},
        {"found": True, "answer": "Посох [1].", "citations": []},
    )
    statuses = [
        (e.code, e.detail)
        for e in chat.ask_events(session, project, model, "Кто служанка Люты?")
        if isinstance(e, chat.Status)
    ]
    assert ("card", "Люты") in statuses
    assert "Cards (not sources, do not cite)" in model.prompts[1]
    assert "chapter 1 (Мельница): Её служанка — Рымка." in model.prompts[1]
    assert 'card "Цмок": no such card' in model.prompts[2]


def test_chat_model_falls_back_when_temperature_is_refused(session, project, monkeypatch):
    from app.llm import calls

    built = []

    class Refusing:
        def __init__(self, temperature):
            self.temperature = temperature

        def invoke(self, messages):
            if self.temperature is not None:
                raise ValueError("Unsupported value: 'temperature' does not support 0.0")
            return AIMessage("{}")

    def fake_chat_model(connection, model, **kwargs):
        built.append(kwargs.get("temperature"))
        return Refusing(kwargs.get("temperature"))

    model = object.__new__(calls.TextModel)
    model.session, model.engine, model.project_id = session, session.get_bind(), project.id
    model.connection, model.connection_name, model.model_name = None, "c", "m"
    model.temperature, model.request_overhead = calls.STEADY_TEMPERATURE, 0
    monkeypatch.setattr(calls.registry, "chat_model", fake_chat_model)
    model.llm = model._build()
    assert model.invoke("chat", []) == "{}"
    assert built == [0.0, None] and model.temperature is None


def test_mentions_bring_every_place_a_name_occurs(session, project):
    index_project(session, project)
    from app.rag.index import mentions

    found = mentions(session, project.id, "служанка Люты")  # another case ending
    assert any("Люта шла" in p.text for p in found)
    assert mentions(session, project.id, "служанка") == []  # no name, nothing extra


def test_first_search_includes_the_places_of_the_names(session, project):
    model = FakeModel({"found": True, "answer": "Посох [1].", "citations": []})
    chat.ask(session, project, model, "Чем занят Рыхташ?")
    assert "Рыхташ вошёл в старую мельницу" in model.prompts[0]


def test_names_without_a_card_are_reported(session, project):
    model = FakeModel({"found": True, "answer": "Посох [1].", "citations": []})
    replies = [
        e
        for e in chat.ask_events(session, project, model, "Что несла Люта? Где был Рыхташ?")
        if isinstance(e, chat.Reply)
    ]
    # Both occur in the book once only: too rare to ask for a card search.
    assert replies[0].missing_cards == []
    assert chat._capitalised("Расскажи про Журэю. Где Люта?", True) == ["Журэю", "Люта"]


def test_answer_in_another_language_than_the_question_is_translated(session, project):
    model = FakeModel(
        {"found": True, "answer": "Яна несла посах і хустку [1].", "citations": []},
        {"answer": "Она несла посох и платок [1]."},
    )
    _, reply = chat.ask(session, project, model, "Что Люта несла в руках и на плечах?")
    assert reply.content == "Она несла посох и платок [1]."
    assert not chat.other_language("Что несла Люта?", "Посох «і хустку» [1].")


def _book(session, chapters):
    book = Project(title="Короткие имена", mode="writer")
    for position, text in enumerate(chapters):
        book.chapters.append(
            Chapter(
                position=position,
                title=f"Глава {position + 1}",
                text=text,
                content_hash=text_hash(text),
            )
        )
    session.add(book)
    session.commit()
    index_project(session, book)
    return book


def test_mentions_find_a_three_letter_name_but_not_a_question_word(session):
    from app.rag.index import mentions

    book = _book(
        session,
        [
            "Кто там стоит? Это воевода Зур с дружиной.\n\nКто знает дорогу? Никто.",
            "Князь велел, и воевода Зур собирал охотников в поход.",
        ],
    )
    found = mentions(session, book.id, "Кто такой Зур")
    assert any("Зур собирал" in p.text for p in found)
    assert mentions(session, book.id, "Кто знает") == []  # capitalised only at sentence starts


def test_mentions_reach_every_chapter_of_a_name(session):
    from app.rag.index import MENTION_CHUNKS, mentions

    early = "\n\n".join(f"Лютава ішла па дарозе {n}. " + "Далей лес. " * 30 for n in range(40))
    book = _book(session, [early, "Тут Лютава атрымала даручэнне вызваліць вязняў."])
    found = mentions(session, book.id, "Лютава")
    assert any("даручэнне" in p.text for p in found)
    assert len(found) <= MENTION_CHUNKS


def test_translated_query_is_the_same_on_a_repeat(monkeypatch):
    calls = []

    def once(model, query, sample):
        calls.append(query)
        return f"пераклад {len(calls)}"

    monkeypatch.setattr(chat, "_translate_once", once)
    chat.TRANSLATIONS.clear()
    assert chat._translate(None, "Кто такой Зур?", "кніга") == "пераклад 1"
    assert chat._translate(None, "Кто такой Зур?", "кніга") == "пераклад 1"
    assert len(calls) == 1
