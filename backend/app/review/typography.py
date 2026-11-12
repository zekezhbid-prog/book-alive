"""Checks computed without a model: Russian typesetting, the letter ё, monotonous openings.

They are instant and free, and the typesetting ones can also be fixed in one go: the rules
are mechanical, unlike anything about words or style."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.review.checks import LANG_BE, LANG_EN


@dataclass
class Finding:
    paragraph: int
    quote: str
    problem: str
    suggestion: str = ""


def _quotes(text: str) -> str:
    """Straight double quotes to «ёлочки»: opening after a space, a bracket or a dash."""
    out: list[str] = []
    for index, ch in enumerate(text):
        if ch != '"':
            out.append(ch)
            continue
        before = text[index - 1] if index else " "
        out.append("«" if before.isspace() or before in "([—–-«/" else "»")
    return "".join(out)


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    fix: Callable[[str], str]
    problem: str


def _sub(pattern: str, repl: str) -> tuple[re.Pattern[str], Callable[[str], str]]:
    compiled = re.compile(pattern, re.MULTILINE)
    return compiled, lambda text: compiled.sub(repl, text)


TYPOGRAPHY_RU: tuple[Rule, ...] = (
    Rule(re.compile('"'), _quotes, "Прямые кавычки вместо «ёлочек»"),
    Rule(*_sub(r"^[-–] ", "— "), "Реплика начинается с дефиса, нужно тире «—»"),
    Rule(*_sub(r"(?<=\S) (?:[-–]|--) (?=\S)", " — "), "Дефис вместо тире «—»"),
    Rule(*_sub(r"(?<!\.)\.{3}(?!\.)", "…"), "Три точки вместо многоточия «…»"),
    Rule(*_sub(r"(?<=\S) {2,}(?=\S)", " "), "Лишние пробелы"),
    Rule(*_sub(r"(?<=[^\s—]) +(?=[,.;:!?»)])", ""), "Пробел перед знаком препинания"),
    Rule(*_sub(r"(?<=[«(]) +", ""), "Пробел после открывающей кавычки или скобки"),
)


def _window(text: str, start: int, end: int, margin: int = 20) -> str:
    """The match with a few words around it, cut on spaces."""
    left = max(0, start - margin)
    if left:
        space = text.find(" ", left, start)
        left = space + 1 if space != -1 else left
    right = min(len(text), end + margin)
    if right < len(text):
        space = text.rfind(" ", end, right)
        right = space if space != -1 else right
    return text[left:right]


def typography_findings(paragraphs: list[str]) -> list[Finding]:
    found: list[Finding] = []
    for index, paragraph in enumerate(paragraphs):
        for rule in TYPOGRAPHY_RU:
            matches = list(rule.pattern.finditer(paragraph))
            if not matches:
                continue
            first = matches[0]
            quote = _window(paragraph, first.start(), first.end())
            problem = rule.problem
            if len(matches) > 1:
                problem += f" (в абзаце: {len(matches)})"
            found.append(Finding(index, quote, problem, rule.fix(quote)))
    return found


def fix_typography(text: str) -> str:
    """The text with every typesetting rule applied, paragraph by paragraph."""
    paragraphs = text.split("\n\n")
    for rule in TYPOGRAPHY_RU:
        paragraphs = [rule.fix(p) for p in paragraphs]
    return "\n\n".join(paragraphs)


# ---------- ё ----------

_WORD = re.compile(r"[а-яёА-ЯЁ]+")
# Pairs where the е spelling is a different word in its own right: never flagged.
_AMBIGUOUS = {
    "все",
    "небо",
    "осел",
    "мел",
    "лен",
    "падеж",
    "берет",
    "узнает",
    "совершенный",
    "совершенно",
    "надал",
    "передохнет",
    "истекший",
    "нем",
    "чем",
    "ведро",
    "слезы",
    "сел",
    "пел",
    "вел",
}


def yo_words(texts: list[str]) -> dict[str, str]:
    """Words the book writes with ё somewhere: their е spelling mapped to the ё one."""
    words: dict[str, str] = {}
    for text in texts:
        for match in _WORD.finditer(text):
            word = match.group().lower()
            if "ё" in word:
                plain = word.replace("ё", "е")
                if plain not in _AMBIGUOUS:
                    words.setdefault(plain, word)
    return words


def yo_findings(paragraphs: list[str], known: dict[str, str]) -> list[tuple[str, list[Finding]]]:
    """Words written with е here and with ё elsewhere in the book, each with its places."""
    places: dict[str, list[Finding]] = {}
    for index, paragraph in enumerate(paragraphs):
        for match in _WORD.finditer(paragraph):
            word = match.group()
            target = known.get(word.lower())
            if target is None or "ё" in word.lower():
                continue
            problem = f"В книге есть «{target}» через ё, а здесь «{word.lower()}» через е"
            places.setdefault(target, []).append(Finding(index, word, problem, target))
    return list(places.items())


# ---------- monotonous openings ----------

_SENTENCE = re.compile(r"[^.!?…]+[.!?…]*")
_FIRST_WORD = re.compile(r"\w+", re.UNICODE)
RUN = 3

_RHYTHM_PROBLEM = {
    LANG_EN: "{n} sentences in a row start with «{word}»",
    LANG_BE: "Запар сказаў, якія пачынаюцца з «{word}»: {n}",
}
_RHYTHM_DEFAULT = "Подряд предложений, которые начинаются с «{word}»: {n}"


def rhythm_findings(paragraphs: list[str], language: str) -> list[Finding]:
    """Three or more sentences in a row that open with the same word."""
    template = _RHYTHM_PROBLEM.get(language, _RHYTHM_DEFAULT)
    found: list[Finding] = []
    run: list[tuple[int, str]] = []  # (paragraph, sentence) of the current run
    current = ""

    def close() -> None:
        if len(run) >= RUN:
            paragraph, sentence = run[0]
            found.append(
                Finding(
                    paragraph, sentence.strip()[:120], template.format(n=len(run), word=current)
                )
            )

    for index, paragraph in enumerate(paragraphs):
        for match in _SENTENCE.finditer(paragraph):
            sentence = match.group()
            first = _FIRST_WORD.search(sentence)
            if first is None:
                continue
            word = first.group().lower()
            if word == current:
                run.append((index, sentence))
            else:
                close()
                current, run = word, [(index, sentence)]
    close()
    return found
