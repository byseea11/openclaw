"""ToolSandbox adapter and role bridge backed by OpenClaw Gateway."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

from eval_old.base import InputStep, ToolAdapter, ToolAdapterResult
from eval_old.openclaw_client import OpenClawEvalClient, OpenClawEvalResponse

SYSTEM_PROMPT = """
You are a ToolSandbox agent.

Rules:
1. Use only the currently provided tools.
2. Do not assume hidden state; confirm it with tools when needed.
3. If a tool fails, adapt to the returned error.
4. If the task cannot be completed, explain why clearly.
5. Each turn should either answer the user or emit tool calls.
""".strip()


class ToolSandboxAdapter(ToolAdapter):
    """Tool-style adapter for ToolSandbox scenarios."""

    benchmark_name = "toolsandbox"
    message_channel = "toolsandbox"

    def load_dataset(self, input_path: str | Path) -> list[Any]:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"ToolSandbox input file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        raise ValueError("ToolSandbox JSON input must be a list.")

    def make_sample_id(self, sample: Any) -> str:
        if isinstance(sample, dict):
            for key in ("scenario_name", "name", "id"):
                value = str(sample.get(key) or "").strip()
                if value:
                    return value
        return str(getattr(sample, "name", None) or getattr(sample, "id", None) or "scenario")

    def init_runtime(self, sample: Any) -> dict[str, Any]:
        return {"sample_id": self.make_sample_id(sample)}

    def build_initial_input(self, sample: Any, runtime: Any) -> InputStep:
        instruction = ""
        tools: list[dict[str, Any]] | None = None
        if isinstance(sample, dict):
            instruction = str(sample.get("instruction") or sample.get("user_instruction") or "").strip()
            tools = sample.get("tools")
        return InputStep(
            kind="observation",
            instructions=SYSTEM_PROMPT,
            input_items=[{"type": "message", "role": "user", "content": instruction}],
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
                "final_answer": response.text,
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


def _ensure_toolsandbox_imports() -> None:
    root = _repo_root()
    toolsandbox_root = root / "ToolSandbox"
    for path in (root, toolsandbox_root):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _to_openresponses_tools(raw_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in raw_tools:
        if tool.get("type") != "function":
            normalized.append(tool)
            continue
        function = dict(tool.get("function") or {})
        normalized.append(
            {
                "type": "function",
                "name": str(function.get("name") or ""),
                "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                "strict": True,
            }
        )
    return normalized


def build_toolsandbox_role(
    *,
    gateway_base_url: str = "http://127.0.0.1:18789",
    gateway_token: str | None = None,
    openclaw_agent_id: str = "main",
    model_override: str | None = None,
) -> type[Any]:
    """Return a ToolSandbox `BaseRole` implementation using the unified eval client."""

    _ensure_toolsandbox_imports()
    from tool_sandbox.common.execution_context import RoleType, get_current_context
    from tool_sandbox.common.message_conversion import Message
    from tool_sandbox.common.tool_conversion import convert_to_openai_tools
    from tool_sandbox.roles.base_role import BaseRole
    from tool_sandbox.roles.execution_environment import get_messages_to_process

    class OpenClawToolSandboxRole(BaseRole):
        role_type = RoleType.AGENT

        def __init__(self) -> None:
            self.client = OpenClawEvalClient(
                gateway_base_url,
                agent=openclaw_agent_id,
                token=gateway_token,
                model_override=model_override,
                timeout_seconds=180.0,
            )
            self.session_key = f"toolsandbox-openclaw:{uuid.uuid4().hex[:12]}"
            self.previous_response_id: str | None = None

        def reset(self) -> None:
            self.session_key = f"toolsandbox-openclaw:{uuid.uuid4().hex[:12]}"
            self.previous_response_id = None

        def respond(self, ending_index: int | None = None) -> None:
            messages = self.get_messages(ending_index=ending_index)
            self.messages_validation(messages=messages)
            messages = self.filter_messages(messages=messages)
            to_process = get_messages_to_process(messages, self.role_type)
            if not to_process or to_process[-1].sender == RoleType.SYSTEM:
                return

            system_blocks = [
                message.content
                for message in to_process
                if message.sender == RoleType.SYSTEM and message.content
            ]
            instructions = SYSTEM_PROMPT if not system_blocks else f"{SYSTEM_PROMPT}\n\n" + "\n\n".join(system_blocks)

            input_items: list[dict[str, Any]] = []
            if to_process[-1].sender == RoleType.USER:
                user_text = "\n\n".join(
                    message.content
                    for message in to_process
                    if message.sender == RoleType.USER and message.content
                ).strip()
                input_items.append({"type": "message", "role": "user", "content": user_text})
            elif to_process[-1].sender == RoleType.EXECUTION_ENVIRONMENT:
                for message in to_process:
                    if message.sender != RoleType.EXECUTION_ENVIRONMENT:
                        continue
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": message.openai_tool_call_id or message.openai_function_name or "",
                            "output": message.content or "",
                        }
                    )
            else:
                raise ValueError(f"Unsupported ToolSandbox sender: {to_process[-1].sender}")

            response = self.client.send(
                session_key=self.session_key,
                message_channel="toolsandbox",
                input_items=input_items,
                instructions=instructions,
                tools=_to_openresponses_tools(convert_to_openai_tools(self.get_available_tools())),
                previous_response_id=self.previous_response_id,
            )
            self.previous_response_id = response.response_id

            if response.tool_calls:
                current_context = get_current_context()
                outgoing: list[Message] = []
                available_tools = set(self.get_available_tools().keys())
                for tool_call in response.tool_calls:
                    if tool_call.name not in available_tools:
                        raise KeyError(
                            f"OpenClaw requested unavailable ToolSandbox tool {tool_call.name!r}; "
                            f"available tools={sorted(available_tools)}"
                        )
                    execution_name = current_context.get_execution_facing_tool_name(tool_call.name)
                    outgoing.append(
                        Message(
                            sender=self.role_type,
                            recipient=RoleType.EXECUTION_ENVIRONMENT,
                            content=self._tool_call_to_python_code(
                                tool_call_id=tool_call.id,
                                execution_facing_tool_name=execution_name,
                                arguments=tool_call.arguments,
                            ),
                            openai_tool_call_id=tool_call.id,
                            openai_function_name=tool_call.name,
                        )
                    )
                self.add_messages(outgoing)
                return

            self.add_messages(
                [Message(sender=self.role_type, recipient=RoleType.USER, content=response.text or "")]
            )

        @staticmethod
        def _tool_call_to_python_code(
            *,
            tool_call_id: str,
            execution_facing_tool_name: str,
            arguments: dict[str, Any],
        ) -> str:
            safe_id = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in tool_call_id) or "call"
            if not (safe_id[0].isalpha() or safe_id[0] == "_"):
                safe_id = f"call_{safe_id}"
            return (
                f"{safe_id}_parameters = {arguments!r}\n"
                f"{safe_id}_response = {execution_facing_tool_name}(**{safe_id}_parameters)\n"
                f"print(repr({safe_id}_response))"
            )

    return OpenClawToolSandboxRole
