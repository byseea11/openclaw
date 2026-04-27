"""tau2-bench adapter that uses nanobot's provider stack for agent decisions."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

try:
    from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
    from tau2.data_model.message import (
        AssistantMessage,
        Message,
        MultiToolMessage,
        SystemMessage,
        ToolCall,
        ToolMessage,
        UserMessage,
    )
    from tau2.environment.tool import Tool
except ImportError as exc:  # pragma: no cover - handled at runtime by the runner script
    raise ImportError(
        "tau2_adapter requires tau2-bench and its Python dependencies. "
        "Add tau2-bench/src to PYTHONPATH and install tau2-bench's environment "
        f"first. Original import error: {exc}"
    ) from exc


AGENT_INSTRUCTION = """
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Use only the provided tools.
""".strip()

SYSTEM_PROMPT = """
<instructions>
{agent_instruction}
</instructions>
<policy>
{domain_policy}
</policy>
""".strip()


class NanobotTau2State(BaseModel):
    """Conversation state used by the tau2 adapter."""

    session_key: str
    active_messages: list[dict[str, Any]] = Field(default_factory=list)
    turn_save_start: int = 0


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            converted.append({"role": "system", "content": message.content})
            continue
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": message.content})
            continue
        if isinstance(message, AssistantMessage):
            tool_calls = None
            if message.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in message.tool_calls
                ]
            converted.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": tool_calls,
                }
            )
            continue
        if isinstance(message, ToolMessage):
            converted.append(
                {
                    "role": "tool",
                    "content": message.content,
                    "tool_call_id": message.id,
                }
            )
            continue
        raise TypeError(f"Unsupported tau2 message type: {type(message)!r}")
    return converted


def _to_tool_calls(tool_calls: list[Any]) -> list[ToolCall]:
    converted: list[ToolCall] = []
    for tool_call in tool_calls:
        converted.append(
            ToolCall(
                id=tool_call.id or str(uuid.uuid4()),
                name=tool_call.name,
                arguments=tool_call.arguments,
                requestor="assistant",
            )
        )
    return converted


def _build_assistant_message(response: Any) -> AssistantMessage:
    tool_calls = _to_tool_calls(response.tool_calls)
    content = response.content
    if tool_calls:
        content = None
    elif isinstance(content, str) and not content.strip():
        content = None
    return AssistantMessage(
        role="assistant",
        content=content,
        tool_calls=tool_calls or None,
        usage=response.usage or None,
        raw_data={
            "finish_reason": response.finish_reason,
            "reasoning_content": response.reasoning_content,
        },
    )


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _load_agent_runtime(
    *,
    config_path: str | Path | None,
    model: str,
    workspace: str | Path | None,
    memory_context_mode: str | None,
):
    import httpx
    from openai import AsyncOpenAI

    from nanobot.config import load_config
    from nanobot.nanobot import _make_provider

    resolved = Path(config_path).expanduser().resolve() if config_path else None
    config = load_config(resolved)
    config.agents.defaults.model = model
    if workspace is not None:
        config.agents.defaults.workspace = str(Path(workspace).expanduser().resolve())
    if memory_context_mode:
        config.agents.defaults.memory_context_mode = memory_context_mode

    provider = _make_provider(config)
    # For eval runs, force OpenAI-compatible providers to ignore system proxy
    # settings so DeepSeek and similar endpoints connect directly.
    if hasattr(provider, "_client") and getattr(provider, "api_base", None):
        provider._client = AsyncOpenAI(
            api_key=getattr(provider, "api_key", None) or "no-key",
            base_url=getattr(provider, "api_base", None),
            default_headers=getattr(getattr(provider, "_client", None), "default_headers", None),
            http_client=httpx.AsyncClient(trust_env=False),
        )
    return config, provider


class NanobotTau2Agent(HalfDuplexAgent[NanobotTau2State]):
    """tau2 text agent that reuses nanobot's runtime context and memory stack."""

    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        llm: str,
        llm_args: dict[str, Any] | None = None,
        *,
        config_path: str | Path | None = None,
        workspace: str | Path | None = None,
        memory_context_mode: str | None = None,
    ):
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.memory import MemoryConsolidator
        from nanobot.session.manager import SessionManager

        super().__init__(tools=tools, domain_policy=domain_policy)
        self.llm = llm
        self.llm_args = llm_args or {}
        self.config, self.provider = _load_agent_runtime(
            config_path=config_path,
            model=llm,
            workspace=workspace,
            memory_context_mode=memory_context_mode,
        )
        defaults = self.config.agents.defaults
        self.workspace = self.config.workspace_path
        self.context = ContextBuilder(
            self.workspace,
            timezone=defaults.timezone,
            memory_context_mode=defaults.memory_context_mode,
        )
        self.sessions = SessionManager(self.workspace)
        self.max_tool_result_chars = defaults.max_tool_result_chars
        self.max_completion_tokens = (
            int(self.llm_args.get("max_tokens"))
            if self.llm_args.get("max_tokens") is not None
            else defaults.max_tokens
        )
        self.memory_consolidator = MemoryConsolidator(
            workspace=self.workspace,
            provider=self.provider,
            model=self.llm,
            sessions=self.sessions,
            context_window_tokens=defaults.context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=lambda: [tool.openai_schema for tool in self.tools],
            max_completion_tokens=self.max_completion_tokens,
        )

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy,
            agent_instruction=AGENT_INSTRUCTION,
        )

    def get_init_state(
        self, message_history: list[Message] | None = None
    ) -> NanobotTau2State:
        session_key = f"tau2:{uuid.uuid4().hex[:12]}"
        state = NanobotTau2State(session_key=session_key)
        if message_history:
            session = self.sessions.get_or_create(session_key)
            self._seed_session_from_history(session, message_history)
            self.sessions.save(session)
        return state

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: NanobotTau2State
    ) -> tuple[AssistantMessage, NanobotTau2State]:
        if isinstance(message, UserMessage) and message.is_audio:
            raise ValueError("NanobotTau2Agent supports text-only tau2 evaluation.")

        session = self.sessions.get_or_create(state.session_key)
        if isinstance(message, UserMessage):
            asyncio.run(self.memory_consolidator.maybe_consolidate_by_tokens(session))
            history = session.get_live_context(max_messages=0)
            state.active_messages = self.context.build_messages(
                history=history,
                current_message=message.content or "",
                channel="tau2",
                chat_id=state.session_key.split(":", 1)[1],
            )
            state.turn_save_start = 1 + len(history)
            state.active_messages = self._merge_system_prompt(state.active_messages)
        else:
            if not state.active_messages:
                raise RuntimeError(
                    "Received tool results without an active user turn in NanobotTau2Agent."
                )
            tool_messages = (
                list(message.tool_messages)
                if isinstance(message, MultiToolMessage)
                else [message]
            )
            for tool_message in tool_messages:
                state.active_messages.append(
                    self._tool_message_dict(tool_message, state.active_messages, state.session_key)
                )

        response = self._call_provider(state.active_messages)
        assistant_message = _build_assistant_message(response)
        state.active_messages.append(self._assistant_message_dict(response))
        if not assistant_message.tool_calls:
            self._finalize_turn(state, session)
        return assistant_message, state

    def _call_provider(self, messages: list[dict[str, Any]]):
        provider_kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": [tool.openai_schema for tool in self.tools],
            "model": self.llm,
        }
        for key in (
            "max_tokens",
            "temperature",
            "reasoning_effort",
            "tool_choice",
            "retry_mode",
        ):
            if key in self.llm_args:
                provider_kwargs[key] = self.llm_args[key]

        try:
            response = asyncio.run(self.provider.chat_with_retry(**provider_kwargs))
        except RuntimeError as exc:
            raise RuntimeError(
                "NanobotTau2Agent expected to run in a synchronous tau2 context."
            ) from exc

        if response.finish_reason == "error":
            raise RuntimeError(response.content or "Unknown provider error")
        return response

    def _merge_system_prompt(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return [{"role": "system", "content": self.system_prompt}]
        merged = list(messages)
        first = dict(merged[0])
        if first.get("role") != "system":
            merged.insert(0, {"role": "system", "content": self.system_prompt})
            return merged
        existing = str(first.get("content") or "").strip()
        first["content"] = (
            f"{self.system_prompt}\n\n---\n\n{existing}" if existing else self.system_prompt
        )
        merged[0] = first
        return merged

    @staticmethod
    def _assistant_message_dict(response: Any) -> dict[str, Any]:
        tool_calls = [
            {
                "id": tool_call.id or str(uuid.uuid4()),
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                },
            }
            for tool_call in response.tool_calls
        ]
        content = response.content
        if tool_calls and (content is None or not str(content).strip()):
            content = None
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls or None,
        }

    def _tool_message_dict(
        self,
        message: ToolMessage,
        active_messages: list[dict[str, Any]],
        session_key: str,
    ) -> dict[str, Any]:
        from nanobot.utils.helpers import maybe_persist_tool_result

        name = self._lookup_tool_name(active_messages, message.id)
        content = message.content or ""
        if message.error and content and not content.lower().startswith("error"):
            content = f"Error: {content}"
        content = maybe_persist_tool_result(
            self.workspace,
            session_key,
            message.id,
            content,
            max_chars=self.max_tool_result_chars,
        )
        return {
            "role": "tool",
            "tool_call_id": message.id,
            "name": name,
            "content": content,
        }

    @staticmethod
    def _lookup_tool_name(messages: list[dict[str, Any]], tool_call_id: str) -> str:
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            for tool_call in message.get("tool_calls") or []:
                if tool_call.get("id") == tool_call_id:
                    return ((tool_call.get("function") or {}).get("name")) or "tool"
        return "tool"

    def _seed_session_from_history(self, session: Any, history: list[Message]) -> None:
        for message in history:
            if isinstance(message, SystemMessage):
                continue
            if isinstance(message, MultiToolMessage):
                for item in message.tool_messages:
                    session.messages.append(self._tool_message_dict(item, session.messages, session.key))
                continue
            converted = _to_openai_messages([message])[0]
            session.messages.append(converted)

    def _finalize_turn(self, state: NanobotTau2State, session: Any) -> None:
        from datetime import datetime

        from nanobot.agent.context import ContextBuilder
        from nanobot.utils.helpers import truncate_text

        for message in state.active_messages[state.turn_save_start :]:
            entry = dict(message)
            role = entry.get("role")
            content = entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue
            if role == "tool" and isinstance(content, str) and len(content) > self.max_tool_result_chars:
                entry["content"] = truncate_text(content, self.max_tool_result_chars)
            elif role == "user" and isinstance(content, str):
                if content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()
        self.sessions.save(session)
        asyncio.run(self.memory_consolidator.maybe_consolidate_by_tokens(session))
        state.active_messages = []
        state.turn_save_start = 0


def make_nanobot_tau2_agent_factory(
    *,
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
    memory_context_mode: str | None = None,
) -> Callable[..., NanobotTau2Agent]:
    """Return a tau2 agent factory wired to a specific nanobot config."""

    def _factory(tools, domain_policy, **kwargs):
        return NanobotTau2Agent(
            tools=tools,
            domain_policy=domain_policy,
            llm=kwargs.get("llm"),
            llm_args=kwargs.get("llm_args"),
            config_path=config_path,
            workspace=workspace,
            memory_context_mode=memory_context_mode,
        )

    return _factory


__all__ = [
    "NanobotTau2Agent",
    "NanobotTau2State",
    "make_nanobot_tau2_agent_factory",
]
