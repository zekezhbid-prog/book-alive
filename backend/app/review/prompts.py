"""Prompts for the manuscript checks. They answer in the language of the book."""

_FORMAT = """Reply with one JSON object and nothing else:
{"remarks": [{"paragraph": 0, "quote": "", "category": "", "problem": "", "suggestion": ""}]}
- "paragraph": the number in square brackets before the paragraph with the problem.
- "quote": the shortest phrase with the problem, copied from the text character for \
character (at most 150 characters).
- "problem" and "suggestion" are in the language of the text. "suggestion" is the corrected \
wording, or empty when the fix is obvious.
- Report only real problems. If there are none, reply {"remarks": []}. At most 30 remarks."""


def _list(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def grammar(instructions: list[str], categories: list[str]) -> str:
    """The proofreader's prompt, looking only for the ticked items."""
    return (
        """You are a proofreader. You get paragraphs of a book chapter, each marked [n]. Look \
only for these problems:
"""
        + _list(instructions)
        + """
Do not touch style, word choice or the author's deliberate manner of speech: dialect, \
slang and archaic words in dialogue and narration are not mistakes. Report nothing outside \
the list above.
"category" is one of: """
        + ", ".join(categories)
        + ".\n\n"
        + _FORMAT
    )


def editorial(instructions: list[str], categories: list[str]) -> str:
    """The line editor's prompt, looking only for the ticked items."""
    return (
        """You are a publishing-house editor reading a manuscript line by line. You get \
paragraphs of a book chapter, each marked [n]. Mark only these problems:
"""
        + _list(instructions)
        + """
Do not fix plain spelling or punctuation (another pass does that), do not comment on the \
plot, and respect the author's deliberate manner: mark what an editor would really ask to \
change. Report nothing outside the list above.
"category" is one of: """
        + ", ".join(categories)
        + ".\n\n"
        + _FORMAT
    )


_CONTRADICTIONS = """You are a continuity editor. You get cards of characters and locations \
from one book. Each card lists facts about it taken from different chapters, one per line as \
[number] (chapter) fact.
Find facts about the SAME card that cannot both be true. Look for:
{items}
Not contradictions: a change that the chapters explain by events (new clothes, an injury, \
daylight turning to night, a place destroyed). Facts about different cards never conflict.

Reply with one JSON object and nothing else:
{"contradictions": [{"facts": [1, 2], "problem": "", "suggestion": ""}]}
- "facts": the numbers of the conflicting lines, at least two.
- "problem" and "suggestion" are in the language of the facts. "suggestion": which wording \
to harmonise on, or empty.
If there are none, reply {"contradictions": []}."""


def contradictions(instructions: list[str]) -> str:
    return _CONTRADICTIONS.replace("{items}", _list(instructions))


# Bump when NOTES changes: notes of chapters read with an older prompt are read again.
NOTES_VERSION = 1

NOTES = """You are a continuity editor taking notes on one piece of a book chapter. The \
paragraphs are marked [n]. Write down only what a later chapter could contradict:
- "time": how much time has passed (since the last chapter or an event), time of day, \
weekday, season, weather of the season, a date, a duration, an age said or implied \
("ей исполнилось пятнадцать", "через три дня", "наутро", "зима")
- "learn": a character learns, is told or sees a fact, a secret or a name for the first time
- "know": a character shows it knows a fact, a secret or a name, or acts on it
- "death": a character dies, is killed, or leaves the story for good
- "loss": an object is lost, broken, destroyed, given away or taken away
- "object": an important object (a weapon, a ring, a letter, a key) is used, carried or \
handed over
Skip everything else. Do not retell the plot.

Reply with one JSON object and nothing else:
{"notes": [{"paragraph": 0, "quote": "", "type": "", "who": "", "note": ""}]}
- "paragraph": the number in square brackets.
- "quote": the shortest phrase that proves the note, copied from the text character for \
character (at most 150 characters).
- "type": one of time, learn, know, death, loss, object.
- "who": the name of the character (or object) the note is about, as the text names it; \
empty for time notes.
- "note": a short statement in the language of the text ("прошло три дня", "Мирон узнаёт, \
что Ольга — его сестра").
At most 25 notes. If there is nothing to note, reply {"notes": []}."""


_CONTINUITY = """You are a continuity editor. You get notes taken from the chapters of one \
book, in the order of the chapters, one per line as [number] (chapter) type: note. Some \
lines are facts from the cards of the characters.
Find notes that cannot all be true. Look only for:
{items}
Judge by the order of the chapters. A change that the chapters explain by events is not a \
contradiction; a flashback, a dream or a story told by a character can go back in time.

Reply with one JSON object and nothing else:
{"contradictions": [{"check": "", "facts": [1, 2], "problem": "", "suggestion": ""}]}
- "check": which item it is: {ids}.
- "facts": the numbers of the lines that conflict (one line only for knowledge that was \
never learned).
- "problem" and "suggestion" are in the language of the notes. "suggestion": how to make it \
agree, or empty.
Report only real problems. If there are none, reply {"contradictions": []}."""


_NAMES = """You are a continuity editor. You get the cards of one book: the name of each \
character or place and the other names the book uses for it. Find names that are the same \
name spelled in different ways for no reason:
{items}
Compare across cards too: two cards may be one person spelled two ways.

Reply with one JSON object and nothing else:
{"variants": [{"names": ["", ""], "problem": "", "suggestion": ""}]}
- "names": the differing spellings exactly as listed, at least two.
- "problem" and "suggestion" are in the language of the names. "suggestion": which \
spelling to keep.
If there are none, reply {"variants": []}."""


def continuity(instructions: list[str], ids: list[str]) -> str:
    return _CONTINUITY.replace("{items}", _list(instructions)).replace("{ids}", ", ".join(ids))


def name_variants(instruction: str) -> str:
    return _NAMES.replace("{items}", _list([instruction]))
