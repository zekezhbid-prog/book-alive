"""Prompt templates for finding characters and locations."""

from app.models import KIND_CHARACTER

# Bump when EXTRACT_SYSTEM changes: stored chapter answers from older prompts are re-read.
PROMPT_VERSION = 7

_SUBJECT = {
    "character": {
        "what": "characters: living, animate beings only (people, animals, spirits, gods, \
monsters, any creature that thinks, speaks or acts on its own will). Never list objects, \
weapons, buildings, places, plants, weather, natural phenomena, illnesses or abstract \
things, however vividly the text describes them; a thing becomes a character only when \
the story makes it alive (it speaks or acts by itself)",
        "permanent": "age, face, build, height, hair, eyes, skin, scars, species, voice, "
        "lasting traits of personality",
        "state": "clothes, hairstyle, injuries, dirt or blood, weapons and objects they "
        "carry, a visible change of form or condition",
        "profile": "lasting traits of behaviour and character that show again and again "
        "(habits, manner of speech and acting, what they love or fear), their role and "
        "occupation",
    },
    "location": {
        "what": "locations and objects: places where the action happens or that are \
described, and notable inanimate things (weapons, artifacts, vehicles, buildings, \
landmarks such as a bridge or a mill, important items a character owns or uses). Skip \
living beings: they are characters. Skip ordinary everyday things that play no part",
        "permanent": "what kind of place or thing it is, architecture, layout, shape, "
        "materials, size, ornament, surroundings, landmarks",
        "state": "time of day, weather, season, light, damage, wear, crowds or emptiness, "
        "sounds and smells, who holds or uses it now",
        "profile": "what the place or thing is for, who lives or works there or owns it, "
        "what happens there or with it, its history and role in the story",
    },
}

EXTRACT_SYSTEM = """You read one chapter of a book and list the entries of one kind in it, \
with what the text says about how they look. The result feeds illustration and video \
prompts, so visual detail matters most.

What to list: {what}.

Rules:
- Use only what this chapter states. Never invent details and never guess beyond the text.
- "name": the fullest proper name the book uses. "aliases": other proper names and \
nicknames of the same one, only when the text makes plain that it is the same one. Never put \
there the name of another entry, a friend, relative or companion. Never put common words \
there (girl, old man, guest, the smith): many others can be called that.
- "named": true when the text gives a proper name; false when it only calls them by a \
common word (the old man, a girl, the stranger in a hat, a bird). Then "name" is that word \
as the text uses it. They may be someone named elsewhere, so never invent a name.
- "group": true for several taken together (the merchants, the guards, the nieces), false \
for a single one.
- Two different beings are two entries, even when they travel together or are related.
- If it is one of the already known entries below, use exactly that name, also when this \
chapter calls them only by a common word or a description (the girl, the old man) and the \
known hint matches.
- List everyone/everything that takes part in the chapter, even with no described details \
(then "facts" is an empty list). Skip passing mentions and unnamed background.
- Looks facts ("permanent" and "state") are what an illustrator needs to draw this: looks, \
not actions, speech or plot. At most 8 per entry, the most visual ones.
- "profile" facts are the general description of the entry, not looks. At most 4 per entry, \
outside the limit of 8, each short and plain, only what this chapter says.
- Each fact is one detail:
  - "category": "permanent" for what stays the same through the book ({permanent}); \
"state" for what is true at this point of the story ({state}); \
"profile" for the general description ({profile}).
  - "text": the detail, written in the language of the chapter.
  - "quote": the phrase from the chapter that supports it, copied character for character, \
under 200 characters.

Reply with one JSON object and nothing else:
{{"entities": [{{"name": "", "aliases": [], "named": true, "group": false, "facts": \
[{{"category": "permanent", "text": "", "quote": ""}}]}}]}}"""

EXTRACT_USER = """Already known:
{known}

Chapter "{title}":

{text}"""

RECONCILE_SYSTEM = """Below is a numbered list of {noun} found in one book, each with its \
other names and a few known details. Some entries may be the same one under different \
names (a nickname, a title, a short form, a different spelling).

Group only entries you are confident are the same. A man and a woman are never the same. \
Two different proper names are different ones, unless one is plainly a short form or \
nickname of the other. An entry marked [no proper name] belongs with a named one when its \
details clearly match. Companions, relatives and entries that \
merely appear together are different. When in doubt, leave them apart: a wrong merge is \
worse than a duplicate.

Reply with one JSON object and nothing else:
{{"groups": [[1, 4], [2, 7, 9]]}}
Use an empty list when nothing should be merged."""


SUMMARY_SYSTEM = """Below are numbered cards of {noun} from one book. Each lists the chapters where \
it appears, the description written for it so far (if any) and facts taken from the text. \
For every card write one general description of 3 to 5 sentences in the language of the \
facts: who or what it is, its role and function in the book, its lasting looks, and the \
traits it shows throughout. Connected prose, not a list and not quotes.
- A description written so far is the base: keep what it says, correct it only where the \
facts contradict it, and add what the new facts tell about the card as a whole. Do not \
drop it in favour of the latest chapters.
- The description is of the card as a whole, not of a moment: leave out moods, feelings \
and actions of one scene ("he is displeased", "she smiles"), unless the facts show them as \
a lasting trait.
Also write "appearance": how it looks, for an illustrator who will draw it, 2 to 4 \
sentences in the language of the facts: {appearance}. Looks only: no role, plot or \
character traits.
- An appearance written so far is the base, as with the description.
- Details from a single chapter (marked "in one chapter") belong only when nothing lasting \
says otherwise; things that repeat across chapters (the same coat, the same ruins) belong.
- Leave "appearance" empty when the facts say nothing about looks.
Use only the given facts and the texts so far. Never invent anything; if little is \
known, write less.

Reply with one JSON object and nothing else:
{{"summaries": [{{"number": 1, "text": "", "appearance": ""}}]}}"""


def _noun(kind: str) -> str:
    return "characters" if kind == KIND_CHARACTER else "locations and objects"


_APPEARANCE = {
    "character": "age, sex, build and height, face, hair, eyes, skin, scars or marks, and "
    "the clothes they usually wear",
    "location": "what kind of place or thing it is, its size and shape, materials, colours, "
    "architecture or make, and what surrounds it",
}


def summary_system(kind: str) -> str:
    return SUMMARY_SYSTEM.format(noun=_noun(kind), appearance=_APPEARANCE[kind])


def extract_system(kind: str) -> str:
    return EXTRACT_SYSTEM.format(**_SUBJECT[kind])


def reconcile_system(kind: str) -> str:
    return RECONCILE_SYSTEM.format(noun=_noun(kind))
