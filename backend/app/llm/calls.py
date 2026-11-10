"""Calling the configured text model, with every call written to the usage journal."""

import json
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db import release_connection
from app.llm import prefs, registry
from app.models import Connection, UsageEvent

log = logging.getLogger(__name__)


class ModelNotConfigured(RuntimeError):
    pass


class BadModelOutput(RuntimeError):
    pass


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
        self.engine = session.get_bind()
        self.project_id = project_id
        self.connection_name = connection.name
        self.request_overhead = 0  # tokens the connection adds to every request on its own
        self.model_name = model_name
        self.llm: BaseChatModel = registry.chat_model(connection, model_name)

    def invoke(self, operation: str, messages: list[BaseMessage]) -> str:
        release_connection(self.session)  # nothing held while the model answers
        answer: AIMessage = self.llm.invoke(messages)
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
                )
            )
            journal.commit()
        return answer.content if isinstance(answer.content, str) else str(answer.content)

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
