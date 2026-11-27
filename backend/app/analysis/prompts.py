"""Prompt templates for finding characters, locations and items."""

from app.models import KIND_CHARACTER, KIND_ITEM

# Bump when EXTRACT_SYSTEM changes: stored chapter answers from older prompts are re-read.
PROMPT_VERSION = 9
# A kind whose prompt changed alone: only its stored answers are re-read, the rest stay.
# Places got a strict filter on 23.11.2026 (no vague spots, a part says what it is part of).
KIND_VERSIONS = {"location": 10}


def prompt_version(kind: str) -> int:
    return KIND_VERSIONS.get(kind, PROMPT_VERSION)


_SUBJECT = {
    "character": {
        "what": "characters: living, animate beings only (people, animals, spirits, gods, \
monsters, any creature that thinks, speaks or acts on its own will). Never list objects, \
weapons, buildings, places, plants, weather, natural phenomena, illnesses or abstract \
things, however vividly the text describes them; a thing becomes a character only when \
the story makes it alive (it speaks or acts by itself)",
        "permanent": "age, face, build, height, hair, eyes, skin, scars, species, voice, "
        "lasting traits of personality; for a creature that is not human (a spirit, "
        "monster, mythical being, animal, bird): what kind of being it is, the exact animal "
        "or bird when the text names it, size, body shape, skin, scales, fur or feathers, "
        "colour, wings, tail, horns, claws, number of heads or limbs, human features if any",
        "state": "clothes, hairstyle, injuries, dirt or blood, weapons and objects they "
        "carry, a visible change of form or condition",
        "profile": "lasting traits of behaviour and character that show again and again "
        "(habits, manner of speech and acting, what they love or fear), their role and "
        "occupation",
    },
    "location": {
        "what": 'locations: places where the action happens or that are described (lands, \
towns, villages, forests, rivers, roads, houses, rooms, and buildings or landmarks such as a \
bridge, a tower or a mill). Never list movable objects (weapons, tools, jewels, books, \
vehicles): they are items. Skip living beings: they are characters. A place gets an entry \
only when it is a specific place someone could paint: it has a proper name, or the text shows \
what it looks like (its kind of building, materials, shape, colours, a feature that sets it \
apart). Skip vague and generic spots described with no look of their own, whatever word names \
them (a forest, a swamp, a road, a river bank, the border, the land, "some tower", "a \
town"), places only passed through or spoken of, and anything that is just a direction. A \
part of a building (a room, a chamber, a hall, a courtyard) is named with what it is part \
of: "the chamber (Vavel castle)", never just "the chamber"',
        "permanent": "what kind of place it is, architecture, layout, shape, materials, "
        "size, ornament, surroundings, landmarks",
        "state": "time of day, weather, season, light, damage, crowds or emptiness, "
        "sounds and smells",
        "profile": "what the place is for, who lives or works there or owns it, what "
        "happens there, its history and role in the story",
    },
    "item": {
        "what": "items: notable movable inanimate things (weapons, armour, tools, jewels, \
artifacts, books, letters, keys, vehicles, important things a character owns, carries or \
uses). Never list places, buildings or landmarks: they are locations. Skip living beings: \
they are characters. Skip ordinary everyday things that play no part",
        "permanent": "what kind of thing it is, shape, size, materials, colours, make, "
        "ornament, inscriptions, marks",
        "state": "damage, wear, dirt or blood, whether it glows or is broken, who holds or "
        "uses it now and where it is",
        "profile": "what the thing is for, who made, owns or uses it, what it can do, its "
        "history and role in the story",
    },
}

