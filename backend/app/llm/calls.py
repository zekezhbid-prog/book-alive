"""Calling the configured text model, with every call written to the usage journal."""

import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.llm import registry
from app.models import KIND_CLAUDE_CLI, AppSetting, Connection, UsageEvent


class ModelNotConfigured(RuntimeError):
    pass


class BadModelOutput(RuntimeError):
    pass


class TextModel:
    """The text model chosen in Settings, bound to a project for usage accounting."""

    def __init__(self, session: Session, project_id: str | None):
        connection_id = session.get(AppSetting, "text_connection_id")
        model = session.get(AppSetting, "text_model")
        connection = session.get(Connection, connection_id.value) if connection_id else None
        if connection is None or model is None or not model.value:
            raise ModelNotConfigured("text_model_not_configured")
        self.engine = session.get_bind()
        self.project_id = project_id
        self.connection_name = connection.name
        # The Claude Code CLI wraps every request in its own system prompt.
        self.request_overhead = 5000 if connection.kind == KIND_CLAUDE_CLI else 0
        self.model_name = model.value
        self.llm: BaseChatModel = registry.chat_model(connection, model.value)

    def invoke(self, operation: str, messages: list[BaseMessage]) -> str:
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
        but free models and the subscription CLI do not support it reliably."""
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
            try:
                return _parse(self.invoke(operation, repair), schema)
            except (ValueError, ValidationError) as exc:
                raise BadModelOutput(str(exc)[:300]) from exc


def _parse[T: BaseModel](reply: str, schema: type[T]) -> T:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", reply, re.DOTALL)
    text = fenced.group(1) if fenced else reply
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    return schema.model_validate(json.loads(text[start : end + 1]))


def estimate_tokens(text: str) -> int:
    """Rough count without a tokenizer: Cyrillic runs near 2.5 characters per token,
    Latin near 4. Good enough for a before-you-spend estimate."""
    cyrillic = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    return round(cyrillic / 2.5 + (len(text) - cyrillic) / 4)
