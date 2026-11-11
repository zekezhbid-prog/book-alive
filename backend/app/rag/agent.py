"""The book chat as an agent. A model cannot read a whole novel for every question, and a
few search hits are too little to answer from, so the agent gets the table of contents
and two tools: search the book, and open a whole chapter. It decides what to look at
until it has enough, then answers from what it has read.

A LangGraph loop of one decision node and the two tools. Tool calls go through plain
JSON in the reply, as everywhere in the app: not every provider supports tool calling.
"""

import os
from typing import Literal, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.calls import BadModelOutput, TextModel
from app.models import KIND_LOCATION, Entity, EntityFact, Project
from app.rag.index import search

# Decisions per question, the last one forced to be an answer. Each is a model call.
MAX_STEPS = 6
# A chapter longer than this is opened only in part; search reaches the rest.
READ_CHARS = 60_000
NAMES_PER_CHAPTER = 12

SYSTEM = """You answer questions about one book, using only its text. You do not see the \
book itself. You have its table of contents below and three tools:

- card: what an earlier reading of the book recorded about one character or place: who \
they are, the people around them (servants, family, friends, enemies), and the chapters \
they appear in. The quickest way to learn a name the question does not give ("her maid", \
"his brother") and where to look. A card is not a source: confirm what it says in the \
chapters and cite those. Only the names listed in the table of contents have cards; \
for anyone else, search.
- search: finds short passages by meaning and by words. Good for a name, an object, a \
particular moment.
- read: opens a whole chapter by its number. Use it when the answer depends on events, \
motives or how something developed, or when the passages found are fragments that do \
not show the whole picture.

Reply with one JSON object and nothing else, one of:
{{"action": "card", "name": "..."}}
{{"action": "search", "query": "..."}}
{{"action": "read", "chapter": 3}}
{{"action": "answer", "found": true, "answer": "... [1] ... [3]", \
"citations": [{{"source": 1, "quote": "..."}}]}}

Rules:
{scope}- If the question names a chapter ("chapter 3", "this chapter"), read that chapter. \
"This chapter" is the one marked "open now".
- Otherwise everything in the table of contents is in scope. Do not settle for fragments when the question \
needs more: read the chapters they come from.
- Each step makes the reader wait several seconds. When the sources you have already \
answer the question, answer at once; take a step only for what is still missing.
- When the question is about someone tied to a character with a card, and the sources do \
not name them yet, look at that card.
- Answer about exactly the one the question names. Passages about someone else (an \
ancestor, a namesake, a relative, an earlier holder of the title) are not the answer: \
keep looking, and mention them only as an aside.
- What happened to someone in the end (death, fate, where they went, how it ended) is told \
where they appear last: read the last chapters with them in the table of contents and the \
one after, not the first ones.
- Start the answer with the direct answer in one sentence. When the book only implies it, \
say what it shows (where they were last seen, what happened there, who speaks of it after).
- Plan with the table of contents: it lists who and what appears in each chapter. Open \
the chapters where the people, places or things of the question appear; when the question \
is about how something began or developed, start from the earliest of them.
- Names in the question may be misspelt or given in another language: match them to the \
names in the table of contents. Write search queries in the language of the book, as its \
chapter titles and names show it, not in the language of the question.
- Answer from what the text shows, even when it does not use the words of the question: \
describe the scene or the facts that bear on it. Say the book does not answer only when \
nothing you have read bears on the question, and never before reading at least one \
chapter likely to hold the answer.
- Earlier answers in this conversation may be wrong: check them against the sources.
- You have {steps} replies in all for this question, so choose what to open carefully.
- Answer only from the numbered sources you have gathered. Do not use anything you \
know about this or any other book.
- If the sources do not answer the question, say plainly that the book does not \
answer it, and set "found" to false. Do not guess.
- Answer in the language of the question. Be complete but to the point.
- After each statement put the number of the source it comes from, like [2]. For every \
source you relied on, give one short quote copied from it character for character \
(under 200 characters).

Table of contents:

{contents}"""

