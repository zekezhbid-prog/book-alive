import io
import zipfile

import pytest

from app.importing.chapters import detect_chapters, split_sections
from app.importing.extract import Paragraph, UnsupportedBook, extract

PROSE = "Он шёл по дороге и думал о том, что ждёт его впереди. " * 8


def paragraphs(*texts: str) -> list[Paragraph]:
    return [Paragraph(t) for t in texts]


def test_keyword_headings():
    method, chapters = detect_chapters(
        paragraphs("Глава 1", PROSE, PROSE, "Глава 2", PROSE, "Глава 3", PROSE)
    )
    assert method == "pattern"
    assert [c.title for c in chapters] == ["Глава 1", "Глава 2", "Глава 3"]
    assert chapters[0].text == f"{PROSE}\n\n{PROSE}"


def test_part_title_is_folded_into_first_chapter():
    _, chapters = detect_chapters(paragraphs("Часть первая", "Глава 1", PROSE, "Глава 2", PROSE))
    assert [c.title for c in chapters] == ["Часть первая · Глава 1", "Глава 2"]


def test_text_before_first_chapter_becomes_untitled_chapter():
    _, chapters = detect_chapters(
        paragraphs("Посвящается маме.", "Глава 1", PROSE, "Глава 2", PROSE)
    )
    assert chapters[0].title == ""
    assert chapters[0].text == "Посвящается маме."


def test_short_title_lines_without_keywords():
    method, chapters = detect_chapters(paragraphs("Млын", PROSE, "Каваль", PROSE, "Палац", PROSE))
    assert method == "titles"
    assert [c.title for c in chapters] == ["Млын", "Каваль", "Палац"]


def test_verse_lines_are_not_titles():
    _, chapters = detect_chapters(
        paragraphs(
            "Млын", PROSE,
            "Люлі-люлі", "Спі, маё дзіця", "Люлі-люлі", PROSE,
            "Каваль", PROSE,
        )
    )  # fmt: skip
    assert [c.title for c in chapters] == ["Млын", "Каваль"]
    assert "Спі, маё дзіця" in chapters[0].text


def test_heading_style_used_for_body_text_is_ignored():
    # Every paragraph is styled as a heading, as in some manuscripts.
    book = [Paragraph(t, heading=True) for t in ("Млын", PROSE, "Каваль", PROSE, "Палац", PROSE)]
    method, chapters = detect_chapters(book)
    assert method == "titles"
    assert len(chapters) == 3


def test_real_heading_styles_win():
    book = [
        Paragraph("Встреча у реки, или Как всё началось", heading=True),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph("Дорога домой, или Чем всё закончилось", heading=True),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph(PROSE),
        Paragraph(PROSE),
    ]
    method, chapters = detect_chapters(book)
    assert method == "headings"
    assert len(chapters) == 2


def test_no_chapters_falls_back_to_sections():
    method, chapters = detect_chapters(paragraphs(*[PROSE] * 100))
    assert method == "sections"
    assert len(chapters) > 1
    assert all(c.title == "" for c in chapters)


def test_sections_attach_short_tail():
    sections = split_sections(["a" * 1000] * 11, target=5000)
    assert [len(s.text.replace("\n\n", "")) for s in sections] == [5000, 6000]


def test_plain_text_one_paragraph_per_line():
    book = extract("Первый абзац.\nВторой абзац.\nТретий абзац.\nЧетвёртый.".encode(), "book.txt")
    assert [p.text for p in book.paragraphs] == [
        "Первый абзац.", "Второй абзац.", "Третий абзац.", "Четвёртый."
    ]  # fmt: skip


def test_cp1251_text_is_decoded():
    book = extract("Привет, мир.\n\nВторая строка.".encode("cp1251"), "book.txt")
    assert book.paragraphs[0].text == "Привет, мир."


def test_fb2():
    fb2 = """<?xml version="1.0" encoding="utf-8"?>
    <FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
      <description><title-info>
        <author><first-name>Николай</first-name><last-name>Гоголь</last-name></author>
        <book-title>Вий</book-title>
      </title-info></description>
      <body>
        <section><title><p>Глава 1</p><p>Бурса</p></title><p>Первый абзац.</p></section>
        <section><title><p>Глава 2</p></title><p>Второй абзац.</p></section>
      </body>
    </FictionBook>""".encode()
    book = extract(fb2, "viy.fb2")
    assert (book.title, book.author) == ("Вий", "Николай Гоголь")
    assert [(p.text, p.heading) for p in book.paragraphs] == [
        ("Глава 1. Бурса", True),
        ("Первый абзац.", False),
        ("Глава 2", True),
        ("Второй абзац.", False),
    ]


def test_docx():
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = f"""<w:document xmlns:w="{w}"><w:body>
      <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Глава 1</w:t></w:r></w:p>
      <w:p><w:r><w:t>Первая </w:t></w:r><w:r><w:t>строка.</w:t></w:r></w:p>
      <w:p></w:p>
    </w:body></w:document>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    book = extract(buffer.getvalue(), "book.docx")
    assert [(p.text, p.heading) for p in book.paragraphs] == [
        ("Глава 1", True),
        ("Первая строка.", False),
    ]


def test_sentence_starting_with_a_heading_word_is_not_a_heading():
    book = ["1. Начало", PROSE, "Книга лежала на столе.", PROSE, "2. Дорога", PROSE]
    book += ["Часть пути они прошли молча.", PROSE, "3. Конец", PROSE]
    method, chapters = detect_chapters(paragraphs(*book))
    assert method == "pattern"
    assert [c.title for c in chapters] == ["1. Начало", "2. Дорога", "3. Конец"]


@pytest.mark.parametrize("name", ["book.epub", "book.docx", "book.pdf", "book.fb2"])
def test_damaged_files_are_reported_as_unsupported(name):
    data = b"PK\x03\x04 not really a zip" if name.endswith(("epub", "docx")) else b"%PDF-1.4 broken"
    if name.endswith("fb2"):
        data = b""
    with pytest.raises(UnsupportedBook):
        extract(data, name)


def test_epub_with_url_encoded_file_names():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/book.opf",
            """<package xmlns="http://www.idpf.org/2007/opf"
                 xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata><dc:title>Вий</dc:title><dc:creator>Гоголь</dc:creator></metadata>
              <manifest><item id="c1" href="Text/Chapter%201.xhtml"/></manifest>
              <spine><itemref idref="c1"/></spine>
            </package>""",
        )
        archive.writestr(
            "OPS/Text/Chapter 1.xhtml",
            "<html><body><h1>Глава 1</h1><div><p>Первый абзац.</p></div></body></html>",
        )
    book = extract(buffer.getvalue(), "viy.epub")
    assert (book.title, book.author) == ("Вий", "Гоголь")
    assert [(p.text, p.heading) for p in book.paragraphs] == [
        ("Глава 1", True),
        ("Первый абзац.", False),
    ]
