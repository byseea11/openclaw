"""tau2-bench adapter backed by OpenClaw Gateway OpenResponses."""
from __future__ import annotations

import uuid
from typing import Any, Callable

from pydantic import BaseModel, Field

try:
    from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
    from tau2.agent.llm_agent import LLMSoloAgent
    from tau2.data_model.message import (
        AssistantMessage,
        Message,
        MultiToolMessage,
        ToolCall,
        ToolMessage,
        UserMessage,
    )
    from tau2.environment.tool import Tool
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "OpenClaw tau2 adapter requires tau2-bench. "
        "Please add tau2-bench/src to PYTHONPATH and install tau2-bench first. "
        f"Original import error: {exc}"
    ) from exc

from eval.openclaw.openresponses_client import OpenClawOpenResponsesClient

SYSTEM_PROMPT = """
你是一个严格遵守 policy 的客服智能体。

规则：
1. 优先遵守提供给你的 domain policy。
2. 需要时调用工具，但不要虚构工具。
3. 如果工具返回错误，基于错误继续修正。
4. 如果信息不足，就向用户澄清。
5. 只输出给用户的话，或一次工具调用。
""".strip()


class OpenClawTau2State(BaseModel):
    """Conversation state for the OpenClaw tau2 adapter."""

    session_key: str
    previous_response_id: str | None = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)


def _tau2_tool_schema(tool: Tool) -> dict[str, Any]:
    schema = dict(tool.openai_schema)
    if schema.get("type") == "function":
        function = dict(schema.get("function") or {})
        function.setdefault("strict", True)
        schema["function"] = function
    return schema


class OpenClawTau2Agent(HalfDuplexAgent[OpenClawTau2State]):
    """tau2 text agent using OpenClaw's client-tool HTTP surface."""

    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        llm: str,
        llm_args: dict[str, Any] | None = None,
        *,
        gateway_base_url: str = "http://127.0.0.1:18789",
        gateway_token: str | None = None,
        openclaw_agent_id: str = "main",
        model_override: str | None = None,
    ):
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.llm = llm
        self.llm_args = llm_args or {}
        self.client = OpenClawOpenResponsesClient(
            base_url=gateway_base_url,
            token=gateway_token,
            agent_id=openclaw_agent_id,
            model="openclaw",
            model_override=model_override,
            message_channel="tau2",
            timeout_seconds=float(self.llm_args.get("timeout_seconds", 180.0)),
        )

    @property
    def system_prompt(self) -> str:
        return f"{SYSTEM_PROMPT}\n\n<policy>\n{self.domain_policy}\n</policy>"

    def get_init_state(self, message_history: list[Message] | None = None) -> OpenClawTau2State:
        transcript: list[dict[str, Any]] = []
        if message_history:
            for message in message_history:
                if isinstance(message, UserMessage) and message.content:
                    transcript.append({"role": "user", "content": message.content})
        return OpenClawTau2State(
            session_key=f"tau2-openclaw:{uuid.uuid4().hex[:12]}",
            transcript=transcript,
        )

    def generate_next_message(
        self,
        message: ValidAgentInputMessage,
        state: OpenClawTau2State,
    ) -> tuple[AssistantMessage, OpenClawTau2State]:
        if isinstance(message, UserMessage):
            if message.is_audio:
                raise ValueError("OpenClawTau2Agent 目前只支持 text / half-duplex tau2 评测。")
            input_items: list[dict[str, Any]] = [
                {"type": "message", "role": "user", "content": message.content or ""}
            ]
            if message.content:
                state.transcript.append({"role": "user", "content": message.content})
        elif isinstance(message, ToolMessage):
            input_items = [
                {
                    "type": "function_call_output",
                    "call_id": message.id,
                    "output": message.content or "",
                }
            ]
            state.transcript.append({"role": "tool", "id": message.id, "content": message.content or ""})
        else:
            raise TypeError(f"Unsupported tau2 input message: {type(message)!r}")

        response = self.client.create_response(
            input_items=input_items,
            instructions=self.system_prompt,
            tools=[_tau2_tool_schema(tool) for tool in self.tools],
            user=state.session_key,
            previous_response_id=state.previous_response_id,
            max_output_tokens=self.llm_args.get("max_tokens"),
        )
        state.previous_response_id = response.response_id

        tool_calls = [
            ToolCall(
                id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments,
                requestor="assistant",
            )
            for tool_call in response.tool_calls
        ]
        content = response.text or None
        if tool_calls:
            content = None
        assistant = AssistantMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls or None,
            raw_data={"openclaw_response_id": response.response_id},
        )
        state.transcript.append(
            {
                "role": "assistant",
                "content": response.text,
                "tool_calls": [call.model_dump() for call in tool_calls],
            }
        )
        return assistant, state