SCOPE_RULE = """- This conversation is limited to some chapters of the book: only they are in \
the table of contents, and search and read reach nothing else. Answer from them alone; \
if they do not answer the question, say so.
"""

FORCE_ANSWER = "No more tools: answer now from the sources you have."
EMPTY_ANSWER = (
    'Your answer was empty. Reply {"action": "answer", ...} with the answer written out, or '
    "say plainly that the sources do not answer the question."
)
READ_FIRST = (
    "You have not read any chapter yet, so you cannot know the book does not answer. "
    "Earlier answers in this conversation may be wrong too. Pick from the table of contents "
    'the chapter most likely to hold the answer and reply {"action": "read", "chapter": N}.'
)


class Citation(BaseModel):
    source: int
    quote: str = ""


class Decision(BaseModel):
    action: Literal["card", "search", "read", "answer"] = "answer"
    name: str = ""
    query: str = ""
    chapter: int = 0
    found: bool = True
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)


class State(TypedDict):
    question: str
    # Numbered material gathered so far: [1] is sources[0]. Search hits and whole chapters.
    sources: list[Document]
    # What the agent has done, so the next decision knows what not to repeat.
    log: list[str]
    # Cards looked at: background for planning, never cited.
    notes: list[str]
    steps: int
    decision: Decision | None


def contents(
    session: Session, project: Project, open_chapter_id: str = "", scope: list[str] | None = None
) -> str:
    """The table of contents the agent plans with: number, title, size, and who and
    where appears in each chapter, from the cards when they have been made. With a
    `scope` only those chapters are listed, under their numbers in the book."""
    names: dict[str, dict[str, list[str]]] = {}
    rows = session.execute(
        select(EntityFact.chapter_id, Entity.kind, Entity.name)
        .join(Entity, EntityFact.entity_id == Entity.id)
        .where(Entity.project_id == project.id)
        .distinct()
        .order_by(Entity.name)
    ).all()
    # Main characters first: a crowded chapter shows only some names, and the alphabet
    # must not hide the hero there (a name late in it was cut off in every busy chapter).
    weight: dict[str, int] = {}
    for _, _, name in rows:
        weight[name] = weight.get(name, 0) + 1
    for chapter_id, kind, name in sorted(rows, key=lambda r: (-weight[r[2]], r[2])):
        names.setdefault(chapter_id, {}).setdefault(kind, []).append(name)
    lines = []
    for number, chapter in enumerate(project.chapters, 1):
        if scope and chapter.id not in scope:
            continue
        line = f"{number}. {chapter.title or '(untitled)'} — {len(chapter.text):,} characters"
        found = names.get(chapter.id, {})
        people = [n for k, ns in found.items() if k != KIND_LOCATION for n in ns]
        places = found.get(KIND_LOCATION, [])
        if people:
            line += f"; characters: {', '.join(people[:NAMES_PER_CHAPTER])}"
        if places:
            line += f"; places: {', '.join(places[:NAMES_PER_CHAPTER])}"
        if chapter.id == open_chapter_id:
            line += " (open now)"
        lines.append(line)
    return "\n".join(lines)


def passage_document(chapter_id: str, title: str, paragraph: int, text: str) -> Document:
    return Document(
        page_content=text,
        metadata={"chapter_id": chapter_id, "chapter_title": title, "paragraph": paragraph},
    )


def _config(config: RunnableConfig) -> tuple[Session, TextModel, Project, dict]:
    c = config["configurable"]
    return c["session"], c["model"], c["project"], c


def _sources_text(sources: list[Document]) -> str:
    return "\n\n".join(
        f"[{n}] ({doc.metadata['chapter_title'] or '—'}"
        + (", whole chapter" if doc.metadata.get("whole") else ", passage")
        + f")\n{doc.page_content}"
        for n, doc in enumerate(sources, 1)
    )


