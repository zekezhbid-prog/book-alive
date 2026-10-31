"""Prompt templates for finding characters and locations."""

from app.models import KIND_CHARACTER

# Bump when EXTRACT_SYSTEM changes: stored chapter answers from older prompts are re-read.
PROMPT_VERSION = 3

_SUBJECT = {
    "character": {
        "what": "characters (people and other beings that act or are described)",
        "permanent": "age, face, build, height, hair, eyes, skin, scars, species, voice, "
        "lasting traits of personality",
        "state": "clothes, hairstyle, injuries, dirt or blood, weapons and objects they "
        "carry, a visible change of form or condition",
        "profile": "lasting traits of behaviour and character that show again and again "
        "(habits, manner of speech and acting, what they love or fear), their role and "
        "occupation",
    },
    "location": {
        "what": "locations (places where the action happens or that are described)",
        "permanent": "what kind of place it is, architecture, layout, materials, size, "
        "surroundings, landmarks",
        "state": "time of day, weather, season, light, damage, crowds or emptiness, "
        "sounds and smells",
        "profile": "what the place is for, who lives or works there, what happens there, "
        "its history and role in the story",
    },
}

EXTRACT_SYSTEM = """You read one chapter of a book and list the {what} in it, with what the \
text says about how they look. The result feeds illustration and video prompts, so visual \
detail matters most.

Rules:
- Use only what this chapter states. Never invent details and never guess beyond the text.
- "name": the fullest proper name the book uses. "aliases": other proper names and \
nicknames of the same one. Never put common words there (girl, old man, guest, the smith): \
many others can be called that.
- Two different beings are two entries, even when they travel together or are related.
- If it is one of the already known entries below, use exactly that name.
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
{{"entities": [{{"name": "", "aliases": [], "facts": [{{"category": "permanent", "text": "", \
"quote": ""}}]}}]}}"""

EXTRACT_USER = """Already known:
{known}

Chapter "{title}":

{text}"""

RECONCILE_SYSTEM = """Below is a numbered list of {noun} found in one book, each with its \
other names and a few known details. Some entries may be the same one under different \
names (a nickname, a title, a short form, a different spelling).

Group only entries you are confident are the same. Companions, relatives and entries that \
merely appear together are different. When in doubt, leave them apart: a wrong merge is \
worse than a duplicate.

Reply with one JSON object and nothing else:
{{"groups": [[1, 4], [2, 7, 9]]}}
Use an empty list when nothing should be merged."""


def extract_system(kind: str) -> str:
    return EXTRACT_SYSTEM.format(**_SUBJECT[kind])


def reconcile_system(kind: str) -> str:
    return RECONCILE_SYSTEM.format(noun="characters" if kind == KIND_CHARACTER else "locations")
