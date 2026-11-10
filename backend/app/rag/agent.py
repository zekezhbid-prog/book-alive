"""The book chat as an agent. A model cannot read a whole novel for every question, and a
few search hits are too little to answer from, so the agent gets the table of contents
and two tools: search the book, and open a whole chapter. It decides what to look at
until it has enough, then answers from what it has read.

A LangGraph loop of one decision node and the two tools. Tool calls go through plain
JSON in the reply, as everywhere in the app: not every provider supports tool calling.
"""

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
book itself. You have its table of contents below and two tools:

- search: finds short passages by meaning and by words. Good for a name, an object, a \
particular moment.
- read: opens a whole chapter by its number. Use it when the answer depends on events, \
motives or how something developed, or when the passages found are fragments that do \
not show the whole picture.

Reply with one JSON object and nothing else, one of:
{{"action": "search", "query": "..."}}
{{"action": "read", "chapter": 3}}
{{"action": "answer", "found": true, "answer": "... [1] ... [3]", \
"citations": [{{"source": 1, "quote": "..."}}]}}

Rules:
{scope}- If the question names a chapter ("chapter 3", "this chapter"), read that chapter. \
"This chapter" is the one marked "open now".
- Otherwise everything in the table of contents is in scope. Do not settle for fragments when the question \
needs more: read the chapters they come from.
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
READ_FIRST = (
    "You have not read any chapter yet, so you cannot know the book does not answer. "
    "Earlier answers in this conversation may be wrong too. Pick from the table of contents "
    'the chapter most likely to hold the answer and reply {"action": "read", "chapter": N}.'
)


class Citation(BaseModel):
    source: int
    quote: str = ""


class Decision(BaseModel):
    action: Literal["search", "read", "answer"] = "answer"
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
    for chapter_id, kind, name in rows:
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
    request = (
        f"Question: {state['question']}\n\n"
        f"Done so far:\n" + "\n".join(f"- {line}" for line in state["log"]) + "\n\n"
        f"Sources:\n\n{_sources_text(state['sources']) or '(none yet)'}"
    )
    if steps >= MAX_STEPS:
        request += f"\n\n{FORCE_ANSWER}"
    messages: list[BaseMessage] = [SystemMessage(system), *c.get("history", [])]
    messages.append(HumanMessage(request))
    decision = model.invoke_json("chat", messages, Decision)
    read_any = any(d.metadata.get("whole") for d in state["sources"])
    if decision.action == "answer" and not decision.found and not read_any and steps < MAX_STEPS:
        # "The book does not say" from a few passages is too quick (and an earlier answer in
        # the history tempts to repeat it): one more turn, with a chapter opened first.
        messages += [AIMessage(decision.model_dump_json()), HumanMessage(READ_FIRST)]
        decision = model.invoke_json("chat", messages, Decision)
    if decision.action != "answer" and steps >= MAX_STEPS:
        raise BadModelOutput("the agent did not answer within its steps")
    if decision.action == "answer" and not decision.answer.strip():
        raise BadModelOutput("empty answer")
    return {"decision": decision, "steps": steps}


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


def _route(state: State) -> str:
    action = state["decision"].action
    return {"search": "search", "read": "read"}.get(action, END)


def build_graph():
    graph = StateGraph(State)
    graph.add_node("decide", decide)
    graph.add_node("search", search_tool)
    graph.add_node("read", read_tool)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges("decide", _route, ["search", "read", END])
    graph.add_edge("search", "decide")
    graph.add_edge("read", "decide")
    return graph.compile()


GRAPH = build_graph()
