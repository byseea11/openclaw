"""Unified OpenClaw Gateway client for benchmark evaluation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


def _normalize_gateway_url(gateway_url: str) -> str:
    base = gateway_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/responses"
    if base.endswith("/v1/responses"):
        return base
    return f"{base}/v1/responses"


def _normalize_models_url(gateway_url: str) -> str:
    base = gateway_url.rstrip("/")
    if base.endswith("/v1/responses"):
        return f"{base[:-len('/responses')]}/models"
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


@dataclass(frozen=True)
class OpenClawToolCall:
    """A function call returned by OpenClaw's OpenResponses endpoint."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = "{}"


@dataclass(frozen=True)
class OpenClawEvalResponse:
    """Normalized non-stream OpenClaw response used by eval adapters."""

    response_id: str | None
    text: str
    tool_calls: list[OpenClawToolCall]
    raw_payload: dict[str, Any]
    status: str | None = None
    usage: dict[str, Any] | None = None
    latency_ms: float | None = None


class OpenClawEvalClientError(RuntimeError):
    """Raised when the OpenClaw Gateway request fails or returns bad payloads."""


def _extract_text(item: dict[str, Any]) -> str:
    if item.get("type") != "message":
        return ""
    content = item.get("content")
    if isinstance(content, str):
        return content.strip()
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
    return "\n".join(parts).strip()


def _extract_tool_call(item: dict[str, Any]) -> OpenClawToolCall | None:
    if item.get("type") != "function_call":
        return None
    raw_arguments = str(item.get("arguments") or "{}")
    try:
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
    except json.JSONDecodeError:
        parsed = {"_raw": raw_arguments}
    return OpenClawToolCall(
        id=str(item.get("call_id") or item.get("id") or ""),
        name=str(item.get("name") or ""),
        arguments=parsed,
        raw_arguments=raw_arguments,
    )


class OpenClawEvalClient:
    """Small wrapper over OpenClaw Gateway's `POST /v1/responses`."""

    def __init__(
        self,
        gateway_url: str,
        *,
        agent: str = "main",
        model: str = "openclaw/default",
        token: str | None = None,
        model_override: str | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        self.responses_url = _normalize_gateway_url(gateway_url)
        self.models_url = _normalize_models_url(gateway_url)
        self.agent = agent
        self.model = model
        self.token = token
        self.model_override = model_override
        self.timeout_seconds = timeout_seconds

    def _build_headers(
        self,
        *,
        session_key: str | None = None,
        message_channel: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-openclaw-agent-id": self.agent,
        }
        if session_key:
            headers["x-openclaw-session-key"] = session_key
        if message_channel:
            headers["x-openclaw-message-channel"] = message_channel
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.model_override:
            headers["x-openclaw-model"] = self.model_override
        return headers

    def probe_models(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as client:
            response = client.get(self.models_url, headers=self._build_headers())
        if response.status_code >= 400:
            detail = response.text.strip()
            raise OpenClawEvalClientError(
                f"OpenClaw models probe failed with HTTP {response.status_code}: {detail}"
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OpenClawEvalClientError(
                f"OpenClaw models probe returned invalid JSON: {response.text[:500]}"
            ) from exc
        if not isinstance(data, dict):
            raise OpenClawEvalClientError("OpenClaw models probe payload must be a JSON object.")
        return data

    def send(
        self,
        *,
        session_key: str,
        message_channel: str,
        input_items: list[dict[str, Any]],
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        previous_response_id: str | None = None,
        max_output_tokens: int | None = None,
    ) -> OpenClawEvalResponse:
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
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens

        headers = self._build_headers(
            session_key=session_key,
            message_channel=message_channel,
        )

        started_at = time.perf_counter()
        with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as client:
            response = client.post(self.responses_url, headers=headers, json=payload)
        latency_ms = (time.perf_counter() - started_at) * 1000

        if response.status_code >= 400:
            detail = response.text.strip()
            if response.status_code == 404:
                detail = (
                    f"{detail}\n"
                    "Hint: OpenClaw Gateway reached the port, but `/v1/responses` is not "
                    "available there. Check that you are talking to the real Gateway port and "
                    "that `gateway.http.endpoints.responses.enabled` is set to true."
                )
            raise OpenClawEvalClientError(
                f"OpenClaw request failed with HTTP {response.status_code}: {detail}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise OpenClawEvalClientError(
                f"OpenClaw returned invalid JSON: {response.text[:500]}"
            ) from exc

        if not isinstance(data, dict):
            raise OpenClawEvalClientError("OpenClaw response payload must be a JSON object.")

        output = data.get("output")
        items = [item for item in output if isinstance(item, dict)] if isinstance(output, list) else []
        text = "\n".join(part for part in (_extract_text(item) for item in items) if part).strip()
        tool_calls = [tool for tool in (_extract_tool_call(item) for item in items) if tool is not None]

        usage = data.get("usage")
        normalized_usage = usage if isinstance(usage, dict) else None

        return OpenClawEvalResponse(
            response_id=str(data.get("id") or "") or None,
            text=text,
            tool_calls=tool_calls,
            raw_payload=data,
            status=str(data.get("status") or "") or None,
            usage=normalized_usage,
            latency_ms=round(latency_ms, 3),
        )
