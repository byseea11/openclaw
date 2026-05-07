"""OpenClaw Gateway OpenResponses client for benchmark adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OpenClawHostedToolCall:
    """A client tool call emitted by the OpenClaw Gateway."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


@dataclass(frozen=True)
class OpenClawHostedResponse:
    """Parsed non-stream OpenResponses result."""

    response_id: str | None
    text: str
    tool_calls: list[OpenClawHostedToolCall]
    raw_payload: dict[str, Any]


class OpenClawOpenResponsesError(RuntimeError):
    """Raised when the OpenClaw OpenResponses endpoint fails."""


def _normalize_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _extract_text(item: dict[str, Any]) -> str:
    if item.get("type") != "message":
        return ""
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "output_text":
            text = str(part.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _extract_tool_call(item: dict[str, Any]) -> OpenClawHostedToolCall | None:
    if item.get("type") != "function_call":
        return None
    raw_arguments = str(item.get("arguments") or "{}")
    try:
        arguments = json.loads(raw_arguments)
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
    except json.JSONDecodeError:
        arguments = {"_raw": raw_arguments}
    return OpenClawHostedToolCall(
        id=str(item.get("call_id") or item.get("id") or ""),
        name=str(item.get("name") or ""),
        arguments=arguments,
        raw_arguments=raw_arguments,
    )


class OpenClawOpenResponsesClient:
    """Small wrapper around the OpenClaw Gateway `/v1/responses` endpoint."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:18789",
        token: str | None = None,
        agent_id: str | None = None,
        model: str = "openclaw",
        model_override: str | None = None,
        message_channel: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.token = token
        self.agent_id = agent_id
        self.model = model
        self.model_override = model_override
        self.message_channel = message_channel
        self.timeout_seconds = timeout_seconds

    def create_response(
        self,
        *,
        input_items: list[dict[str, Any]] | str,
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        user: str | None = None,
        previous_response_id: str | None = None,
        max_output_tokens: int | None = None,
    ) -> OpenClawHostedResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
            "stream": False,
        }
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if user:
            payload["user"] = user
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.agent_id:
            headers["x-openclaw-agent-id"] = self.agent_id
        if self.model_override:
            headers["x-openclaw-model"] = self.model_override
        if self.message_channel:
            headers["x-openclaw-message-channel"] = self.message_channel

        with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as client:
            response = client.post(f"{self.base_url}/responses", headers=headers, json=payload)

        if response.status_code >= 400:
            detail = response.text.strip()
            raise OpenClawOpenResponsesError(
                f"OpenClaw OpenResponses request failed with HTTP {response.status_code}: {detail}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OpenClawOpenResponsesError(
                f"OpenClaw OpenResponses returned invalid JSON: {response.text[:500]}"
            ) from exc

        if not isinstance(data, dict):
            raise OpenClawOpenResponsesError("OpenClaw OpenResponses payload must be a JSON object.")

        output = data.get("output")
        items = [item for item in output if isinstance(item, dict)] if isinstance(output, list) else []
        text = "\n".join(part for part in (_extract_text(item) for item in items) if part).strip()
        tool_calls = [tool for tool in (_extract_tool_call(item) for item in items) if tool is not None]
        return OpenClawHostedResponse(
            response_id=str(data.get("id") or "") or None,
            text=text,
            tool_calls=tool_calls,
            raw_payload=data,
        )


__all__ = [
    "OpenClawHostedResponse",
    "OpenClawHostedToolCall",
    "OpenClawOpenResponsesClient",
    "OpenClawOpenResponsesError",
]
