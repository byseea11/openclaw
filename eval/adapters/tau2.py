"""tau2-bench adapter and bridge helpers backed by OpenClaw Gateway."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from eval.base import InputStep, ToolAdapter, ToolAdapterResult
from eval.openclaw_client import OpenClawEvalClient, OpenClawEvalResponse

SYSTEM_PROMPT = """
You are a policy-following task agent.

Rules:
1. Follow the provided domain policy first.
2. Use only the provided tools.
3. If a tool fails, adapt to the error instead of hallucinating success.
4. Ask for clarification when information is missing.
5. Each turn should either answer the user or make tool calls.
""".strip()

TAU2_SOLO_ADDITIONAL_RULES = """
Solo-mode rules:
1. The ticket describes the concrete task you must complete.
2. Prefer solving the ticket directly with the available tools.
3. Use `transfer_to_human_agents` only when the task truly cannot be completed with the available tools or the policy explicitly requires escalation.
4. Do not transfer if you can complete the request yourself.
5. After completing the task, stop cleanly.
""".strip()


class Tau2Adapter(ToolAdapter):
    """Tool-style adapter for tau2 tasks and observations."""

    benchmark_name = "tau2"
    message_channel = "tau2"

    def load_dataset(self, input_path: str | Path) -> list[Any]:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"tau2 input file not found: {path}")
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            raise ValueError("tau2 JSON input must be a list")
        raise ValueError("tau2 adapter only supports JSON task dumps when using load_dataset().")

    def make_sample_id(self, sample: Any) -> str:
        if isinstance(sample, dict):
            for key in ("task_id", "id", "name"):
                value = str(sample.get(key) or "").strip()
                if value:
                    return value
        return str(getattr(sample, "task_id", None) or getattr(sample, "id", None) or "task")

    def init_runtime(self, sample: Any) -> dict[str, Any]:
        return {"sample_id": self.make_sample_id(sample)}

    def build_initial_input(self, sample: Any, runtime: Any) -> InputStep:
        observation = ""
        tools: list[dict[str, Any]] | None = None
        if isinstance(sample, dict):
            observation = str(
                sample.get("initial_observation")
                or sample.get("instruction")
                or sample.get("user_goal")
                or ""
            ).strip()
            tools = sample.get("tools")
        return InputStep(
            kind="observation",
            instructions=SYSTEM_PROMPT,
            input_items=[{"type": "message", "role": "user", "content": observation or "Begin solving the task."}],
            tools=tools,
            metadata={"runtime": runtime},
        )

    def handle_response(
        self,
        sample: Any,
        runtime: Any,
        response: OpenClawEvalResponse,
    ) -> ToolAdapterResult:
        if response.tool_calls:
            return ToolAdapterResult(
                done=False,
                result={
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "raw_arguments": call.raw_arguments,
                        }
                        for call in response.tool_calls
                    ]
                },
            )
        return ToolAdapterResult(
            done=True,
            result={
                "sample_id": self.make_sample_id(sample),
                "final_text": response.text,
                "response_id": response.response_id,
                "latency_ms": response.latency_ms,
                "raw": response.raw_payload,
            },
        )

    @staticmethod
    def build_tool_result_step(call_id: str, output: str) -> InputStep:
        return InputStep(
            kind="tool_result",
            input_items=[
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                }
            ],
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_tau2_imports() -> None:
    tau2_src = _repo_root() / "tau2-bench" / "src"
    for path in (_repo_root(), tau2_src):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


class OpenClawTau2State(BaseModel):
    """Conversation state for the OpenClaw tau2 bridge."""

    session_key: str
    previous_response_id: str | None = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)


def _tau2_tool_schema(tool: Any) -> dict[str, Any]:
    schema = dict(tool.openai_schema)
    if schema.get("type") != "function":
        return schema

    function = dict(schema.get("function") or {})
    return {
        "type": "function",
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "parameters": function.get("parameters") or {"type": "object", "properties": {}},
        "strict": True,
    }


def make_openclaw_tau2_agent_factory(
    *,
    gateway_base_url: str = "http://127.0.0.1:18789",
    gateway_token: str | None = None,
    openclaw_agent_id: str = "main",
    model_override: str | None = None,
) -> Callable[..., Any]:
    """Return a tau2 agent factory using the unified eval client."""

    _ensure_tau2_imports()
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage

    class OpenClawTau2Agent(HalfDuplexAgent[OpenClawTau2State]):
        def __init__(self, tools, domain_policy, llm, llm_args=None):
            super().__init__(tools=tools, domain_policy=domain_policy)
            self.llm = llm
            self.llm_args = llm_args or {}
            self.client = OpenClawEvalClient(
                gateway_base_url,
                agent=openclaw_agent_id,
                token=gateway_token,
                model_override=model_override,
                timeout_seconds=float(self.llm_args.get("timeout_seconds", 180.0)),
            )

        @property
        def system_prompt(self) -> str:
            return f"{SYSTEM_PROMPT}\n\n<policy>\n{self.domain_policy}\n</policy>"

        def get_init_state(self, message_history=None):
            return OpenClawTau2State(session_key=f"tau2-openclaw:{uuid.uuid4().hex[:12]}")

        def generate_next_message(self, message, state):
            if isinstance(message, UserMessage):
                input_items = [{"type": "message", "role": "user", "content": message.content or ""}]
            elif isinstance(message, ToolMessage):
                input_items = [
                    {
                        "type": "function_call_output",
                        "call_id": message.id,
                        "output": message.content or "",
                    }
                ]
            else:
                raise TypeError(f"Unsupported tau2 input message: {type(message)!r}")

            response = self.client.send(
                session_key=state.session_key,
                message_channel="tau2",
                input_items=input_items,
                instructions=self.system_prompt,
                tools=[_tau2_tool_schema(tool) for tool in self.tools],
                previous_response_id=state.previous_response_id,
                max_output_tokens=self.llm_args.get("max_tokens"),
            )
            state.previous_response_id = response.response_id
            tool_calls = [
                ToolCall(id=call.id, name=call.name, arguments=call.arguments, requestor="assistant")
                for call in response.tool_calls
            ]
            content = None if tool_calls else (response.text or None)
            assistant = AssistantMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls or None,
                raw_data={"openclaw_response_id": response.response_id},
            )
            return assistant, state

    def factory(tools, domain_policy, llm, llm_args=None, **_kwargs):
        return OpenClawTau2Agent(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=llm_args,
        )

    setattr(factory, "agent_class", OpenClawTau2Agent)
    return factory


def make_openclaw_tau2_solo_agent_factory(
    *,
    gateway_base_url: str = "http://127.0.0.1:18789",
    gateway_token: str | None = None,
    openclaw_agent_id: str = "main",
    model_override: str | None = None,
) -> Callable[..., Any]:
    """Return a tau2 solo-agent factory using the unified eval client."""

    _ensure_tau2_imports()
    from tau2.agent.llm_agent import LLMSoloAgent
    from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage, UserMessage

    class OpenClawTau2SoloAgent(LLMSoloAgent):
        @classmethod
        def check_valid_task(cls, _task: Any) -> bool:
            return True

        def __init__(self, tools, domain_policy, task, llm, llm_args=None):
            super().__init__(
                tools=tools,
                domain_policy=domain_policy,
                task=task,
                llm=llm,
                llm_args=llm_args,
            )
            self._done_enabled = False
            self._transfer_enabled = False
            self.client = OpenClawEvalClient(
                gateway_base_url,
                agent=openclaw_agent_id,
                token=gateway_token,
                model_override=model_override,
                timeout_seconds=float((llm_args or {}).get("timeout_seconds", 180.0)),
            )

        def get_init_state(self, message_history=None):
            return OpenClawTau2State(session_key=f"tau2-openclaw-solo:{uuid.uuid4().hex[:12]}")

        def _visible_tools(self) -> list[Any]:
            visible: list[Any] = []
            for tool in self.tools:
                name = getattr(tool, "name", "")
                if name == self.STOP_FUNCTION_NAME and not self._done_enabled:
                    continue
                if name == self.TRANSFER_TOOL_NAME and not self._transfer_enabled:
                    continue
                visible.append(tool)
            return visible

        def generate_next_message(self, message, state):
            if isinstance(message, UserMessage):
                raise ValueError("OpenClawTau2SoloAgent does not support user messages.")
            if isinstance(message, MultiToolMessage):
                self._done_enabled = True
                self._transfer_enabled = True
                input_items = [
                    {
                        "type": "function_call_output",
                        "call_id": tool_message.id,
                        "output": tool_message.content or "",
                    }
                    for tool_message in message.tool_messages
                ]
            elif isinstance(message, ToolMessage):
                self._done_enabled = True
                self._transfer_enabled = True
                input_items = [
                    {
                        "type": "function_call_output",
                        "call_id": message.id,
                        "output": message.content or "",
                    }
                ]
            elif message is None:
                input_items = [
                    {
                        "type": "message",
                        "role": "user",
                        "content": self.task.ticket or "Solve the ticket using the available tools.",
                    }
                ]
            else:
                raise TypeError(f"Unsupported tau2 solo input message: {type(message)!r}")

            response = self.client.send(
                session_key=state.session_key,
                message_channel="tau2",
                input_items=input_items,
                instructions=f"{LLMSoloAgent.system_prompt.fget(self)}\n\n{TAU2_SOLO_ADDITIONAL_RULES}",
                tools=[_tau2_tool_schema(tool) for tool in self._visible_tools()],
                tool_choice="required",
                previous_response_id=state.previous_response_id,
            )
            state.previous_response_id = response.response_id
            tool_calls = [
                ToolCall(id=call.id, name=call.name, arguments=call.arguments, requestor="assistant")
                for call in response.tool_calls
            ]
            stop_call = next((call for call in tool_calls if call.name == self.STOP_FUNCTION_NAME), None)
            if stop_call is not None:
                assistant_message = AssistantMessage(
                    role="assistant",
                    content=self.STOP_TOKEN,
                    tool_calls=None,
                    raw_data={"openclaw_response_id": response.response_id},
                )
                return assistant_message, state
            return (
                AssistantMessage(
                    role="assistant",
                    content=None if tool_calls else (response.text or None),
                    tool_calls=tool_calls or None,
                    raw_data={"openclaw_response_id": response.response_id},
                ),
                state,
            )

    def factory(tools, domain_policy, task, llm, llm_args=None, **_kwargs):
        return OpenClawTau2SoloAgent(
            tools=tools,
            domain_policy=domain_policy,
            task=task,
            llm=llm,
            llm_args=llm_args,
        )

    setattr(factory, "agent_class", OpenClawTau2SoloAgent)
    return factory
