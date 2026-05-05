from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import error, request

from .logging_utils import builder_log


class JsonLLMClient(Protocol):
    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate structured JSON output."""


@dataclass(frozen=True)
class DisabledLLMClient:
    """Placeholder client for environments where no live model is configured."""

    reason: str = "LLM client not configured"

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raise RuntimeError(self.reason)


def _read_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip()
    return values


def _load_builder_env() -> dict[str, str]:
    values = dict(os.environ)
    root_env = _read_env_file(".env")
    for key, value in root_env.items():
        values.setdefault(key, value)
    return values


def _normalize_chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("model returned empty content")
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("model did not return valid JSON")
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("model JSON response must be an object")
    return value


@dataclass(frozen=True)
class OpenAICompatibleLLMClient:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 120.0
    max_tokens: int = 1200

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        builder_log(
            "llm",
            f"开始请求模型 model={self.model} timeout={self.timeout_seconds}s max_tokens={self.max_tokens}",
        )
        req = request.Request(
            _normalize_chat_completions_url(self.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            builder_log("llm", f"模型请求返回 HTTP {exc.code}")
            raise RuntimeError(f"LLM HTTP {exc.code}: {raw}") from exc
        except error.URLError as exc:
            builder_log("llm", f"模型请求网络失败: {exc}")
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        payload_json = json.loads(raw)
        choices = payload_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("LLM response missing choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            content = "".join(parts)
        builder_log("llm", "模型请求成功返回 JSON 内容")
        return _parse_json_object(str(content or ""))

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.4,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            return self._request(payload)
        except RuntimeError as exc:
            text = str(exc)
            if "response_format.type" not in text and "json_object" not in text:
                raise
            builder_log("llm", "当前模型不支持 json_object，准备回退到普通 JSON 提示词模式")
        fallback_payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                    + "\nReturn one JSON object only. Do not wrap it in Markdown. Do not add commentary.",
                },
                {"role": "user", "content": user_prompt},
            ],
        }
        return self._request(fallback_payload)


def build_llm_client_from_env() -> JsonLLMClient:
    env = _load_builder_env()
    api_key = str(env.get("OPENAI_API_KEY") or "").strip()
    base_url = str(env.get("OPENAI_API_BASE_URL") or "").strip()
    model = (
        str(env.get("FEISHU_BUILDER_MODEL") or "").strip()
        or str(env.get("VOLCENGINE_EP_ID") or "").strip()
        or str(env.get("OPENAI_MODEL") or "").strip()
    )
    timeout_seconds = float(str(env.get("FEISHU_BUILDER_TIMEOUT_SECONDS") or "120").strip() or "120")
    max_tokens = int(str(env.get("FEISHU_BUILDER_MAX_TOKENS") or "1200").strip() or "1200")
    if not api_key or not base_url or not model:
        builder_log("llm", "未检测到可用的 OPENAI 兼容配置，当前将使用 fallback 生成链")
        return DisabledLLMClient("OPENAI-compatible builder model is not configured")
    builder_log("llm", f"已加载 OPENAI 兼容配置 model={model} base_url={base_url}")
    return OpenAICompatibleLLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
    )