# Who a detail belongs to, what counts as true, how a voice sounds. Shared by the chapter
# search and the rebuild of one card; written for any book, in any language.
_FACT_RULES = """- A detail belongs to an entry only when the quoted words describe that entry \
itself. In a dialogue or a scene with several people, work out whom each description and \
each pronoun is about: a speaker who describes someone else, a listener who hears it, or \
someone standing nearby never gets that detail. When it is unclear whose it is, write no \
fact.
- What one character says or thinks about another (an accusation, an insult, a rumour, a \
guess, a threat, a lie, a mistaken belief) is not a fact about that other: never write it \
as their trait, role or look. Plain information the story confirms (age, kinship, a name, \
a job) may come from anyone's words.
- The quote must show the detail itself: a fact about a beard needs words about the beard. \
No quote, no fact.
- Turning into something and taking someone's look: keep the direction exactly as the \
text tells it - who changed, from what, into what, and whose look they took. Never turn it \
around, never shorten it into a different story.
- A way of speaking is described as the text renders it: drawn-out or doubled sounds \
("s-s-so", "yesss", "rrright") are hissing, a drawl, a growl or a lisp. Call it stuttering \
only when the words say so or the text repeats whole syllables at the start of a word \
("I-I-I", "b-b-but"). Read the text in its own language, whatever it is.
- When the chapter states an age (a number of years or winters, "turned fourteen", "a \
child of five"), always write it as a "permanent" fact, even in passing.
"""

EXTRACT_SYSTEM = """You read one chapter of a book and list the entries of one kind in it, \
with what the text says about how they look. The result feeds illustration and video \
prompts, so visual detail matters most.

What to list: {what}.

Rules:
- Use only what this chapter states. Never invent details and never guess beyond the text.
{fact_rules}- "name": the fullest proper name the book uses. "aliases": other proper names and \
nicknames of the same one, only when the text makes plain that it is the same one. Never put \
there the name of another entry, a friend, relative or companion. Never put common words \
there (girl, old man, guest, the smith): many others can be called that.
- "named": true when the text gives a proper name; false when it only calls them by a \
common word (the old man, a girl, the stranger in a hat, a bird). Then "name" is that word \
as the text uses it. They may be someone named elsewhere, so never invent a name.
- "group": true for several taken together (the merchants, the guards, the nieces), false \
for a single one.
- Two different beings are two entries, even when they travel together or are related.
- One being in several forms (a shape-shifter, a disguise, a being turned into another \
shape) is one entry, also when each form has its own name: put the other names in \
"aliases" and write the form in its facts ("in the form of a cat: grey fur"). But \
beings who only share a name or a title (a father and a son, an old one and a young one \
of the same kind, one born or hatched later), and a being that split off from another and \
acts on its own (a shadow, a double, a reflection), are separate entries: never make one \
an alias of the other.
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
- A bodily lack or defect (one eye, blindness, a lame leg, a missing hand, deafness, a \
hunchback) is a fact only when the words say it outright ("he had one eye", "blind in one \
eye", "his empty sleeve"). Closing, narrowing or covering an eye, a sideways look, limping \
after a blow, holding an arm are actions: write no looks fact from them at all.
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
- Two entries that both have a proper name are always different ones: never group them \
together. Every group has at most one entry without the [no proper name] mark; it may also \
be made of [no proper name] entries only.
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
- Its origin (where it comes from, how it was born, found, saved, adopted or made) belongs \
in the description whenever the facts tell it. A fact saying the text is silent on some \
point is no claim: never turn it into "nothing is known" about what other facts do tell.
- Use all the facts given. For a minor one with few facts, three to five sentences when the \
facts allow; for a main one that appears in many chapters, a full paragraph of six to ten \
sentences that covers the whole book, not just its first chapters. Never pad beyond the facts.
- A description written so far is the base: keep what the facts support, add what the new \
facts tell, correct or drop what the facts do not support.
- The trait that sets it apart from everyone else (an unusual gift or power, a striking \
habit, the way it speaks) belongs in the description whenever the facts show it.
- A being with several forms: say what each form is.
- The description is of the card as a whole, not of a moment: leave out moods, feelings \
and actions of one scene ("he is displeased", "she smiles"), unless the facts show them as \
a lasting trait.
{notes_rule}Use only the given facts and notes. Never invent anything.

Reply with one JSON object and nothing else:
{{"summaries": [{{"number": 1, "text": ""}}]}}"""


