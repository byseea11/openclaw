"""Unified OpenClaw Gateway client for benchmark evaluation."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


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


def _normalize_tools_invoke_urls(gateway_url: str) -> list[str]:
    base = gateway_url.rstrip("/")
    if base.endswith("/v1/responses"):
        root = base[: -len("/v1/responses")]
    elif base.endswith("/v1"):
        root = base[: -len("/v1")]
    else:
        root = base
    candidates = [f"{root}/tools/invoke", f"{root}/v1/tools/invoke"]
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


@dataclass(frozen=True)
class OpenClawToolCall:
    """A function call returned by OpenClaw's OpenResponses endpoint."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = "{}"


@dataclass(frozen=True)
class OpenClawToolOutput:
    """A tool output item returned by OpenClaw's OpenResponses endpoint."""

    call_id: str
    name: str
    output: Any
    raw_output: Any


@dataclass(frozen=True)
class OpenClawEvalResponse:
    """Normalized non-stream OpenClaw response used by eval adapters."""

    response_id: str | None
    text: str
    tool_calls: list[OpenClawToolCall]
    tool_outputs: list[OpenClawToolOutput]
    raw_payload: dict[str, Any]
    status: str | None = None
    usage: dict[str, Any] | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class OpenClawToolInvokeResponse:
    """Normalized direct gateway tool invocation result."""

    ok: bool
    result: Any
    raw_payload: dict[str, Any]
    latency_ms: float | None = None


class OpenClawEvalClientError(RuntimeError):
    """Raised when the OpenClaw Gateway request fails or returns bad payloads."""


@dataclass(frozen=True)
class _JsonHttpResponse:
    status_code: int
    text: str

    def json(self) -> Any:
        return json.loads(self.text)


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout_seconds: float,
) -> _JsonHttpResponse:
    """Use httpx when available, but keep eval runnable with the stdlib only."""

    try:
        import httpx

        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.request(method, url, headers=headers, json=payload)
        return _JsonHttpResponse(status_code=response.status_code, text=response.text)
    except ModuleNotFoundError as exc:
        if exc.name != "httpx":
            raise

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            text = response.read().decode("utf-8", errors="replace")
            return _JsonHttpResponse(status_code=response.status, text=text)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return _JsonHttpResponse(status_code=exc.code, text=text)


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


def _extract_tool_output(
    item: dict[str, Any],
    *,
    tool_name_by_call_id: dict[str, str],
) -> OpenClawToolOutput | None:
    if item.get("type") != "function_call_output":
        return None
    call_id = str(item.get("call_id") or "")
    raw_output = item.get("output")
    parsed_output = raw_output
    if isinstance(raw_output, str):
        try:
            parsed_output = json.loads(raw_output)
        except json.JSONDecodeError:
            parsed_output = raw_output
    return OpenClawToolOutput(
        call_id=call_id,
        name=tool_name_by_call_id.get(call_id, ""),
        output=parsed_output,
        raw_output=raw_output,
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
        self.tools_invoke_urls = _normalize_tools_invoke_urls(gateway_url)
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
        response = _request_json(
            "GET",
            self.models_url,
            headers=self._build_headers(),
            timeout_seconds=self.timeout_seconds,
        )
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

    def invoke_tool(
        self,
        *,
        session_key: str,
        tool: str,
        args: dict[str, Any] | None = None,
        message_channel: str | None = None,
        action: str | None = None,
    ) -> OpenClawToolInvokeResponse:
        payload: dict[str, Any] = {
            "tool": tool,
            "args": args or {},
            "sessionKey": session_key,
        }
        if action:
            payload["action"] = action

        headers = self._build_headers(message_channel=message_channel)
        started_at = time.perf_counter()
        last_404_detail: str | None = None
        last_response: _JsonHttpResponse | None = None

        for tools_invoke_url in self.tools_invoke_urls:
            response = _request_json(
                "POST",
                tools_invoke_url,
                headers=headers,
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            last_response = response
            if response.status_code == 404:
                last_404_detail = response.text.strip()
                continue
            if response.status_code >= 400:
                detail = response.text.strip()
                raise OpenClawEvalClientError(
                    f"OpenClaw tool invoke failed with HTTP {response.status_code}: {detail}"
                )
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise OpenClawEvalClientError(
                    f"OpenClaw tool invoke returned invalid JSON: {response.text[:500]}"
                ) from exc
            if not isinstance(data, dict):
                raise OpenClawEvalClientError(
                    "OpenClaw tool invoke payload must be a JSON object."
                )
            return OpenClawToolInvokeResponse(
                ok=bool(data.get("ok")),
                result=data.get("result"),
                raw_payload=data,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )

        detail = last_404_detail or (last_response.text.strip() if last_response else "")
        raise OpenClawEvalClientError(
            "OpenClaw tool invoke endpoint is unavailable: "
            + (detail or "no supported /tools/invoke route found")
        )

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
        response = _request_json(
            "POST",
            self.responses_url,
            headers=headers,
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
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
        tool_name_by_call_id = {tool.id: tool.name for tool in tool_calls if tool.id}
        tool_outputs = [
            tool
            for tool in (
                _extract_tool_output(item, tool_name_by_call_id=tool_name_by_call_id) for item in items
            )
            if tool is not None
        ]

        usage = data.get("usage")
        normalized_usage = usage if isinstance(usage, dict) else None

        return OpenClawEvalResponse(
            response_id=str(data.get("id") or "") or None,
            text=text,
            tool_calls=tool_calls,
            tool_outputs=tool_outputs,
            raw_payload=data,
            status=str(data.get("status") or "") or None,
            usage=normalized_usage,
            latency_ms=round(latency_ms, 3),
        )
