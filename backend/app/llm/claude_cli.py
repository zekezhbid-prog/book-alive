"""LangChain chat model backed by the local Claude Code CLI.

The CLI authenticates with the user's Claude subscription, so text work costs
nothing beyond the plan. It only works where the CLI is installed and logged in,
that is on the user's own machine, not inside a hosted container.
"""

import json
import shutil
import subprocess
import tempfile
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

CLI_MODELS = ["sonnet", "opus", "haiku"]


class ClaudeCLIError(RuntimeError):
    pass


def cli_path() -> str | None:
    return shutil.which("claude")


class ChatClaudeCLI(BaseChatModel):
    model: str = "sonnet"
    timeout: int = 600

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        executable = cli_path()
        if not executable:
            raise ClaudeCLIError("Claude Code CLI is not installed on this machine")
        system = "\n\n".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        turns = [m for m in messages if not isinstance(m, SystemMessage)]
        if len(turns) == 1:
            prompt = str(turns[0].content)
        else:
            prompt = "\n\n".join(f"[{m.type}]\n{m.content}" for m in turns)

        command = [executable, "-p", "--output-format", "json", "--model", self.model]
        # No tools and no project settings: this is plain text completion.
        command += ["--tools", "", "--setting-sources", "", "--no-session-persistence"]
        if system:
            command += ["--system-prompt", system]
        # An empty working directory keeps the CLI from picking up any CLAUDE.md.
        with tempfile.TemporaryDirectory() as workdir:
            try:
                done = subprocess.run(
                    command,
                    check=False,  # failures are reported in the JSON payload
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=workdir,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise ClaudeCLIError(f"Claude CLI timed out after {self.timeout}s") from exc
        try:
            payload = json.loads(done.stdout)
        except json.JSONDecodeError as exc:
            detail = (done.stderr or done.stdout).strip()[:500]
            raise ClaudeCLIError(f"Claude CLI failed: {detail}") from exc
        if payload.get("is_error"):
            raise ClaudeCLIError(str(payload.get("result", "Claude CLI returned an error"))[:500])

        usage = payload.get("usage") or {}
        input_tokens = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
        output_tokens = usage.get("output_tokens", 0)
        message = AIMessage(
            content=payload.get("result", ""),
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