LOOKS_SYSTEM = """Below is one of the {noun} of a book: its name, the chapters where it appears \
and every looks detail found in the text, each with its chapter and the words of the book.

Write "appearance": how it looks, for an illustrator who will draw it, in the language of \
the details: {appearance}.
{age}- Keep every concrete detail: colours, materials, cut and ornament of clothes (buttons, \
embroidery, belts), hair and beard, marks, size and shape, what it is made of. Precision \
matters more than brevity: as long as the details need, usually three to eight sentences.
- Check each detail against the words of the book: if they show it belongs to someone or \
something else, or to a moment (a gesture, an action, a flushed face, squinting once), \
leave it out.
- A bodily lack or defect (one eye, blindness, a limp, a missing hand) stays only when the \
quoted words state it outright. When the quote shows only an action (closing or narrowing \
one eye, a sideways look, limping after a blow), the detail is a misreading: drop it.
- When details contradict (grey hair and red hair), keep the one the book repeats, or the \
one it states plainly, never both and never a mix.
- Clothes, objects and marks seen in one chapter belong too. When they differ between \
chapters, describe what repeats as the usual look and name the rest with where it is worn \
("in the chapter X he wears ...").
- The details come in story order with chapter numbers. A change that happens in the \
story (a burn, a wound, a new scar, grey or cut hair, a lost eye or limb, thinness after \
hunger, new clothes for good) is not the look of the whole book: describe the look before \
it first, then the change with the chapter it first appears in ("from chapter 48: burned \
hands and face"). Treat a detail as such a change when it first shows up late, comes from \
an event, or earlier chapters describe the same body part without it.
- A creature that is not human (a spirit, a monster, a mythical being, an animal, a bird) \
is drawn by someone who has never seen it: start with what it is (its kind as the book \
calls it, the exact species of an animal or bird when the details name it), then its size \
and body shape, and every described part of it - head, eyes, skin, scales, fur or feathers, \
colour, wings, tail, horns, claws, how many heads or limbs, what in it is human-like and \
what is not, how it moves. A being that takes several forms gets each form apart, with the \
chapter where it shows.
{notes_rule}Looks only: no role, plot or character traits. Use only the details below; never invent.

Reply with one JSON object and nothing else:
{{"appearance": ""}}"""


GENERAL_SYSTEM = """Below are numbered general descriptions of {noun} from one book. A general \
description tells who or what it is, its role and occupation, its ties to others, the main \
line of what it does across the story and its lasting traits.

Check every description and remove what belongs to a single chapter or scene rather than to \
the card as a whole: one particular thing done or said once ("he reminds her to eat", "she \
opens the gate for them"), one moment's mood, place or clothing, a detail of one episode. \
Such things are kept chapter by chapter elsewhere; here they do not belong. A habit or a \
duty the description presents as lasting stays. Its origin (where it comes from, how it \
was born, found, saved, adopted or made) and the turns that change its life for good stay \
too, even when they happen in one scene.
- Only remove, and mend the grammar where a removal breaks a sentence. Never add anything, \
never reword what stays, keep the language.
- When nothing needs removing, return the description unchanged.

Reply with one JSON object and nothing else, an entry for every description:
{{"texts": [{{"number": 1, "text": ""}}]}}"""


def general_system(kind: str) -> str:
    return GENERAL_SYSTEM.format(noun=_noun(kind))


def _noun(kind: str) -> str:
    return {KIND_CHARACTER: "characters", KIND_ITEM: "objects"}.get(kind, "locations")


# An illustrator who is not told the age draws an adult: a boy of fourteen came out bearded.
_AGE = (
    "- A human or human-like being: the first sentence gives the sex and the age. The "
    'number when the book states it ("14 years old"); otherwise an estimate from the details '
    'and from who it is ("about 13-15, a teenager", "about 70, an old man"), said to be an '
    "estimate. Never leave the age out. When the book shows the age changing (years pass), "
    "give the age at first appearance, then the later one with its chapter.\n"
)

_APPEARANCE = {
    "character": "age, sex, build and height, face, hair, eyes, skin, scars or marks, and "
    "the clothes they usually wear; for a creature that is not human: what kind of being it "
    "is, size, body shape and every part of the body the book describes",
    "location": "what kind of place it is, its size and shape, materials, colours, "
    "architecture, and what surrounds it",
    "item": "what kind of thing it is, its size and shape, materials, colours, make, "
    "ornament and marks",
}


def summary_system(kind: str) -> str:
    return SUMMARY_SYSTEM.format(noun=_noun(kind), notes_rule=NOTES_RULE)


