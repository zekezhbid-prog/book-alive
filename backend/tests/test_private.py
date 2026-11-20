from app.importing.chapters import DetectedChapter
from app.importing.private import PRIVATE_TITLE, personal_block, split_off_personal

# Made-up data shaped like a manuscript's title page.
TITLE_PAGE = [
    "Аўтар: Пятрова Ганна Іванаўна",
    "01.02.1990 г. нар.",
    "Тэл.: +375-29-123-45-67 (Viber, Telegram)",
    "Адрас: 220000, Мінская вобл., г. Мінск, вул. Лесная, д. 5",
    "Пашпарт выдадзены 03.04.2015 Цэнтральным РУУС г. Мінска",
    "Асабісты нумар: 1234567A001PB1",
]
STORY = [
    "Цуд",
    "Ніхто не бачыў, як гэта здарылася.",
    "Была ноч, і на скрыжаванні нікога не было.",
]


def test_title_page_with_personal_data_is_found():
    assert personal_block(TITLE_PAGE + STORY) == len(TITLE_PAGE)


def test_e_mail_and_passport_number_count_too():
    assert personal_block(["Іван Пятроў", "ivan@example.com", "Паспорт MP1234567", *STORY]) == 3


def test_a_story_with_a_date_or_a_number_is_no_title_page():
    assert personal_block(["Глава 1", "Было это 12.05.1812 года.", *STORY]) == 0
    assert personal_block(["Дом стоял на улице Лесной, д. 5.", *STORY]) == 0
    assert personal_block(STORY) == 0


def test_personal_data_far_into_the_book_is_not_a_title_page():
    filler = [f"Абзац {i}." for i in range(30)]
    assert personal_block(filler + TITLE_PAGE) == 0


def test_the_block_becomes_a_private_chapter_and_the_story_stays():
    chapters = [
        DetectedChapter("", "\n\n".join(TITLE_PAGE + STORY)),
        DetectedChapter("Другая", "Текст."),
    ]
    out = split_off_personal(chapters)
    assert [(c.title, c.private) for c in out] == [
        (PRIVATE_TITLE, True),
        ("", False),
        ("Другая", False),
    ]
    assert out[0].text == "\n\n".join(TITLE_PAGE)
    assert out[1].text == "\n\n".join(STORY)


def test_a_chapter_that_is_only_personal_data_is_marked_private():
    out = split_off_personal([DetectedChapter("Титул", "\n\n".join(TITLE_PAGE))])
    assert [(c.title, c.private) for c in out] == [("Титул", True)]


def test_a_book_without_personal_data_is_untouched():
    chapters = [DetectedChapter("Один", "\n\n".join(STORY))]
    assert split_off_personal(chapters) == chapters


def test_a_request_with_private_text_is_not_sent():
    import pytest
    from langchain_core.messages import HumanMessage

    from app.llm.calls import PrivateTextBlocked, TextModel, _squash

    model = TextModel.__new__(TextModel)
    model.private = [_squash(TITLE_PAGE[2])]
    model._refuse_private("x", [HumanMessage("Глава:\n\n" + "\n\n".join(STORY))])
    with pytest.raises(PrivateTextBlocked):
        model._refuse_private("x", [HumanMessage("Текст:  " + TITLE_PAGE[2].upper())])


def test_import_closes_the_title_page_to_ai_and_the_switch_works(client):
    from tests.conftest import make_book

    data = ("\n\n".join(TITLE_PAGE) + "\n\n").encode("utf-8") + make_book(2)
    project = client.post(
        "/api/projects",
        data={"mode": "reader"},
        files={"file": ("Рукапіс.txt", data, "text/plain")},
    ).json()
    chapters = project["chapters"]
    assert [(c["title"], c["private"]) for c in chapters] == [
        (PRIVATE_TITLE, True),
        ("Глава 1", False),
        ("Глава 2", False),
    ]
    first = chapters[0]["id"]
    assert client.post(f"/api/chapters/{first}/scenes/split").status_code in (403, 409, 422)
    opened = client.patch(f"/api/chapters/{first}", json={"private": False}).json()
    assert opened["private"] is False
