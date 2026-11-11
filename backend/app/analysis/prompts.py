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
- A "permanent" fact only when the text states a lasting feature. Never draw one from an \
action, a gesture or a moment (squinting, limping once, a flushed face): such a moment is \
at most a "state" fact, or nothing.
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

RECONCILE_SYSTEM = """Below is a numbered list of {noun} found in one book. Each line has \
its other names, the chapters it appears in, the others it appears with most, and a few \
known details (role, looks). Some entries may be the same one under different names (a \
nickname, a title, a short form, a different spelling, or a common word such as "the old \
man" or "the mentor" in place of the name).

Group only entries you are confident are the same:
- An entry marked [no proper name] belongs with a named one when its details fit (sex, age, \
role, occupation, looks) and it appears together with the same companions as the named one: \
the book calls a known one by a common word in a scene with the people around them.
- Two different proper names are different ones, unless one is plainly a short form or \
nickname of the other, or everything points to one: the same role and companions, details \
that fit, and the two names never appear in the same chapter.
- A man and a woman are never the same. Companions, relatives and entries that merely \
appear together are different. Two entries that act side by side in the same chapter are \
different.
When in doubt, leave them apart: a wrong merge is worse than a duplicate.

Reply with one JSON object and nothing else:
{{"groups": [[1, 4], [2, 7, 9]]}}
Use an empty list when nothing should be merged."""


ADOPT_SYSTEM = """Below are numbered {noun} that a book never calls by a proper name (the old \
man, the mentor, a girl), each with the chapters it appears in, the named ones it appears \
with, and what the text says about it with the book's own words. Under each are lettered \
candidates: named ones from the same book who may be the same.

For each numbered entry decide whether it is one of its candidates. It is the same one when \
the signs agree and nothing contradicts them:
- sex and age fit, and the looks fit;
- the role, occupation or title fits;
- it appears with the people the candidate is with (friends, family, master, servants, \
enemies), and what it does fits the candidate's part in the story.
It is not the same one when anything clearly contradicts (sex, age, looks, role), or when \
it acts beside the candidate as a different person in the same scene. A crowd or a group is \
never one person. When in doubt, choose nothing: a wrong merge is worse than a card left \
apart.

Reply with one JSON object and nothing else, listing only the entries that match:
{{"matches": [{{"number": 1, "candidate": "B"}}]}}"""


def adopt_system(kind: str) -> str:
    return ADOPT_SYSTEM.format(noun=_noun(kind))


SUMMARY_SYSTEM = """Below are numbered cards of {noun} from one book. Each lists the chapters where \
it appears, the description written for it so far (if any) and facts taken from the text, \
chapter by chapter: "about" facts tell who or what it is, "looks" facts how it looks.

For every card write "text", one general description in the language of the facts: who or \
what it is, its role and occupation, its ties to others, the main line of what it does in \
the story from beginning to end (not single episodes), and the traits it shows throughout. \
Connected prose, not a list and not quotes.
- Use all the facts given. For a minor one with few facts, three to five sentences when the \
facts allow; for a main one that appears in many chapters, a full paragraph of six to ten \
sentences that covers the whole book, not just its first chapters. Never pad beyond the facts.
- A description written so far is the base: keep what the facts support, add what the new \
facts tell, correct or drop what the facts do not support.
- The description is of the card as a whole, not of a moment: leave out moods, feelings \
and actions of one scene ("he is displeased", "she smiles"), unless the facts show them as \
a lasting trait.
Use only the given facts. Never invent anything.

Reply with one JSON object and nothing else:
{{"summaries": [{{"number": 1, "text": ""}}]}}"""


LOOKS_SYSTEM = """Below is one of the {noun} of a book: its name, the chapters where it appears \
and every looks detail found in the text, each with its chapter and the words of the book.

Write "appearance": how it looks, for an illustrator who will draw it, in the language of \
the details: {appearance}.
- Keep every concrete detail: colours, materials, cut and ornament of clothes (buttons, \
embroidery, belts), hair and beard, marks, size and shape, what it is made of. Precision \
matters more than brevity: as long as the details need, usually three to eight sentences.
- Check each detail against the words of the book: if they show it belongs to someone or \
something else, or to a moment (a gesture, an action, a flushed face, squinting once), \
leave it out.
- When details contradict (grey hair and red hair), keep the one the book repeats, or the \
one it states plainly, never both and never a mix.
- Clothes, objects and marks seen in one chapter belong too. When they differ between \
chapters, describe what repeats as the usual look and name the rest with where it is worn \
("in the chapter X he wears ...").
Looks only: no role, plot or character traits. Use only the details below; never invent.

Reply with one JSON object and nothing else:
{{"appearance": ""}}"""


GENERAL_SYSTEM = """Below are numbered general descriptions of {noun} from one book. A general \
description tells who or what it is, its role and occupation, its ties to others, the main \
line of what it does across the story and its lasting traits.

Check every description and remove what belongs to a single chapter or scene rather than to \
the card as a whole: one particular thing done or said once ("he reminds her to eat", "she \
opens the gate for them"), one moment's mood, place or clothing, a detail of one episode. \
Such things are kept chapter by chapter elsewhere; here they do not belong. A habit or a \
duty the description presents as lasting stays.
- Only remove, and mend the grammar where a removal breaks a sentence. Never add anything, \
never reword what stays, keep the language.
- When nothing needs removing, return the description unchanged.

Reply with one JSON object and nothing else, an entry for every description:
{{"texts": [{{"number": 1, "text": ""}}]}}"""


def general_system(kind: str) -> str:
    return GENERAL_SYSTEM.format(noun=_noun(kind))


def _noun(kind: str) -> str:
    return "characters" if kind == KIND_CHARACTER else "locations and objects"


_APPEARANCE = {
    "character": "age, sex, build and height, face, hair, eyes, skin, scars or marks, and "
    "the clothes they usually wear",
    "location": "what kind of place or thing it is, its size and shape, materials, colours, "
    "architecture or make, and what surrounds it",
}


def summary_system(kind: str) -> str:
    return SUMMARY_SYSTEM.format(noun=_noun(kind))


def looks_system(kind: str) -> str:
    return LOOKS_SYSTEM.format(noun=_noun(kind), appearance=_APPEARANCE[kind])


def extract_system(kind: str) -> str:
    return EXTRACT_SYSTEM.format(**_SUBJECT[kind])


def reconcile_system(kind: str) -> str:
    return RECONCILE_SYSTEM.format(noun=_noun(kind))