CARD_FACTS_SYSTEM = """You read one chapter of a book and collect what it says about ONE entry \
only: {target}. Ignore every other {noun_one}.

Find it in the chapter also when it is called by another of its names, a common word (the \
old man, the girl) or a pronoun, as long as the text makes plain it is the same one. If it \
does not take part in the chapter, reply with no facts and "present": false.

Rules:
- Use only what this chapter states. Never invent details and never guess beyond the text.
- Looks facts ("permanent" and "state") are what an illustrator needs to draw it: looks, \
not actions, speech or plot. At most 10, the most visual ones.
- A "permanent" fact only when the text states a lasting feature. Never draw one from an \
action, a gesture or a moment (squinting, limping once, a flushed face).
- A bodily lack or defect (one eye, blindness, a lame leg, a missing hand) is a fact only \
when the words say it outright. Closing, narrowing or covering an eye, a sideways look, \
limping after a blow are actions: write no looks fact from them.
- Never take a detail of someone or something else standing near it.
{fact_rules}- "profile" facts are the general description, not looks: at most 5, short and plain.
- Each fact:
  - "category": "permanent" for what stays the same through the book ({permanent}); \
"state" for what is true at this point of the story ({state}); \
"profile" for the general description ({profile}).
  - "text": the detail, written in the language of the chapter.
  - "quote": the phrase from the chapter that supports it, copied character for character, \
under 200 characters.

Reply with one JSON object and nothing else:
{{"present": true, "facts": [{{"category": "permanent", "text": "", "quote": ""}}]}}"""


def card_facts_system(kind: str, target: str) -> str:
    subject = _SUBJECT[kind]
    return CARD_FACTS_SYSTEM.format(
        target=target,
        fact_rules=_FACT_RULES,
        noun_one={KIND_CHARACTER: "character", KIND_ITEM: "object"}.get(kind, "place"),
        permanent=subject["permanent"],
        state=subject["state"],
        profile=subject["profile"],
    )


IMPROVE_SYSTEM = """You read one chapter of a book to improve the card of ONE entry: \
{target}. Ignore every other {noun_one}. The card already has facts from this chapter; \
they are mostly right, so keep them and add only what is missing.

Find it in the chapter also when it is called by another of its names, a common word or a \
pronoun, as long as the text makes plain it is the same one. If it does not take part in \
the chapter, reply with "present": false and nothing else.

You get:
- "Known facts": numbered facts the card already has from this chapter.
- "Author's notes": numbered things the author of the book says about it. They are true \
even when the book never says them.
- "Wishes": what the author wants improved this time (may be empty).

Do this:
- "facts": only NEW facts the known ones do not already say, with what the wishes ask for \
first. Never repeat a known fact in other words.
- "wrong": numbers of known facts that are wrong: they contradict an author's note, or \
their quote shows the detail belongs to someone or something else or to a moment only.
- "confirmed": numbers of author's notes this chapter states itself; for each, also add \
the fact with its quote to "facts" (unless a known fact already says it).

Rules for new facts:
- Use only what this chapter states. Never invent details and never guess beyond the text. \
An author's note is no quote: a fact still needs the chapter's own words.
- Looks facts ("permanent" and "state") are what an illustrator needs to draw it: looks, \
not actions, speech or plot.
- A "permanent" fact only when the text states a lasting feature, never from an action, a \
gesture or a moment.
- Never take a detail of someone or something else standing near it.
{fact_rules}- Each fact:
  - "category": "permanent" for what stays the same through the book ({permanent}); \
"state" for what is true at this point of the story ({state}); \
"profile" for the general description ({profile}).
  - "text": the detail, written in the language of the chapter.
  - "quote": the phrase from the chapter that supports it, copied character for character, \
under 200 characters.

Reply with one JSON object and nothing else:
{{"present": true, "facts": [{{"category": "permanent", "text": "", "quote": ""}}], \
"wrong": [], "confirmed": []}}"""


def improve_system(kind: str, target: str) -> str:
    subject = _SUBJECT[kind]
    return IMPROVE_SYSTEM.format(
        target=target,
        fact_rules=_FACT_RULES,
        noun_one={KIND_CHARACTER: "character", KIND_ITEM: "object"}.get(kind, "place"),
        permanent=subject["permanent"],
        state=subject["state"],
        profile=subject["profile"],
    )


