"""Deterministic chapter detection. Tried in order, first plausible result wins:

1. headings  - the file's own heading styles, when they look like real headings
2. pattern   - lines such as "Глава 5", "Chapter IV", "12."
3. titles    - short standalone title lines followed by prose ("Млын", "The Mill")
4. sections  - no chapters found: equal parts by size
"""

import re
from collections import Counter
from dataclasses import dataclass
from statistics import median

from app.importing.extract import Paragraph

_KEYWORD = re.compile(
    r"^(глава|раздзел|частка|часть|книга|том|пролог|эпилог|эпілог|интерлюдия|предисловие|"
    r"послесловие|chapter|part|book|prologue|epilogue|interlude|foreword|afterword)\b.{0,70}$",
    re.IGNORECASE,
)
_ROMAN = re.compile(r"^(?=[IVXLCDM])M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})\.?$")
_NUMBER = re.compile(r"^\d{1,3}\.?$")
_NUMBERED_TITLE = re.compile(r"^\d{1,3}\.\s+[A-ZА-ЯЁІЎ][^.!?]{1,60}$")
_ENDS_SENTENCE = re.compile(r"[.!?…:;,»\"”]$")
_ENDS_PROSE = re.compile(r"[.!?…»\"”]$")

MIN_CHAPTER_CHARS = 300
SECTION_CHARS = 15000


@dataclass
class DetectedChapter:
    title: str
    text: str


def detect_chapters(paragraphs: list[Paragraph]) -> tuple[str, list[DetectedChapter]]:
    texts = [p.text for p in paragraphs]
    for method, finder in (("headings", _styled), ("pattern", _patterned), ("titles", _titled)):
        starts = finder(paragraphs)
        chapters = _build(texts, starts)
        if _plausible(chapters):
            return method, chapters
    return "sections", split_sections(texts)


def _styled(paragraphs: list[Paragraph]) -> list[int]:
    starts = [i for i, p in enumerate(paragraphs) if p.heading and len(p.text) <= 100]
    # Manuscripts often use a heading style for body text; then it carries no signal.
    if len(starts) > len(paragraphs) * 0.2:
        return []
    return starts


def _patterned(paragraphs: list[Paragraph]) -> list[int]:
    families: dict[str, list[int]] = {"keyword": [], "roman": [], "numbered": [], "number": []}
    for i, p in enumerate(paragraphs):
        t = p.text
        if len(t) > 80:
            continue
        if _KEYWORD.match(t) and not _is_sentence(t):
            families["keyword"].append(i)
        elif _ROMAN.match(t):
            families["roman"].append(i)
        elif _NUMBERED_TITLE.match(t):
            families["numbered"].append(i)
        elif _NUMBER.match(t):
            families["number"].append(i)
    # Ties go to the earlier, more explicit family.
    best = max(families.values(), key=len)
    return best if len(best) >= 2 else []


def _is_sentence(text: str) -> bool:
    """ "Книга лежала на столе." starts with a heading word but is prose."""
    return text.endswith((",", ";")) or (
        len(text.split()) > 3 and text.endswith((".", "!", "?", "…"))
    )


def _titled(paragraphs: list[Paragraph]) -> list[int]:
    def title_like(t: str) -> bool:
        return (
            len(t) <= 40
            and len(t.split()) <= 5
            and t[0].isupper()
            and not _ENDS_SENTENCE.search(t)
            and not any(mark in t for mark in "—–:")
        )

    def prose_like(t: str) -> bool:
        return len(t) >= 60 or bool(_ENDS_PROSE.search(t))

    texts = [p.text for p in paragraphs]
    candidates = {i for i, t in enumerate(texts) if title_like(t)}
    # Refrains repeat, chapter titles do not.
    seen = Counter(texts)
    candidates = {i for i in candidates if seen[texts[i]] == 1}
    starts = []
    for i in sorted(candidates):
        # A title sits between prose; a line of verse sits next to other short lines.
        after = i + 1 < len(texts) and prose_like(texts[i + 1])
        before = i == 0 or prose_like(texts[i - 1])
        if after and before:
            starts.append(i)
    return starts


def _build(texts: list[str], starts: list[int]) -> list[DetectedChapter]:
    if len(starts) < 2:
        return []
    chapters: list[DetectedChapter] = []
    preface = "\n\n".join(texts[: starts[0]])
    if preface:
        chapters.append(DetectedChapter("", preface))
    pending_title = ""
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(texts)
        title = f"{pending_title} · {texts[start]}" if pending_title else texts[start]
        body = "\n\n".join(texts[start + 1 : end])
        # "Part One" immediately followed by "Chapter 1": fold the part title into the chapter.
        if not body and n + 1 < len(starts):
            pending_title = title
            continue
        pending_title = ""
        # Too short to be a chapter: most likely a line of verse that looked like a title.
        if len(body) < MIN_CHAPTER_CHARS and chapters and chapters[-1].title:
            chapters[-1].text = "\n\n".join(filter(None, [chapters[-1].text, title, body]))
            continue
        chapters.append(DetectedChapter(title, body))
    return chapters


def _plausible(chapters: list[DetectedChapter]) -> bool:
    titled = [c for c in chapters if c.title]
    if len(titled) < 2:
        return False
    return median(len(c.text) for c in titled) >= MIN_CHAPTER_CHARS


def split_sections(texts: list[str], target: int = SECTION_CHARS) -> list[DetectedChapter]:
    sections: list[list[str]] = [[]]
    size = 0
    for text in texts:
        if size >= target:
            sections.append([])
            size = 0
        sections[-1].append(text)
        size += len(text)
    # A short tail reads better attached to the previous section.
    if len(sections) > 1 and sum(map(len, sections[-1])) < target * 0.3:
        sections[-2].extend(sections.pop())
    return [DetectedChapter("", "\n\n".join(s)) for s in sections if s]
