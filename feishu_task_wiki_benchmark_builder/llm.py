from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Protocol
from urllib import error, request

from .fixture_model_backend import (
    build_fixture_case_context,
    build_fixture_conversation_plan,
    build_fixture_phase3_answer_judge,
    build_fixture_phase3_task_wiki_answer,
    build_fixture_semantic_gold,
    build_fixture_story_plan,
)
from .io import ensure_dir


MODEL_CALL_LOG_PATH = Path("logs") / "model_call_log.jsonl"
REPO_DOTENV_PATH = Path(".env")
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_BUILDER_MODEL = "gpt-5.4"
REPO_DOTENV_AUTH_SOURCE = "repo_root_.env"
REPO_OPENAI_API_KEY_KEY = "OPENAI_API_KEY"
REPO_OPENAI_BASE_URL_KEY = "OPENAI_API_BASE_URL"
REPO_BUILDER_MODEL_KEY = "FEISHU_BUILDER_MODEL"


class ModelBackendError(RuntimeError):
    """Raised when the configured model backend cannot complete a request."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        error_code: str | None = None,
        http_status: int | None = None,
        backend: str = "openai",
        model: str | None = None,
        base_url: str | None = None,
        auth_source: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.error_code = error_code
        self.http_status = http_status
        self.backend = backend
        self.model = model
        self.base_url = base_url
        self.auth_source = auth_source
        self.duration_ms = duration_ms


class ModelPayloadValidationError(RuntimeError):
    """Raised when a model response cannot satisfy the builder schema."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        payload: dict[str, Any],
        backend: str,
        model: str,
        base_url: str,
        duration_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.payload = payload
        self.backend = backend
        self.model = model
        self.base_url = base_url
        self.duration_ms = duration_ms


@dataclass(frozen=True)
class OpenAIRuntimeConfig:
    api_key: str
    model: str
    base_url: str
    auth_source: str


@dataclass
class ModelCallResult:
    payload: dict[str, Any]
    backend: str
    model: str
    base_url: str
    duration_ms: int


@dataclass
class AuthCheckResult:
    backend: str
    model: str
    base_url: str
    auth_source: str
    ok: bool
    error_code: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backend": self.backend,
            "model": self.model,
            "base_url": self.base_url,
            "auth_source": self.auth_source,
            "ok": self.ok,
        }
        if self.error_code is not None:
            payload["error_code"] = self.error_code
        if self.message is not None:
            payload["message"] = self.message
        return payload


class BuilderModelClient(Protocol):
    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> ModelCallResult: ...


class OpenAIChatCompletionsClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        auth_source: str,
        timeout_seconds: int = 90,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.auth_source = auth_source
        self.timeout_seconds = timeout_seconds

    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> ModelCallResult:
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ],
            "response_format": {"type": "json_object"},
        }
        max_tokens = _max_tokens_for_stage(stage)
        if max_tokens is not None:
            request_payload["max_tokens"] = max_tokens
        response_payload, duration_ms = self._post_json(stage=stage, request_payload=request_payload)
        try:
            finish_reason = response_payload["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            finish_reason = None
        if finish_reason == "length":
            raise ModelBackendError(
                f"OpenAI backend truncated JSON output for {stage}.",
                error_type="protocol_error",
                error_code="output_truncated",
                backend="openai",
                model=self.model,
                base_url=self.base_url,
                auth_source=self.auth_source,
                duration_ms=duration_ms,
            )
        try:
            message = response_payload["choices"][0]["message"]["content"]
            raw_response_text = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
            payload = json.loads(raw_response_text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelBackendError(
                f"OpenAI backend returned invalid JSON for {stage}.",
                error_type="protocol_error",
                error_code="invalid_response_json",
                backend="openai",
                model=self.model,
                base_url=self.base_url,
                auth_source=self.auth_source,
                duration_ms=duration_ms,
            ) from exc
        if not isinstance(payload, dict):
            raise ModelBackendError(
                f"OpenAI backend returned non-object JSON for {stage}.",
                error_type="protocol_error",
                error_code="non_object_json",
                backend="openai",
                model=self.model,
                base_url=self.base_url,
                auth_source=self.auth_source,
                duration_ms=duration_ms,
            )
        return ModelCallResult(
            payload=payload,
            backend="openai",
            model=self.model,
            base_url=self.base_url,
            duration_ms=duration_ms,
        )

    def probe_auth(self) -> AuthCheckResult:
        request_payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are running a builder auth probe. Return a compact JSON object.",
                },
                {"role": "user", "content": '{"probe":"auth-check","ok":true}'},
            ],
            "response_format": {"type": "json_object"},
        }
        self._post_json(stage="auth-check", request_payload=request_payload)
        return AuthCheckResult(
            backend="openai",
            model=self.model,
            base_url=self.base_url,
            auth_source=self.auth_source,
            ok=True,
            message="仓库根 .env 中的 OpenAI 配置可用。",
        )

    def _post_json(
        self,
        *,
        stage: str,
        request_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        http_request = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started_at = monotonic()
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                duration_ms = int((monotonic() - started_at) * 1000)
                return json.loads(response.read().decode("utf-8")), duration_ms
        except error.HTTPError as exc:
            duration_ms = int((monotonic() - started_at) * 1000)
            body = exc.read().decode("utf-8", errors="replace")
            raise _map_http_error(
                stage=stage,
                http_status=exc.code,
                body=body,
                model=self.model,
                base_url=self.base_url,
                auth_source=self.auth_source,
                duration_ms=duration_ms,
            ) from exc
        except error.URLError as exc:
            duration_ms = int((monotonic() - started_at) * 1000)
            raise ModelBackendError(
                f"OpenAI backend failed for {stage}: {exc.reason}",
                error_type="network_error",
                error_code="network_error",
                backend="openai",
                model=self.model,
                base_url=self.base_url,
                auth_source=self.auth_source,
                duration_ms=duration_ms,
            ) from exc
        except json.JSONDecodeError as exc:
            duration_ms = int((monotonic() - started_at) * 1000)
            raise ModelBackendError(
                f"OpenAI backend returned non-JSON HTTP payload for {stage}.",
                error_type="protocol_error",
                error_code="http_payload_not_json",
                backend="openai",
                model=self.model,
                base_url=self.base_url,
                auth_source=self.auth_source,
                duration_ms=duration_ms,
            ) from exc


class FixtureModelClient:
    def __init__(self) -> None:
        self.model = "fixture-structured-generator"

    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> ModelCallResult:
        if stage == "case-context":
            payload = build_fixture_case_context(
                seed=int(user_payload["seed"]),
                requested_family_id=user_payload.get("requested_family_id"),
                difficulty=str(user_payload["difficulty"]),
                comparison_target=str(user_payload["comparison_target"]),
            )
        elif stage == "story-plan":
            payload = build_fixture_story_plan(case_context=dict(user_payload["case_context"]))
        elif stage == "conversation-plan":
            payload = build_fixture_conversation_plan(user_payload=dict(user_payload))
        elif stage in {"semantic-gold", "semantic-gold-repair"}:
            payload = build_fixture_semantic_gold(user_payload=dict(user_payload))
        elif stage == "phase3-task-wiki-answer":
            payload = build_fixture_phase3_task_wiki_answer(user_payload=dict(user_payload))
        elif stage == "phase3-answer-judge":
            payload = build_fixture_phase3_answer_judge(user_payload=dict(user_payload))
        else:
            raise ModelBackendError(
                f"Fixture backend does not support stage: {stage}",
                error_type="unsupported_stage",
                error_code="unsupported_fixture_stage",
                backend="fixture",
                model=self.model,
                base_url="fixture://local",
            )
        return ModelCallResult(
            payload=payload,
            backend="fixture",
            model=self.model,
            base_url="fixture://local",
            duration_ms=0,
        )


def get_configured_backend() -> str:
    return os.environ.get("FEISHU_TASK_WIKI_BENCHMARK_BUILDER_MODEL_BACKEND", "openai").strip() or "openai"


def _max_tokens_for_stage(stage: str) -> int | None:
    if stage in {"conversation-plan", "conversation-plan-repair"}:
        return 20000
    return None


def create_model_client() -> BuilderModelClient:
    backend = get_configured_backend()
    if backend == "fixture":
        return FixtureModelClient()
    if backend != "openai":
        raise ModelBackendError(
            f"Unsupported model backend: {backend}",
            error_type="unsupported_backend",
            error_code="unsupported_backend",
            backend=backend,
        )
    config = resolve_openai_runtime_config()
    return OpenAIChatCompletionsClient(
        api_key=config.api_key,
        model=config.model,
        base_url=config.base_url,
        auth_source=config.auth_source,
    )


def resolve_openai_runtime_config() -> OpenAIRuntimeConfig:
    if not REPO_DOTENV_PATH.exists():
        raise ModelBackendError(
            "Repository root .env was not found.",
            error_type="auth_config_error",
            error_code="missing_dotenv",
            backend="openai",
            auth_source=REPO_DOTENV_AUTH_SOURCE,
        )
    dotenv_values = _read_repo_dotenv_values()
    if REPO_OPENAI_API_KEY_KEY not in dotenv_values:
        raise ModelBackendError(
            f"{REPO_OPENAI_API_KEY_KEY} is missing from the repository root .env.",
            error_type="auth_config_error",
            error_code="missing_openai_api_key",
            backend="openai",
            auth_source=REPO_DOTENV_AUTH_SOURCE,
        )
    api_key = dotenv_values[REPO_OPENAI_API_KEY_KEY].strip()
    if not api_key:
        raise ModelBackendError(
            f"{REPO_OPENAI_API_KEY_KEY} in the repository root .env is empty.",
            error_type="auth_config_error",
            error_code="empty_openai_api_key",
            backend="openai",
            auth_source=REPO_DOTENV_AUTH_SOURCE,
        )
    model = dotenv_values.get(REPO_BUILDER_MODEL_KEY, "").strip() or DEFAULT_BUILDER_MODEL
    base_url = dotenv_values.get(REPO_OPENAI_BASE_URL_KEY, "").strip() or DEFAULT_OPENAI_BASE_URL
    return OpenAIRuntimeConfig(
        api_key=api_key,
        model=model,
        base_url=base_url,
        auth_source=REPO_DOTENV_AUTH_SOURCE,
    )


def run_auth_check() -> dict[str, Any]:
    config = resolve_openai_runtime_config()
    client = OpenAIChatCompletionsClient(
        api_key=config.api_key,
        model=config.model,
        base_url=config.base_url,
        auth_source=config.auth_source,
    )
    return client.probe_auth().as_dict()


def preflight_model_backend() -> None:
    backend = get_configured_backend()
    if backend == "fixture":
        return
    if backend != "openai":
        raise ModelBackendError(
            f"Unsupported model backend: {backend}",
            error_type="unsupported_backend",
            error_code="unsupported_backend",
            backend=backend,
        )
    run_auth_check()


def _read_repo_dotenv_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not REPO_DOTENV_PATH.exists():
        return values
    for raw_line in REPO_DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _map_http_error(
    *,
    stage: str,
    http_status: int,
    body: str,
    model: str,
    base_url: str,
    auth_source: str,
    duration_ms: int,
) -> ModelBackendError:
    error_code = f"http_{http_status}"
    message = body.strip() or f"HTTP {http_status}"
    error_type = "http_error"
    try:
        body_payload = json.loads(body)
    except json.JSONDecodeError:
        body_payload = None
    if isinstance(body_payload, dict):
        error_block = body_payload.get("error")
        if isinstance(error_block, dict):
            api_code = error_block.get("code")
            api_message = error_block.get("message")
            api_type = error_block.get("type")
            if isinstance(api_code, str) and api_code:
                error_code = api_code
            elif isinstance(api_type, str) and api_type:
                error_code = api_type
            if isinstance(api_message, str) and api_message:
                message = api_message
    if http_status == 401:
        error_type = "auth_error"
    return ModelBackendError(
        f"OpenAI backend failed for {stage}: HTTP {http_status} {message}",
        error_type=error_type,
        error_code=error_code,
        http_status=http_status,
        backend="openai",
        model=model,
        base_url=base_url,
        auth_source=auth_source,
        duration_ms=duration_ms,
    )


def build_model_call_log_entry(
    *,
    stage: str,
    result: ModelCallResult,
    case_id: str | None,
    artifact_path: str | Path,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "stage": stage,
        "backend": result.backend,
        "model": result.model,
        "base_url": result.base_url,
        "success": True,
        "duration_ms": result.duration_ms,
        "case_id": case_id,
        "artifact_path": str(artifact_path),
    }


def build_model_call_failure_log_entry(
    *,
    stage: str,
    error: ModelBackendError,
    case_id: str | None,
    artifact_path: str | Path,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "stage": stage,
        "backend": error.backend,
        "model": error.model,
        "base_url": error.base_url,
        "success": False,
        "duration_ms": error.duration_ms,
        "case_id": case_id,
        "artifact_path": str(artifact_path),
        "error_type": error.error_type,
        "error_code": error.error_code,
        "http_status": error.http_status,
        "message": str(error),
    }


def build_model_call_validation_failure_log_entry(
    *,
    stage: str,
    error: ModelPayloadValidationError,
    case_id: str | None,
    artifact_path: str | Path,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "stage": stage,
        "backend": error.backend,
        "model": error.model,
        "base_url": error.base_url,
        "success": False,
        "duration_ms": error.duration_ms,
        "case_id": case_id,
        "artifact_path": str(artifact_path),
        "error_type": "validation_error",
        "error_code": "schema_validation_failed",
        "message": str(error),
        "raw_payload": error.payload,
    }


def append_model_call_log(*, case_path: Path, entries: list[dict[str, Any]]) -> Path:
    log_path = case_path / MODEL_CALL_LOG_PATH
    ensure_dir(log_path.parent)
    with log_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path