WISH_NOTE_SYSTEM = """The author of a book asks to improve one card of their book. Below are \
the card's name and the author's words.

Keep only what the author states about the card itself: facts about it (age, origin, looks, \
kin, role), in the author's own words. Drop everything that only asks for something or \
names the card: "this is X", "merge them", "improve the description", "add the looks", \
"check chapter 5". Do not add, explain or translate anything.

Reply with one JSON object and nothing else; "note" is empty when nothing is stated:
{"note": ""}"""


# The author's notes ride along with every description request; this tells how to read them.
NOTES_RULE = """- "author's notes" are what the author of the book says about the card: they \
are true even without a quote. Use them, and where a fact contradicts a note, the note wins.
"""


def looks_system(kind: str) -> str:
    age = _AGE if kind == KIND_CHARACTER else ""
    return LOOKS_SYSTEM.format(
        noun=_noun(kind), appearance=_APPEARANCE[kind], age=age, notes_rule=NOTES_RULE
    )


def extract_system(kind: str) -> str:
    return EXTRACT_SYSTEM.format(fact_rules=_FACT_RULES, **_SUBJECT[kind])


def reconcile_system(kind: str) -> str:
    return RECONCILE_SYSTEM.format(noun=_noun(kind))


# ---------- deep search (app.analysis.deep) ----------

INDEX_SYSTEM = """You read one chapter of a book, given as numbered paragraphs, and list \
the characters in it with the numbers of the paragraphs where each one is mentioned or acts \
(also through a pronoun or a word like "the old man" when it is clear who that is). \
Characters are living, animate beings only: people, animals, spirits, creatures that think, \
speak or act on their own. Named characters matter most: find every one, even one named \
only once.

- Write the name in its base form, as a dictionary would list it (nominative, singular), in \
the language and spelling of the book: "Тарас" for "Тараса", "Тарасу", "Тарасам"; "Андрэй" for \
"Андрэя", "Андрэю". All forms of one name in the chapter are ONE entry with all their paragraphs.
- When the chapter calls a named character also by a common word or a pronoun ("the old \
man", "he", "the prince"), put those paragraphs under the name; the word gets no entry of \
its own.
- A thing or an animal a character has turned into ("the stone", "the raven") is that \
character: those paragraphs go under the character's name, even when the word is written \
with a capital letter.
- A new being that shares a name with an older one (a newborn, a child, an heir, someone \
reborn: "the young king", "his son") is a separate entry under the name or title \
the chapter gives it ("the Queen", "the young king"), never under the older one's name.
- Two different proper names or a nickname for the same character stay separate entries: \
do not decide who is who, that is done later.
- A single character the chapter never names gets an entry under its describing word in \
the base form ("the old man", not "of the old man") and "named": false, only when it speaks \
or acts in this chapter. Skip crowds and groups of ordinary people (people, guards, traders, \
servants, warriors) and anyone only spoken about in passing. A kind of creature the story \
is about (mermaids, goblins) is listed once, under the plural.

Do not describe anyone, do not explain. Reply with JSON only:
{"mentions": [{"name": "...", "named": true, "paragraphs": [0, 3, 4]}]}"""

CAST_SYSTEM = """Below is the cast of a whole book: every name found in it, the chapters \
where it occurs and a few paragraphs where it first (and last) appears. Work out who is who.

- The same being under several names, nicknames or forms (someone who turns into an animal, \
a star, a boy, someone who takes another's look) is ONE being: list all those names as its \
sources and its forms. A thing or an animal it turns into, even written with a capital \
letter ("Stone", "Raven"), is a source of that being, not a being of its own.
- Two different beings under one name (a namesake, a newborn named after someone, a part \
that split off and lives on its own, twins) are TWO beings: give each its own name and the \
chapter numbers where the shared name means that one.
- A name that is only a lie, a cover or a mistake inside the story (a stranger is passed \
off as "my niece Mary" to get past the guards) is a false name: it is not the being's name. \
Put it in false_names with whom it was said about.
- A word used as a form of address or about age ("grandad", "son", "old woman") is not a \
name and not a kinship.
- A common word for a person ("the old man", "the girl", "mother", "the prince"; marked \
"not a proper name") may mean different people in different chapters. Give it to a being \
as a source ONLY with the chapter numbers where it means that being, never for the whole \
book. Where it fits nobody, leave it out.
- A form of a name in another grammatical case ("Tarasa", "Andreyu") is a source of that \
being.
- The book's title, headings and the author's name go to titles.
- not_characters is ONLY for crowds and roles of ordinary people ("people", "traders", \
"guards", "servants") and for ordinary animals or things that only pass by. Everything else \
is a being, however minor, even if it appears in one chapter only: anyone with a proper \
name; any spirit, monster, magic or talking creature; a kind of such creatures, even \
written in lower case or in the plural ("goblins", "will-o'-the-wisps"); a part or a shadow \
that split off and acts on its own. When in doubt, keep it as a being.
- Keep every decision of the user listed at the end.

Use the main name the book uses most. Every proper name in the list must end up somewhere: \
a being's source, a false name, titles or not_characters.

Reply with JSON only:
{"beings": [{"name": "...", "sources": [{"name": "...", "chapters": []}], "forms": ["..."]}],
 "false_names": [{"name": "...", "belongs_to": "...", "reason": "..."}],
 "titles": ["..."],
 "not_characters": ["..."]}
"chapters": [] means everywhere in the book (for proper names only)."""