def decide(state: State, config: RunnableConfig) -> dict:
    session, model, project, c = _config(config)
    steps = state["steps"] + 1
    scope = c.get("scope") or []
    system = SYSTEM.format(
        steps=MAX_STEPS,
        scope=SCOPE_RULE if scope else "",
        contents=contents(session, project, c.get("open_chapter_id", ""), scope),
    )
    notes = state.get("notes") or []
    request = (
        f"Question: {state['question']}\n\n"
        f"Done so far:\n"
        + "\n".join(f"- {line}" for line in state["log"])
        + "\n\n"
        + ("Cards (not sources, do not cite):\n\n" + "\n\n".join(notes) + "\n\n" if notes else "")
        + f"Sources:\n\n{_sources_text(state['sources']) or '(none yet)'}"
    )
    if c.get("language_note"):
        request += f"\n\n{c['language_note']}"
    if steps >= MAX_STEPS:
        request += f"\n\n{FORCE_ANSWER}"
    messages: list[BaseMessage] = [SystemMessage(system), *c.get("history", [])]
    messages.append(HumanMessage(request))
    decision = _ask(model, messages)
    read_any = any(d.metadata.get("whole") for d in state["sources"])
    if decision.action == "answer" and not decision.found and not read_any and steps < MAX_STEPS:
        # "The book does not say" from a few passages is too quick (and an earlier answer in
        # the history tempts to repeat it): one more turn, with a chapter opened first.
        decision = _again(model, messages, decision, READ_FIRST)
    if decision.action != "answer" and steps >= MAX_STEPS:
        # Out of steps but still wanting to look: one firm request to answer now.
        decision = _again(model, messages, decision, FORCE_ANSWER)
    if decision.action == "answer" and not decision.answer.strip():
        decision = _again(model, messages, decision, EMPTY_ANSWER)
    if decision.action != "answer" and steps >= MAX_STEPS:
        raise BadModelOutput("the agent did not answer within its steps")
    if decision.action == "answer" and not decision.answer.strip():
        raise BadModelOutput("empty answer")
    return {"decision": decision, "steps": steps}


def _ask(model: TextModel, messages: list[BaseMessage]) -> Decision:
    """One decision; a reply that is still not valid JSON after the repair inside
    `invoke_json` gets one fresh try, since such failures are usually one-off."""
    try:
        return model.invoke_json("chat", messages, Decision)
    except BadModelOutput:
        return model.invoke_json("chat", messages, Decision)


def _again(
    model: TextModel, messages: list[BaseMessage], decision: Decision, request: str
) -> Decision:
    messages += [AIMessage(decision.model_dump_json()), HumanMessage(request)]
    return _ask(model, messages)


def search_tool(state: State, config: RunnableConfig) -> dict:
    session, _, project, c = _config(config)
    query = state["decision"].query.strip()
    sources = list(state["sources"])
    seen = {(d.metadata["chapter_id"], d.metadata["paragraph"]) for d in sources}
    whole = {d.metadata["chapter_id"] for d in sources if d.metadata.get("whole")}
    added = []
    found_passages = search(
        session,
        project.id,
        query,
        focus_chapter_id=c.get("open_chapter_id", ""),
        chapter_ids=c.get("scope") or None,
    )
    for p in found_passages:
        if (p.chapter_id, p.paragraph) in seen or p.chapter_id in whole:
            continue  # the agent already has this text
        sources.append(passage_document(p.chapter_id, p.chapter_title, p.paragraph, p.text))
        added.append(len(sources))
    found = f"sources {', '.join(f'[{n}]' for n in added)}" if added else "nothing new"
    return {"sources": sources, "log": [*state["log"], f'searched "{query}": {found}']}


def read_tool(state: State, config: RunnableConfig) -> dict:
    _, _, project, c = _config(config)
    number = state["decision"].chapter
    chapters = project.chapters
    if not 1 <= number <= len(chapters):
        return {"log": [*state["log"], f"read chapter {number}: there is no such chapter"]}
    chapter = chapters[number - 1]
    scope = c.get("scope") or []
    if scope and chapter.id not in scope:
        log = f"read chapter {number}: outside this conversation's chapters"
        return {"log": [*state["log"], log]}
    sources = list(state["sources"])
    for n, doc in enumerate(sources, 1):
        if doc.metadata["chapter_id"] == chapter.id and doc.metadata.get("whole"):
            return {"log": [*state["log"], f"read chapter {number}: already source [{n}]"]}
    text = chapter.text[:READ_CHARS]
    note = "" if len(chapter.text) <= READ_CHARS else " (only its first part; search for the rest)"
    document = passage_document(chapter.id, chapter.title, 0, text)
    document.metadata["whole"] = True
    sources.append(document)
    log = f"read chapter {number}: source [{len(sources)}]{note}"
    return {"sources": sources, "log": [*state["log"], log]}


