"""Calling the configured text model, with every call written to the usage journal."""

import json
import logging
import re
import threading

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import release_connection
from app.llm import parallel, prefs, registry
from app.models import Chapter, Connection, UsageEvent, new_id

log = logging.getLogger(__name__)

# Tasks answered without sampling randomness, so the same question gets the same answer.
STEADY_TASKS = {"chat"}
STEADY_TEMPERATURE = 0.0


class ModelNotConfigured(RuntimeError):
    pass


class BadModelOutput(RuntimeError):
    pass


class PrivateTextBlocked(RuntimeError):
    """A request carried the text of a chapter closed to AI; it was not sent."""


# Lines of a private chapter shorter than this are too common to look for ("Тэл.:").
PRIVATE_LINE_MIN = 15


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold().strip()


def private_lines(session: Session, project_id: str | None) -> list[str]:
    """The lines of the project's private chapters, to be sure none of them is ever sent."""
    if not project_id:
        return []
    texts = session.scalars(
        select(Chapter.text).where(Chapter.project_id == project_id, Chapter.private)
    )
    lines = (_squash(line) for text in texts for line in text.split("\n\n"))
    return [line for line in lines if len(line) >= PRIVATE_LINE_MIN]


class TextModel:
    """The text model chosen in Settings, bound to a project for usage accounting."""

    def __init__(self, session: Session, project_id: str | None, task: str | None = None):
        """`task`: one of `prefs.TEXT_TASKS`; its own model when one is chosen, else the main."""
        connection_id = model_name = None
        if task:
            connection_id = prefs.for_project(session, project_id, f"text_{task}_connection_id")
            model_name = prefs.for_project(session, project_id, f"text_{task}_model")
        if not connection_id or not model_name:
            connection_id = prefs.for_project(session, project_id, "text_connection_id")
            model_name = prefs.for_project(session, project_id, "text_model")
        connection = session.get(Connection, connection_id) if connection_id else None
        if connection is None or not model_name:
            raise ModelNotConfigured("text_model_not_configured")
        self.session = session
        # Calls may come from the threads of app.llm.parallel: only this one owns the session.
        self.home = threading.current_thread()
        self.engine = session.get_bind()
        self.project_id = project_id
        self.connection_name = connection.name
        self.request_overhead = 0  # tokens the connection adds to every request on its own
        self.model_name = model_name
        self.connection = connection
        # A model is made for one user action (a run, a question): its calls are one line
        # on the usage page.
        self.action_id = new_id()
        # The chat should answer the same question the same way: no sampling randomness.
        # Some models accept only their default temperature; see `invoke`.
        self.temperature = STEADY_TEMPERATURE if task in STEADY_TASKS else None
        # The last guard for chapters closed to AI: every feature skips them on its own.
        self.private = private_lines(session, project_id)
        self.llm: BaseChatModel = self._build()

    def _build(self) -> BaseChatModel:
        extra = {} if self.temperature is None else {"temperature": self.temperature}
        return registry.chat_model(self.connection, self.model_name, **extra)

    def invoke(self, operation: str, messages: list[BaseMessage]) -> str:
        self._refuse_private(operation, messages)
        here = threading.current_thread()
        if getattr(self, "home", here) is here:
            release_connection(self.session)  # nothing held while the model answers
        with parallel.slots:
            answer = self._ask(messages)
        usage = answer.usage_metadata or {}
        # Its own session: tokens are spent whatever happens to the caller's transaction.
        with Session(self.engine) as journal:
            journal.add(
                UsageEvent(
                    project_id=self.project_id,
                    operation=operation,
                    connection_name=self.connection_name,
                    model=self.model_name,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    action_id=getattr(self, "action_id", None),
                )
            )
            journal.commit()
        return answer.content if isinstance(answer.content, str) else str(answer.content)

    def _refuse_private(self, operation: str, messages: list[BaseMessage]) -> None:
        private = getattr(self, "private", None)
        if not private:
            return
        sent = _squash(" ".join(str(m.content) for m in messages))
        if any(line in sent for line in private):
            log.error("%s: a request with the text of a private chapter was not sent", operation)
            raise PrivateTextBlocked("chapter_private")

    def _ask(self, messages: list[BaseMessage]) -> AIMessage:
        try:
            return self.llm.invoke(messages)
        except Exception as exc:
            if self.temperature is None or "temperature" not in str(exc).lower():
                raise
            # The model refuses a temperature of its own choosing: use its default.
            log.info("%s does not take temperature %s", self.model_name, self.temperature)
            self.temperature = None
            self.llm = self._build()
            return self.llm.invoke(messages)

    def invoke_json[T: BaseModel](
        self, operation: str, messages: list[BaseMessage], schema: type[T]
    ) -> T:
        """Structured output through plain JSON in the reply. Tool calling would be neater,
        but free models do not support it reliably."""
        reply = self.invoke(operation, messages)
        try:
            return _parse(reply, schema)
        except (ValueError, ValidationError) as first_error:
            repair = [
                *messages,
                AIMessage(reply),
                HumanMessage(
                    f"That was not valid: {str(first_error)[:500]}\n"
                    "Reply again with only the corrected JSON object."
                ),
            ]
            again = self.invoke(operation, repair)
            try:
                return _parse(again, schema)
            except (ValueError, ValidationError) as exc:
                # The reply itself, so a failure seen by a user can be understood later.
                log.warning(
                    "%s: %s gave no valid JSON: %r", operation, self.model_name, again[:800]
                )
                raise BadModelOutput(str(exc)[:300]) from exc


def _parse[T: BaseModel](reply: str, schema: type[T]) -> T:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", reply, re.DOTALL)
    text = fenced.group(1) if fenced else reply
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    body = text[start : end + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # Models often leave a comma before a closing bracket: harmless, so forgive it.
        data = json.loads(re.sub(r",(\s*[}\]])", r"\1", body))
    return schema.model_validate(data)


def estimate_tokens(text: str) -> int:
    """Rough count without a tokenizer: Cyrillic runs near 2.5 characters per token,
    Latin near 4. Good enough for a before-you-spend estimate."""
    cyrillic = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    return round(cyrillic / 2.5 + (len(text) - cyrillic) / 4)