DOSSIER_SYSTEM = (
    """Below is every passage of a book about ONE character, in story order, \
chapter by chapter, with numbered paragraphs. Write down what the book says about this \
character as facts, each with a quote copied word for word from one paragraph and the \
chapter number it is in.

Categories:
- "permanent": """
    + _SUBJECT["character"]["permanent"]
    + """
- "state": """
    + _SUBJECT["character"]["state"]
    + """ (true in one chapter)
- "profile": """
    + _SUBJECT["character"]["profile"]
    + """; also kinship and other ties, and \
what happens to them in the story

"""
    + _FACT_RULES
    + """- You see the whole story: use it. A claim made once and contradicted by \
everything else (a lie, a cover story, a mistake of another character, a joke) is not a fact; \
if you keep it at all, mark it "doubtful": true.
- Kinship only when the text says it plainly. "Grandad", "son", "granny" used as an address \
or a nickname is about age, not kinship. Tell kin by blood from someone who raised them, a \
foundling, an adopted child, and from someone who only took a relative's look: write which \
it is ("raised him as her own, not his mother").
- Age: give it in "age" with the reasoning. Count it when the text gives the pieces ("he \
was one year old then", "thirteen years later"; "as old as X" with X's age listed below). \
Only when nothing allows a count, estimate it and say it is an estimate.
- Write every description of the body, size, hair and face the passages give; never write \
that something is not described when a passage describes it.
- A way of speaking the text shows (drawn-out hissing, whistling "ss", a growl) is a \
"permanent" fact; tell apart characters who speak alike.
- Several forms of one being: say for each look which form it is.
- Write the facts in the language of the book.

Reply with JSON only:
{"aliases": ["other real names of the character"], "age": "...",
 "facts": [{"category": "permanent", "text": "...", "quote": "...", "chapter": 3, \
"doubtful": false}]}"""
)

CHECK_SYSTEM = """Below are numbered facts written about ONE character, each with its quote \
and the paragraph the quote is from. Read each paragraph and decide whether the quote really \
speaks about this character. A detail of someone else in the same paragraph (another \
person's beard, a listener, a speaker describing a third person) is wrong. Words one \
character says about another that the story does not confirm (a lie, an insult, a guess) \
are wrong as facts. When the quote does speak about this character, the fact is right.

Reply with JSON only: {"wrong": [numbers of the wrong facts]} - an empty list when all are \
right."""


# The deep search for places and objects: the same four steps, told what to look for.

_INDEX_OTHER = """You read one chapter of a book, given as numbered paragraphs, and list \
the {noun} in it with the numbers of the paragraphs where each one is mentioned{where} (also \
through a pronoun or a word like {words} when it is clear which one that is). {what} Named \
{noun} matter most: find every one, even one named only once.

- Write the name in its base form, as a dictionary would list it (nominative, singular), in \
the language and spelling of the book: "Палац" for "Палаца", "Палацы". All forms of one name \
in the chapter are ONE entry with all their paragraphs.
- When the chapter calls a named one also by a common word or a pronoun ({words}), put \
those paragraphs under the name; the word gets no entry of its own.
{extra}- Two different proper names for the same one stay separate entries: do not decide \
which is which, that is done later.
- One the chapter never names gets an entry under its describing word in the base form \
({words}) and "named": false, only when {unnamed}. Skip {skip}.

Do not describe anything, do not explain. Reply with JSON only:
{{"mentions": [{{"name": "...", "named": true, "paragraphs": [0, 3, 4]}}]}}"""

