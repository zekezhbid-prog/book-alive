"""Prompts for the manuscript checks. They answer in the language of the book."""

_FORMAT = """Reply with one JSON object and nothing else:
{"remarks": [{"paragraph": 0, "quote": "", "category": "", "problem": "", "suggestion": ""}]}
- "paragraph": the number in square brackets before the paragraph with the problem.
- "quote": the shortest phrase with the problem, copied from the text character for \
character (at most 150 characters).
- "problem" and "suggestion" are in the language of the text. "suggestion" is the corrected \
wording, or empty when the fix is obvious.
- Report only real problems. If there are none, reply {"remarks": []}. At most 30 remarks."""

GRAMMAR = (
    """You are a proofreader. You get paragraphs of a book chapter, each marked [n]. Find \
spelling mistakes, grammar mistakes, wrong word forms and agreement, missing or extra \
punctuation, typos and doubled words.
Do not touch style, word choice or the author's deliberate manner of speech: dialect, \
slang and archaic words in dialogue and narration are not mistakes.
"category" is one of: spelling, grammar, punctuation, typo.

"""
    + _FORMAT
)

EDITORIAL = (
    """You are a publishing-house editor reading a manuscript line by line. You get paragraphs \
of a book chapter, each marked [n]. Find what an editor marks by hand: repeated words and \
roots close together, clichés and stock phrases, filler words, overlong or tangled \
sentences, wrong dialogue punctuation, inconsistent spelling of the same name or term, \
tense jumps, unclear pronoun references, tautology, anachronisms.
Do not fix plain spelling (another pass does that) and do not comment on the plot.
"category" is one of: repetition, cliche, long_sentence, dialogue, consistency, tense, \
clarity, other.

"""
    + _FORMAT
)

CONTRADICTIONS = """You are a continuity editor. You get cards of characters and locations \
from one book. Each card lists facts about it taken from different chapters, one per line as \
[number] (chapter) fact.
Find facts about the SAME card that cannot both be true: a different eye or hair colour, \
age, height, species, layout of a place, a scar that appears or disappears, and so on.
Not contradictions: a change that the chapters explain by events (new clothes, an injury, \
daylight turning to night, a place destroyed). Facts about different cards never conflict.

Reply with one JSON object and nothing else:
{"contradictions": [{"facts": [1, 2], "problem": "", "suggestion": ""}]}
- "facts": the numbers of the conflicting lines, at least two.
- "problem" and "suggestion" are in the language of the facts. "suggestion": which wording \
to harmonise on, or empty.
If there are none, reply {"contradictions": []}."""
