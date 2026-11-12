"""What each manuscript check can look for: the ticks in the check dialog.

Every item belongs to one section (`kind`), is either asked of the model (`ai`) or computed
here without a model (`code`), and is either general or written for the rules of one
language. Items of another language are never offered: the rules of Russian punctuation say
nothing about a Belarusian or an English book."""

from dataclasses import dataclass

AI = "ai"
CODE = "code"

LANG_RU = "ru"
LANG_BE = "be"
LANG_EN = "en"
LANG_OTHER = "other"


@dataclass(frozen=True)
class Check:
    id: str
    kind: str  # grammar | editorial | contradictions
    engine: str  # ai | code
    default: bool
    # Languages the item is written for; empty means any language.
    languages: tuple[str, ...] = ()
    # For model items: what to look for, as a line of the prompt, and the category the
    # model puts on such remarks.
    instruction: str = ""
    category: str = ""
    # Contradictions that need the chapters themselves, not only the facts of the cards:
    # every chapter is read once for short notes (time, who learns what, deaths, losses).
    reads_text: bool = False


RU = (LANG_RU,)

CHECKS: tuple[Check, ...] = (
    # ---- Spelling and typesetting ----
    Check("spelling", "grammar", AI, True, instruction="spelling mistakes", category="spelling"),
    Check(
        "grammar",
        "grammar",
        AI,
        True,
        instruction="grammar mistakes: wrong word forms, case, agreement",
        category="grammar",
    ),
    Check(
        "punctuation",
        "grammar",
        AI,
        True,
        instruction="missing or extra punctuation",
        category="punctuation",
    ),
    Check("typo", "grammar", AI, True, instruction="typos and doubled words", category="typo"),
    Check(
        "dialogue_ru",
        "grammar",
        AI,
        True,
        RU,
        instruction=(
            "direct speech set wrongly by the Russian rules: a line of dialogue starts with an "
            "em dash (—), not a hyphen or quotes; the author's words after a line are joined "
            "by a comma or by ?, ! or … and then «—», and start with a small letter; quoted "
            "speech inside narration takes «» quotes and the rules «П, — а.» and «П», — а."
        ),
        category="dialogue",
    ),
    Check("typography_ru", "grammar", CODE, True, RU, category="typography"),
    Check("yo_ru", "grammar", CODE, False, RU, category="yo"),
    # ---- Style ----
    Check(
        "repetition",
        "editorial",
        AI,
        True,
        instruction="the same word or root repeated close together without purpose",
        category="repetition",
    ),
    Check(
        "cliche", "editorial", AI, True, instruction="clichés and stock phrases", category="cliche"
    ),
    Check(
        "filler",
        "editorial",
        AI,
        True,
        instruction="filler words that add nothing, especially when repeated across the page",
        category="filler",
    ),
    Check(
        "long_sentence",
        "editorial",
        AI,
        True,
        instruction="overlong or tangled sentences that are hard to follow",
        category="long_sentence",
    ),
    Check(
        "clarity",
        "editorial",
        AI,
        True,
        instruction="a pronoun whose referent is unclear",
        category="clarity",
    ),
    Check(
        "tense",
        "editorial",
        AI,
        True,
        instruction="unmotivated jumps of verb tense within a passage",
        category="tense",
    ),
    Check(
        "tautology",
        "editorial",
        AI,
        True,
        instruction="tautology and pleonasm: words that repeat each other's meaning",
        category="tautology",
    ),
    Check(
        "names",
        "editorial",
        AI,
        True,
        instruction="the same name or term spelled in different ways",
        category="consistency",
    ),
    Check(
        "officialese_ru",
        "editorial",
        AI,
        True,
        RU,
        instruction=(
            "канцелярит: bureaucratic wording and verbal nouns where a verb is alive "
            "(«произвёл осмотр» instead of «осмотрел», «в связи с», «данный», «является»)"
        ),
        category="officialese",
    ),
    Check(
        "participle_ru",
        "editorial",
        AI,
        True,
        RU,
        instruction=(
            "a dangling adverbial participle (деепричастный оборот) whose action is not done by "
            "the subject of the sentence («Подъезжая к станции, с меня слетела шляпа»)"
        ),
        category="participle",
    ),
    Check(
        "paronyms_ru",
        "editorial",
        AI,
        True,
        RU,
        instruction=(
            "paronyms mixed up: одеть/надеть, представить/предоставить, эффективный/эффектный, "
            "абонент/абонемент and the like"
        ),
        category="paronym",
    ),
    Check(
        "genitive_ru",
        "editorial",
        AI,
        False,
        RU,
        instruction=(
            "chains of three or more nouns in the genitive («решение вопроса укрепления "
            "дисциплины»)"
        ),
        category="genitive",
    ),
    Check(
        "kotory_ru",
        "editorial",
        AI,
        False,
        RU,
        instruction="several «который» clauses in one sentence, or one hanging on another",
        category="kotory",
    ),
    Check(
        "speech_verbs",
        "editorial",
        AI,
        False,
        instruction=(
            "showy dialogue tags piled up (growled, smirked, retorted on every line) where a "
            "plain «said» or no tag would do; a single expressive tag is fine"
        ),
        category="speech_verbs",
    ),
    Check(
        "anachronism",
        "editorial",
        AI,
        False,
        instruction="anachronisms: words, things or notions foreign to the time of the story",
        category="anachronism",
    ),
    Check("rhythm", "editorial", CODE, False, category="rhythm"),
    # ---- Contradictions (whole book: the facts of the cards, notes of the chapters) ----
    Check(
        "looks",
        "contradictions",
        AI,
        True,
        instruction=(
            "a character: different eye or hair colour, age, height, build, species, a scar "
            "that appears or disappears"
        ),
    ),
    Check(
        "places",
        "contradictions",
        AI,
        True,
        instruction="a place or object: different layout, size, colour, material, location",
    ),
    Check(
        "name_variants",
        "contradictions",
        AI,
        True,
        instruction=(
            "one character or place named in spellings that differ for no reason "
            "(Катерина and Екатерина, Хельга and Гельга, Грейвуд and Грэйвуд). A short or "
            "pet form (Аня for Анна, Саша for Александр), a title or a nickname is normal "
            "and is never reported"
        ),
        category="name_variants",
    ),
    Check(
        "timeline",
        "contradictions",
        AI,
        True,
        instruction=(
            "timeline: the time that passed does not add up (two days later it is said a week "
            "has gone), day and night or the season jump with no time passing, a date or a "
            "weekday that cannot be, events happening in an impossible order"
        ),
        category="timeline",
        reads_text=True,
    ),
    Check(
        "age",
        "contradictions",
        AI,
        False,
        instruction=(
            "age through time: a character's age does not match the time that passed (14 at "
            "the start, a year later still 14 or already 17), or a character older or younger "
            "than a relative it must be older or younger than"
        ),
        category="age",
        reads_text=True,
    ),
    Check(
        "knowledge",
        "contradictions",
        AI,
        False,
        instruction=(
            "who knows what: a character knows, names or acts on something before the chapter "
            "where it learns it, or something it was never told and never saw"
        ),
        category="knowledge",
        reads_text=True,
    ),
    Check("missing", "contradictions", CODE, False, category="missing"),
    Check(
        "revived",
        "contradictions",
        AI,
        False,
        instruction=(
            "a character that died (or left for good) acts or speaks again later with no "
            "explanation, or an object that was lost, broken, given away or destroyed is in "
            "someone's hands again. A memory, a dream, a flashback, a ghost, a told story or "
            "an object found or mended again is normal"
        ),
        category="revived",
        reads_text=True,
    ),
)