_INDEX_PARTS = {
    "location": {
        "noun": "places",
        "where": " or where the action happens",
        "words": '"the castle", "the village", "there"',
        "what": "Places are lands, towns, villages, forests, rivers, lakes, roads, houses, "
        "rooms, and buildings or landmarks such as a bridge, a tower or a mill.",
        "extra": "- A part of a place (a room, a tower, a courtyard, a cellar) is an entry of "
        "its own when the chapter names it or shows how it looks; its name says what it is "
        'part of: "the chamber (Vavel castle)", not "the chamber".\n',
        "unnamed": "the chapter shows what it looks like (its kind of building, materials, "
        "shape, colours, a feature of its own)",
        "skip": "places only mentioned in passing that the chapter neither names nor shows, "
        "vague and generic spots with no look of their own (a forest, a swamp, a road, a river "
        "bank, the border, the land, some tower, a town), directions (somewhere, the ground, "
        "home as a direction), living beings and movable objects",
    },
    "item": {
        "noun": "objects",
        "where": "",
        "words": '"the sword", "the ring", "it"',
        "what": "Objects are notable movable inanimate things: weapons, armour, tools, "
        "jewels, artifacts, books, letters, keys, vehicles, important things someone owns, "
        "carries, seeks or uses.",
        "extra": "- A thing a character has turned into, or one that speaks and acts by "
        "itself, is a character, not an object: skip it.\n",
        "unnamed": "it plays a part in this chapter (it is used, given, sought, lost, made "
        "or described)",
        "skip": "ordinary everyday things that play no part (a cup drunk from once, a door "
        "opened), places and buildings, living beings",
    },
}

_CAST_OTHER = """Below is every {noun_one} found in a whole book: each name, the chapters \
where it occurs and a few paragraphs where it first (and last) appears. Work out which \
entries are the same {noun_one}.

- The same {noun_one} under several names, a short name or a description ({same}) is ONE \
entry: list all those names as its sources. Other looks it takes in the story ({forms}) go \
to its forms.
- Two different {noun} under one name ({two}) are TWO entries: give each its own name and \
the chapter numbers where the shared name means that one.
- A name that is only a lie, a cover or a mistake inside the story is a false name: it is \
not the {noun_one}'s name. Put it in false_names with which one it was said about.
- A common word ({common}; marked "not a proper name") may mean different {noun} in \
different chapters. Give it to an entry as a source ONLY with the chapter numbers where it \
means that one, never for the whole book. Where it fits none, leave it out.
{extra}- A form of a name in another grammatical case is a source of that entry.
- The book's title, headings and the author's name go to titles.
- dropped is ONLY for what is no {noun_one} at all ({dropped}). Everything else is an \
entry, however minor, even if it appears in one chapter only: anything with a proper name, \
anything the story describes or returns to. When in doubt, keep it.
- Keep every decision of the user listed at the end.

Use the main name the book uses most. Every proper name in the list must end up somewhere: \
an entry's source, a false name, titles or dropped.

Reply with JSON only:
{{"entries": [{{"name": "...", "sources": [{{"name": "...", "chapters": []}}], \
"forms": ["..."]}}],
 "false_names": [{{"name": "...", "belongs_to": "...", "reason": "..."}}],
 "titles": ["..."],
 "dropped": ["..."]}}
"chapters": [] means everywhere in the book (for proper names only)."""

