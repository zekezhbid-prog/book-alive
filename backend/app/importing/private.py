"""The author's personal data at the start of a manuscript (a title page with a phone, an
address, a passport or ID number) never goes to a model.

Manuscripts sent to publishers often open with such a page, and the chapter split may glue it
to the beginning of the story. On import the block becomes a chapter of its own marked
`private`; every AI feature skips private chapters and `TextModel` refuses any request that
carries their text.
"""

import re
from dataclasses import replace

from app.importing.chapters import DetectedChapter

PRIVATE_TITLE = "Личные данные автора"
# The block must start the book: only the first paragraphs are looked at.
WINDOW = 12
# A title page is short lines; a paragraph of prose ends the block.
LINE_CHARS = 250

_DIGITS = re.compile(r"\d")
_SIGNALS = {
    # Strong: never in a story by chance.
    "phone": re.compile(r"(?<![\w.])\+?\d[\d\s()\-]{7,}\d(?![\w.])"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "id": re.compile(r"\b\d{7}[A-ZА-Я]\d{3}[A-ZА-Я]{2}\d\b"),
    "passport": re.compile(r"\b(паспорт|пашпарт|passport)|\b[A-ZА-Я]{2}\s?\d{7}\b", re.IGNORECASE),
    # Weak: may be in a story, count only next to a strong one.
    "date": re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"),
    "birth": re.compile(r"\bнар\.|нарадж|рожд|\bborn\b|date of birth", re.IGNORECASE),
    "address": re.compile(
        r"\b\d{6},|\b(вул|ул|пр-т|просп|кв|адрас|адрес|address)\b\.?", re.IGNORECASE
    ),
}
_STRONG = {"phone", "email", "id", "passport"}


def _signals(paragraph: str) -> set[str]:
    found = set()
    for kind, pattern in _SIGNALS.items():
        for match in pattern.finditer(paragraph):
            if kind == "phone" and len(_DIGITS.findall(match.group())) < 9:
                continue
            found.add(kind)
            break
    return found


def personal_block(paragraphs: list[str]) -> int:
    """How many first paragraphs are the author's personal data; 0 when there are none.
    It takes two lines with signs of it, at least one sign that never turns up in a story
    by chance (a phone, an e-mail, an ID or passport number) and another kind of sign."""
    last, lines, kinds = -1, 0, set()
    for index, paragraph in enumerate(paragraphs[:WINDOW]):
        if len(paragraph) > LINE_CHARS:
            break
        found = _signals(paragraph)
        if found:
            last, lines, kinds = index, lines + 1, kinds | found
    if lines >= 2 and kinds & _STRONG and len(kinds) >= 2:
        return last + 1
    return 0


def split_off_personal(chapters: list[DetectedChapter]) -> list[DetectedChapter]:
    """The personal block at the start of the first chapter as a private chapter of its own."""
    if not chapters:
        return chapters
    first = chapters[0]
    paragraphs = first.text.split("\n\n")
    count = personal_block(paragraphs)
    if not count:
        return chapters
    if count == len(paragraphs):
        return [replace(first, private=True, title=first.title or PRIVATE_TITLE), *chapters[1:]]
    block = DetectedChapter(PRIVATE_TITLE, "\n\n".join(paragraphs[:count]), private=True)
    rest = replace(first, text="\n\n".join(paragraphs[count:]))
    return [block, rest, *chapters[1:]]
