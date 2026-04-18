"""ToolSandbox role backed by OpenClaw Gateway OpenResponses."""
from __future__ import annotations

import uuid
from typing import Any

from tool_sandbox.common.execution_context import RoleType, get_current_context
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.common.tool_conversion import convert_to_openai_tools
from tool_sandbox.roles.base_role import BaseRole
from tool_sandbox.roles.execution_environment import get_messages_to_process

from eval.openclaw.openresponses_client import OpenClawOpenResponsesClient

SYSTEM_PROMPT = """
你是 ToolSandbox 中的工具型智能体。

规则：
1. 只能使用当前给出的工具。
2. 不要假设隐藏状态；需要时通过工具确认。
3. 如果工具失败，基于返回错误继续修正。
4. 如果任务无法完成或信息不足，明确告知用户。
5. 每一轮要么回复用户，要么发起工具调用。
""".strip()


class OpenClawToolSandboxRole(BaseRole):
    """Use OpenClaw's OpenResponses client-tool API inside ToolSandbox."""

    role_type: RoleType = RoleType.AGENT

    def __init__(
        self,
        *,
        gateway_base_url: str = "http://127.0.0.1:18789",
        gateway_token: str | None = None,
        openclaw_agent_id: str = "main",
        model_override: str | None = None,
    ) -> None:
        self.client = OpenClawOpenResponsesClient(
            base_url=gateway_base_url,
            token=gateway_token,
            agent_id=openclaw_agent_id,
            model="openclaw",
            model_override=model_override,
            message_channel="toolsandbox",
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
        if not to_process:
            return
        if to_process[-1].sender == RoleType.SYSTEM:
            return

        system_blocks = [message.content for message in to_process if message.sender == RoleType.SYSTEM and message.content]
        instructions = SYSTEM_PROMPT
        if system_blocks:
            instructions = f"{SYSTEM_PROMPT}\n\n" + "\n\n".join(system_blocks)

        input_items: list[dict[str, Any]] = []
        if to_process[-1].sender == RoleType.USER:
            user_text = "\n\n".join(
                message.content for message in to_process if message.sender == RoleType.USER and message.content
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

        response = self.client.create_response(
            input_items=input_items,
            instructions=instructions,
            tools=convert_to_openai_tools(self.get_available_tools()),
            user=self.session_key,
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
            [
                Message(
                    sender=self.role_type,
                    recipient=RoleType.USER,
                    content=response.text or "",
                )
            ]
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


__all__ = ["OpenClawToolSandboxRole"]