BY_ID = {c.id: c for c in CHECKS}


def offered(language: str) -> list[Check]:
    """Items that apply to a book in `language`."""
    return [c for c in CHECKS if not c.languages or language in c.languages]


def chosen(kind: str, language: str, ids: list[str] | None) -> list[Check]:
    """The items of one section to run: the ticked ones, or the defaults when nothing was
    sent. Unknown ids and items of another language are ignored."""
    items = [c for c in offered(language) if c.kind == kind]
    if ids is None:
        return [c for c in items if c.default]
    wanted = set(ids)
    return [c for c in items if c.id in wanted]


MIN_LETTERS = 100


def detect_language(text: str) -> str:
    """The language of a book from its letters. Belarusian has і and ў and no и, щ, ъ;
    Russian is the other way round."""
    sample = text[:200_000].lower()
    cyrillic = sum(1 for ch in sample if "а" <= ch <= "я" or ch in "ёіў")
    latin = sum(1 for ch in sample if "a" <= ch <= "z")
    if cyrillic + latin < MIN_LETTERS:
        # A book just begun: nothing to tell by yet, most authors here write in Russian.
        return LANG_RU
    if latin > cyrillic:
        return LANG_EN
    belarusian = sum(sample.count(ch) for ch in "іў")
    russian = sum(sample.count(ch) for ch in "ищъ")
    return LANG_BE if belarusian > russian else LANG_RU