class OpenClawTau2SoloAgent(LLMSoloAgent):
    """tau2 solo agent backed by OpenClaw's OpenResponses surface."""

    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        task: Any,
        llm: str,
        llm_args: dict[str, Any] | None = None,
        *,
        gateway_base_url: str = "http://127.0.0.1:18789",
        gateway_token: str | None = None,
        openclaw_agent_id: str = "main",
        model_override: str | None = None,
    ):
        super().__init__(
            tools=tools,
            domain_policy=domain_policy,
            task=task,
            llm=llm,
            llm_args=llm_args,
        )
        self.client = OpenClawOpenResponsesClient(
            base_url=gateway_base_url,
            token=gateway_token,
            agent_id=openclaw_agent_id,
            model="openclaw",
            model_override=model_override,
            message_channel="tau2",
            timeout_seconds=float(self.llm_args.get("timeout_seconds", 180.0)),
        )

    def get_init_state(self, message_history: list[Message] | None = None) -> OpenClawTau2State:
        transcript: list[dict[str, Any]] = []
        if message_history:
            for message in message_history:
                if isinstance(message, ToolMessage):
                    transcript.append(
                        {"role": "tool", "id": message.id, "content": message.content or ""}
                    )
                elif isinstance(message, MultiToolMessage):
                    for tool_message in message.tool_messages:
                        transcript.append(
                            {
                                "role": "tool",
                                "id": tool_message.id,
                                "content": tool_message.content or "",
                            }
                        )
        return OpenClawTau2State(
            session_key=f"tau2-openclaw-solo:{uuid.uuid4().hex[:12]}",
            transcript=transcript,
        )

    def generate_next_message(
        self,
        message: ValidAgentInputMessage | None,
        state: OpenClawTau2State,
    ) -> tuple[AssistantMessage, OpenClawTau2State]:
        if isinstance(message, UserMessage):
            raise ValueError("OpenClawTau2SoloAgent does not support user messages.")
        if isinstance(message, MultiToolMessage):
            input_items = [
                {
                    "type": "function_call_output",
                    "call_id": tool_message.id,
                    "output": tool_message.content or "",
                }
                for tool_message in message.tool_messages
            ]
            state.transcript.extend(
                {
                    "role": "tool",
                    "id": tool_message.id,
                    "content": tool_message.content or "",
                }
                for tool_message in message.tool_messages
            )
        elif isinstance(message, ToolMessage):
            input_items = [
                {
                    "type": "function_call_output",
                    "call_id": message.id,
                    "output": message.content or "",
                }
            ]
            state.transcript.append({"role": "tool", "id": message.id, "content": message.content or ""})
        elif message is None:
            input_items = [{"type": "message", "role": "user", "content": "Begin solving the task."}]
        else:
            raise TypeError(f"Unsupported tau2 solo input message: {type(message)!r}")

        response = self.client.create_response(
            input_items=input_items,
            instructions=self.system_prompt,
            tools=[_tau2_tool_schema(tool) for tool in self.tools],
            tool_choice="required",
            user=state.session_key,
            previous_response_id=state.previous_response_id,
            max_output_tokens=self.llm_args.get("max_tokens"),
        )
        state.previous_response_id = response.response_id

        tool_calls = [
            ToolCall(
                id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments,
                requestor="assistant",
            )
            for tool_call in response.tool_calls
        ]
        if not tool_calls:
            raise ValueError("OpenClawTau2SoloAgent only supports tool calls.")

        assistant = AssistantMessage(
            role="assistant",
            content=response.text or None,
            tool_calls=tool_calls,
            raw_data={"openclaw_response_id": response.response_id},
        )
        assistant = self._check_if_stop_toolcall(assistant)
        state.transcript.append(
            {
                "role": "assistant",
                "content": assistant.content,
                "tool_calls": [call.model_dump() for call in tool_calls],
            }
        )
        return assistant, state


def make_openclaw_tau2_agent_factory(
    *,
    gateway_base_url: str = "http://127.0.0.1:18789",
    gateway_token: str | None = None,
    openclaw_agent_id: str = "main",
    model_override: str | None = None,
) -> Callable[..., OpenClawTau2Agent]:
    """Return a tau2 agent factory bound to a specific OpenClaw Gateway."""

    def _factory(
        tools: list[Tool],
        domain_policy: str,
        **kwargs: Any,
    ) -> OpenClawTau2Agent:
        return OpenClawTau2Agent(
            tools=tools,
            domain_policy=domain_policy,
            llm=kwargs.get("llm", "openclaw"),
            llm_args=kwargs.get("llm_args"),
            gateway_base_url=gateway_base_url,
            gateway_token=gateway_token,
            openclaw_agent_id=openclaw_agent_id,
            model_override=model_override,
        )

    return _factory


def make_openclaw_tau2_solo_agent_factory(
    *,
    gateway_base_url: str = "http://127.0.0.1:18789",
    gateway_token: str | None = None,
    openclaw_agent_id: str = "main",
    model_override: str | None = None,
) -> Callable[..., OpenClawTau2SoloAgent]:
    """Return a tau2 solo agent factory bound to a specific OpenClaw Gateway."""

    def _factory(
        tools: list[Tool],
        domain_policy: str,
        **kwargs: Any,
    ) -> OpenClawTau2SoloAgent:
        return OpenClawTau2SoloAgent(
            tools=tools,
            domain_policy=domain_policy,
            task=kwargs["task"],
            llm=kwargs.get("llm", "openclaw"),
            llm_args=kwargs.get("llm_args"),
            gateway_base_url=gateway_base_url,
            gateway_token=gateway_token,
            openclaw_agent_id=openclaw_agent_id,
            model_override=model_override,
        )

    return _factory


__all__ = [
    "OpenClawTau2Agent",
    "OpenClawTau2SoloAgent",
    "OpenClawTau2State",
    "make_openclaw_tau2_agent_factory",
    "make_openclaw_tau2_solo_agent_factory",
]
