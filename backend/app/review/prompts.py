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