_CAST_PARTS = {
    "location": {
        "noun_one": "place",
        "noun": "places",
        "same": '"the castle", "Vavel", "the prince\'s castle"',
        "forms": "a castle before and after a fire, a village in ruins",
        "two": "two villages of one name, the forest of one chapter and another forest",
        "common": '"the forest", "the house", "the road", "the hut"',
        "extra": "- A part of a place (a room, a tower, a courtyard) stays an entry of its "
        "own when the book names it or shows how it looks; do not fold it into the whole, "
        'but name it with what it is part of: "the chamber (Vavel castle)". The same word '
        "for rooms of different buildings is different entries.\n"
        "- The cards are for pictures and video: a generic spot with no look of its own (a "
        "forest, a swamp, a road, a river bank, the border, the land, some tower, a town) "
        "goes to dropped, however often it appears.\n",
        "dropped": "a living being, a movable object, a time, an idea, a vague or generic "
        "spot with no look of its own, a direction that only passes by (somewhere, the "
        "ground, home as a direction)",
    },
    "item": {
        "noun_one": "object",
        "noun": "objects",
        "same": '"the sword", "Grandfather\'s sword", "the blade"',
        "forms": "a broken and a mended sword, a ring that turned into a key",
        "two": "two swords both called \"the sword\", a father's and a son's ring",
        "common": '"the sword", "the ring", "the letter", "the book"',
        "extra": "- A thing a character has turned into, or one that speaks and acts by "
        "itself, is a character: put it in dropped.\n",
        "dropped": "a living being, a place or a building, an everyday thing that plays no "
        "part, an idea",
    },
}

_DOSSIER_OTHER = """Below is every passage of a book about ONE {noun_one}, in story order, \
chapter by chapter, with numbered paragraphs. Write down what the book says about this \
{noun_one} as facts, each with a quote copied word for word from one paragraph and the \
chapter number it is in.

Categories:
- "permanent": {permanent}
- "state": {state} (true in one chapter)
- "profile": {profile}; also what happens {there} in the story

{fact_rules}- You see the whole story: use it. A claim made once and contradicted by \
everything else (a lie, a cover story, a mistake of a character, a joke) is not a fact; if \
you keep it at all, mark it "doubtful": true.
- A detail of someone or something else in the same paragraph (a person's clothes in the \
room, another {noun_one} nearby) is not about this {noun_one}.
- Write every description of shape, size, materials, colours and ornament the passages \
give; never write that something is not described when a passage describes it.
- Several looks of one {noun_one} (before and after it was burnt, broken, rebuilt): say \
for each look which one it is.
- Write the facts in the language of the book.

Reply with JSON only:
{{"aliases": ["other real names of the {noun_one}"],
 "facts": [{{"category": "permanent", "text": "...", "quote": "...", "chapter": 3, \
"doubtful": false}}]}}"""

_CHECK_OTHER = """Below are numbered facts written about ONE {noun_one}, each with its quote \
and the paragraph the quote is from. Read each paragraph and decide whether the quote really \
speaks about this {noun_one}. A detail of something else in the same paragraph ({other}) is \
wrong. Words a character says that the story does not confirm (a lie, a boast, a guess) are \
wrong as facts. When the quote does speak about this {noun_one}, the fact is right.

Reply with JSON only: {{"wrong": [numbers of the wrong facts]}} - an empty list when all are \
right."""

_OTHER = {
    "location": {
        "noun_one": "place",
        "there": "there",
        "other": "another place, a person or an object in this place",
    },
    "item": {
        "noun_one": "object",
        "there": "with it",
        "other": "another object, the person who holds it, the place where it lies",
    },
}


def card_label(kind: str) -> str:
    """What a card is called at the head of a request: "Character: Anna"."""
    return {KIND_CHARACTER: "Character", KIND_ITEM: "Object"}.get(kind, "Place")


def index_system(kind: str) -> str:
    if kind == KIND_CHARACTER:
        return INDEX_SYSTEM
    return _INDEX_OTHER.format(**_INDEX_PARTS[kind])


def cast_system(kind: str) -> str:
    if kind == KIND_CHARACTER:
        return CAST_SYSTEM
    return _CAST_OTHER.format(**_CAST_PARTS[kind])


def dossier_system(kind: str) -> str:
    if kind == KIND_CHARACTER:
        return DOSSIER_SYSTEM
    subject = _SUBJECT[kind]
    return _DOSSIER_OTHER.format(
        fact_rules=_FACT_RULES,
        permanent=subject["permanent"],
        state=subject["state"],
        profile=subject["profile"],
        noun_one=_OTHER[kind]["noun_one"],
        there=_OTHER[kind]["there"],
    )


def check_system(kind: str) -> str:
    if kind == KIND_CHARACTER:
        return CHECK_SYSTEM
    return _CHECK_OTHER.format(noun_one=_OTHER[kind]["noun_one"], other=_OTHER[kind]["other"])