CARD_FACTS = 30


def find_card(session: Session, project: Project, name: str) -> Entity | None:
    """The card a name points at: exact name or alias first, then a name that starts
    the same way (the question may use another case ending or a misspelling)."""
    wanted = name.strip().casefold()
    if not wanted:
        return None
    cards = session.scalars(select(Entity).where(Entity.project_id == project.id)).all()

    def names(card: Entity) -> list[str]:
        return [n.casefold() for n in [card.name, *card.aliases, *card.pinned_names] if n]

    exact = [c for c in cards if wanted in names(c)]
    if exact:
        return exact[0]

    def similar(a: str, b: str) -> bool:
        """Same word up to a case ending: "Журэі" ~ "Журэя", "Люты" ~ "Люта"."""
        common = len(os.path.commonprefix([a, b]))
        return common >= max(3, min(len(a), len(b)) - 2)

    def words(card: Entity) -> list[str]:  # "князь Цмок" is found by "Цмока" too
        return [w for n in names(card) for w in [n, *n.split()] if len(w) >= 3]

    close = [c for c in cards if any(similar(w, wanted) for w in words(c))]
    return close[0] if close else None


def card_text(project: Project, card: Entity, scope: list[str]) -> str:
    numbers = {c.id: n for n, c in enumerate(project.chapters, 1)}
    titles = {c.id: c.title for c in project.chapters}
    lines = [f"Card: {card.name}" + (f" (also: {', '.join(card.aliases)})" if card.aliases else "")]
    about = card.description.strip() or card.summary.strip()
    if about:
        lines.append(about)
    facts = [
        f for f in card.facts if f.chapter_id in numbers and (not scope or f.chapter_id in scope)
    ]
    facts.sort(key=lambda f: numbers[f.chapter_id])
    where = sorted({numbers[f.chapter_id] for f in facts})
    if where:
        lines.append(f"appears in chapters: {', '.join(map(str, where))}")
    if len(facts) > CARD_FACTS:
        # The whole book, not its first chapters: the end of a story matters as much.
        step = len(facts) / CARD_FACTS
        facts = [facts[int(i * step)] for i in range(CARD_FACTS - 1)] + [facts[-1]]
    for fact in facts:
        n = numbers[fact.chapter_id]
        lines.append(f"- chapter {n} ({titles[fact.chapter_id] or 'untitled'}): {fact.text}")
    if not about and not facts:
        lines.append("(nothing recorded)")
    return "\n".join(lines)


def card_tool(state: State, config: RunnableConfig) -> dict:
    session, _, project, c = _config(config)
    name = state["decision"].name.strip()
    notes = list(state.get("notes") or [])
    card = find_card(session, project, name)
    if card is None:
        log = f'card "{name}": no such card; search the book instead'
    elif any(n.startswith(f"Card: {card.name}") for n in notes):
        log = f'card "{name}": already shown below'
    else:
        notes.append(card_text(project, card, c.get("scope") or []))
        log = f'card "{name}": shown below as "{card.name}"'
    return {"notes": notes, "log": [*state["log"], log]}


def _route(state: State) -> str:
    action = state["decision"].action
    return {"card": "card", "search": "search", "read": "read"}.get(action, END)


def build_graph():
    graph = StateGraph(State)
    graph.add_node("decide", decide)
    graph.add_node("card", card_tool)
    graph.add_node("search", search_tool)
    graph.add_node("read", read_tool)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges("decide", _route, ["card", "search", "read", END])
    graph.add_edge("card", "decide")
    graph.add_edge("search", "decide")
    graph.add_edge("read", "decide")
    return graph.compile()


GRAPH = build_graph()
