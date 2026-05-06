from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .builder_settings import resolve_default_difficulty
from .config import DEFAULT_DATASET_ROOT
from .io import ensure_dir, read_json, read_jsonl, write_json, write_jsonl, write_text
from .llm import (
    MODEL_CALL_LOG_PATH,
    ModelBackendError,
    ModelPayloadValidationError,
    append_model_call_log,
    build_model_call_failure_log_entry,
    build_model_call_validation_failure_log_entry,
    preflight_model_backend,
    run_auth_check,
)
from .runtime.collector import build_observed_messages, collect_fetch_records
from .runtime.executor import execute_plan, execution_result_rows
from .schemas import (
    default_simulated_open_id,
    validate_actor_registry,
    validate_case_world_artifact,
    validate_characters,
    validate_conversation_plan_artifact,
    validate_case_context,
    validate_pre_annotation_report,
    validate_replay_eval,
    validate_story_beats_artifact,
    validate_story_plan,
    validate_task_actor_layout_artifact,
)
from .stages.annotation_gold import build_annotation_gold
from .stages.baseline_eval import build_baseline_eval
from .stages.benchmark_report import build_benchmark_report
from .stages.case_context import generate_case_context
from .stages.case_spec import build_case_spec
from .stages.case_world import build_case_world_artifact
from .stages.command_plan import build_command_plan
from .stages.conversation_plan import build_conversation_plan_artifact
from .stages.common import (
    active_case_path_for,
    build_case_id,
    case_dir_for,
    dataset_root_for_case,
    ensure_case_layout,
    normalize_seed,
)
from .stages.dataset_plan import build_dataset_generation_plan
from .stages.family_selection import select_family
from .stages.capability_brief import build_memory_capability_brief
from .stages.observed_validation import build_pre_annotation_validation_report
from .stages.plan_mapper import build_execution_plan_from_command_plan
from .stages.query_benchmark import build_query_benchmark
from .stages.replay_eval import build_replay_eval
from .stages.story_beats import build_story_beats_artifact
from .stages.story_plan import generate_story_plan
from .stages.task_actor_layout import build_task_actor_layout_artifact
from .stages.value_eval import build_value_eval


class ArtifactDependencyError(FileNotFoundError):
    """Raised when a required artifact for a stage is missing."""


class CliUsageError(ValueError):
    """Raised when a CLI command is missing required explicit inputs."""


PHASE1_STAGE_ORDER = (
    "spec-generation",
    "family-selection",
    "capability-brief",
    "task-actor-layout",
    "case-world",
    "characters",
    "state-trajectory",
    "coverage-spec",
    "story-beats",
    "conversation-plan",
    "command-plan",
    "execute",
    "collect",
    "pre-annotation-validate",
)
PHASE1_COMPAT_STAGE_ORDER = ("case-context", "story-plan")
PHASE1_STAGE_CHOICES = (*PHASE1_STAGE_ORDER, *PHASE1_COMPAT_STAGE_ORDER)
PHASE2_STAGE_ORDER = (
    "annotation-gold",
    "query-benchmark",
    "build-checks",
    "gold-validate",
    "replay-runtime",
    "replay-eval",
)
PHASE3_STAGE_ORDER = (
    "memory-md-baseline",
    "value-eval",
    "report",
)


def _resolve_dataset_root(dataset_root: str | Path | None) -> Path:
    return Path(dataset_root) if dataset_root is not None else DEFAULT_DATASET_ROOT


def _resolve_cli_difficulty(difficulty: str | None) -> str:
    return difficulty if difficulty is not None else resolve_default_difficulty()


def _artifact_result(*, stage: str, case_path: Path, artifact_path: Path, artifact: Any) -> dict[str, Any]:
    return {
        "stage": stage,
        "case_dir": str(case_path),
        "artifact_path": str(case_path / artifact_path),
        "artifact": artifact,
    }


def _multi_artifact_result(*, stage: str, case_path: Path, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stage": stage,
        "case_dir": str(case_path),
        "artifacts": artifacts,
    }


def _require_case_path(case_dir: str | Path, *, stage: str) -> Path:
    case_path = Path(case_dir)
    ensure_case_layout(case_path)
    return case_path


def _read_required_json(case_path: Path, relative_path: str | Path, *, stage: str) -> dict[str, Any]:
    file_path = case_path / relative_path
    if not file_path.exists():
        raise ArtifactDependencyError(f"{stage} 缺少前置 artifact: {relative_path}")
    return read_json(file_path)


def _read_required_jsonl(case_path: Path, relative_path: str | Path, *, stage: str) -> list[dict[str, Any]]:
    file_path = case_path / relative_path
    if not file_path.exists():
        raise ArtifactDependencyError(f"{stage} 缺少前置 artifact: {relative_path}")
    return read_jsonl(file_path)


def _load_case_context(case_path: Path, *, stage: str) -> dict[str, Any]:
    return validate_case_context(_read_required_json(case_path, Path("input") / "case_context.json", stage=stage))


def _load_story_plan(case_path: Path, *, stage: str) -> dict[str, Any]:
    return validate_story_plan(_read_required_json(case_path, Path("input") / "story_plan.json", stage=stage))


def _load_conversation_plan(case_path: Path, *, stage: str) -> dict[str, Any]:
    return validate_conversation_plan_artifact(
        _read_required_json(case_path, Path("input") / "conversation_plan.json", stage=stage)
    )


def _load_task_actor_layout(case_path: Path, *, stage: str) -> dict[str, Any]:
    return validate_task_actor_layout_artifact(
        _read_required_json(case_path, Path("input") / "task_actor_layout.json", stage=stage)
    )


def _fixture_backend_enabled() -> bool:
    return os.environ.get("FEISHU_TASK_WIKI_BENCHMARK_BUILDER_MODEL_BACKEND") == "fixture"


def _case_spec_from_context(case_context: dict[str, Any]) -> dict[str, Any]:
    return build_case_spec(
        family_id=str(case_context["family_id"]),
        difficulty=str(case_context["difficulty"]),
        seed=int(case_context["seed"]),
        comparison_target=str(case_context["comparison_target"]),
    )


def _family_selection_from_context(case_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "family_id": str(case_context["family_id"]),
        "selection_mode": "resolved_from_spec_generation",
        "selection_reason": "spec-generation 已确定当前 case 的正式 family。",
        "seed": int(case_context["seed"]),
    }


_PERSON_NAMES = (
    "林晨",
    "周宇",
    "陈雪",
    "王源",
    "高骏",
    "赵敏",
    "何然",
    "秦怡",
    "罗天",
    "苏禾",
    "唐越",
    "许薇",
    "沈嘉",
    "梁昕",
)


def _department_for_actor_role(role: str) -> str:
    normalized = role.lower()
    if any(token in normalized for token in ("project", "program", "release", "pm", "owner")):
        return "项目管理"
    if any(token in normalized for token in ("dev", "engineer", "backend", "frontend", "data")):
        return "研发平台"
    if any(token in normalized for token in ("qa", "test", "quality")):
        return "质量保障"
    if any(token in normalized for token in ("ops", "infra", "sre", "admin")):
        return "运维保障"
    if any(token in normalized for token in ("security", "compliance", "legal", "auditor")):
        return "安全合规"
    if any(token in normalized for token in ("customer", "support", "sales")):
        return "客户协作"
    if "finance" in normalized:
        return "财务运营"
    if "hr" in normalized or "people" in normalized:
        return "组织发展"
    if any(token in normalized for token in ("doc", "writer", "knowledge")):
        return "知识管理"
    return "企业协作"


def _role_label_for_actor_role(role: str) -> str:
    normalized = role.lower()
    labels = (
        (("project", "program", "release", "pm"), "项目负责人"),
        (("owner",), "当前负责人"),
        (("review", "qa", "test", "quality"), "质量复核人"),
        (("dev", "engineer", "backend", "frontend"), "研发协作者"),
        (("ops", "infra", "sre", "admin"), "运维协作者"),
        (("security", "compliance", "legal", "auditor"), "合规确认人"),
        (("customer", "support", "sales"), "客户接口人"),
        (("finance",), "财务接口人"),
        (("hr", "people"), "组织接口人"),
        (("doc", "writer", "knowledge"), "知识沉淀人"),
    )
    for tokens, label in labels:
        if any(token in normalized for token in tokens):
            return label
    return role.replace("_", " ").strip() or "协作者"


def _default_channels_from_world(case_world: dict[str, Any] | None) -> list[str]:
    sessions = list((case_world or {}).get("source_sessions") or [])
    channels = [f"chat_{session['session_id']}" for session in sessions[:2] if session.get("session_id")]
    return channels or ["chat_main"]


def _characters_from_layout(
    *,
    case_context: dict[str, Any],
    task_actor_layout: dict[str, Any],
    case_world: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default_channels = _default_channels_from_world(case_world)
    rows: list[dict[str, Any]] = []
    for index, actor in enumerate(task_actor_layout["actors"]):
        person_id = str(actor["actor_id"])
        role = str(actor.get("role") or "")
        department = _department_for_actor_role(role)
        name = _PERSON_NAMES[index % len(_PERSON_NAMES)]
        rows.append(
            {
                "person_id": person_id,
                "actor_slot_id": person_id,
                "simulated_open_id": default_simulated_open_id(person_id),
                "name": name,
                "department": department,
                "role": _role_label_for_actor_role(role),
                "task_ids": [str(case_context["task_id"])],
                "default_channels": default_channels,
                "profile": (
                    f"{name}来自{department}，在本 benchmark 中承接 `{person_id}` 槽位，"
                    "负责制造或澄清跨 source 的任务记忆证据。"
                ),
            }
        )
    return validate_characters(
        {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "task_id": case_context["task_id"],
            "characters": rows,
        }
    )


def _actor_registry_from_characters(characters: dict[str, Any]) -> dict[str, Any]:
    validated = validate_characters(characters)
    return validate_actor_registry(
        {
            "case_id": validated["case_id"],
            "family_id": validated["family_id"],
            "task_id": validated["task_id"],
            "actors": [
                {
                    "person_id": actor["person_id"],
                    "simulated_open_id": actor["simulated_open_id"],
                    "name": actor["name"],
                    "department": actor["department"],
                    "role": actor["role"],
                    "default_channels": actor["default_channels"],
                }
                for actor in validated["characters"]
            ],
        }
    )


def _state_trajectory_from_story_plan(*, case_context: dict[str, Any], story_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task_id": case_context["task_id"],
        "state_changes": list(story_plan["state_changes"]),
    }


def _coverage_spec_from_story_plan(*, case_context: dict[str, Any], story_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task_id": case_context["task_id"],
        "required_case_structure": list(case_context["required_case_structure"]),
        "message_beat_ids": [beat["beat_id"] for beat in story_plan["message_beats"]],
        "probe_queries": list(story_plan["planned_probe_queries"]),
    }


def _build_model_backend_error_message(*, stage_label: str, error: ModelBackendError) -> str:
    lines = [f"{stage_label} 失败："]
    if error.error_code == "missing_dotenv":
        lines.append("仓库根 `.env` 不存在，builder 无法读取真实模型认证配置。")
        lines.append("修复方法：在仓库根创建 `.env`，并写入有效的 `OPENAI_API_KEY`。")
    elif error.error_code == "missing_openai_api_key":
        lines.append("仓库根 `.env` 缺少 `OPENAI_API_KEY`。")
        lines.append("修复方法：把有效的 `OPENAI_API_KEY` 写入仓库根 `.env`，然后先运行 `auth-check`。")
    elif error.error_code == "empty_openai_api_key":
        lines.append("仓库根 `.env` 里的 `OPENAI_API_KEY` 为空。")
        lines.append("修复方法：替换成有效的 key，然后重新运行 `auth-check`。")
    elif error.error_code == "invalid_api_key":
        lines.append("仓库根 `.env` 中的 `OPENAI_API_KEY` 无效。")
        lines.append("修复方法：替换 repo 根 `.env` 中的 key，然后重新运行 `auth-check`。")
    elif error.error_type == "network_error":
        lines.append("无法连接到当前 `OPENAI_API_BASE_URL`。")
        lines.append("修复方法：检查 repo 根 `.env` 里的 `OPENAI_API_BASE_URL` 是否正确，或确认当前网络可访问 OpenAI 兼容接口。")
    elif error.error_type == "protocol_error":
        lines.append("模型接口返回了 builder 无法解析的响应。")
        lines.append("修复方法：检查 `OPENAI_API_BASE_URL` 是否指向兼容的 OpenAI Chat Completions 接口。")
    else:
        lines.append(str(error))
        lines.append("修复方法：先运行 `auth-check` 验证 repo 根 `.env` 配置，再重试当前阶段。")
    return "\n".join(lines)


def _build_auth_check_error_payload(error: ModelBackendError) -> dict[str, Any]:
    return {
        "backend": error.backend,
        "model": error.model,
        "base_url": error.base_url,
        "auth_source": error.auth_source,
        "ok": False,
        "error_code": error.error_code,
        "message": _build_model_backend_error_message(stage_label="auth-check", error=error),
    }


def _preflight_stage(stage: str) -> None:
    if stage in {"case-context", "story-plan"}:
        preflight_model_backend()


def _build_active_case_payload(
    *,
    case_path: Path,
    case_context: dict[str, Any],
    last_completed_stage: str,
) -> dict[str, Any]:
    return {
        "case_id": str(case_context["case_id"]),
        "case_dir": str(case_path),
        "family_id": str(case_context["family_id"]),
        "task_id": str(case_context["task_id"]),
        "seed": int(case_context["seed"]),
        "last_completed_stage": last_completed_stage,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    }


def _write_active_case(
    *,
    case_path: Path,
    case_context: dict[str, Any],
    last_completed_stage: str,
) -> Path:
    dataset_root = dataset_root_for_case(case_path)
    active_case_path = active_case_path_for(dataset_root)
    write_json(
        active_case_path,
        _build_active_case_payload(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage=last_completed_stage,
        ),
    )
    return active_case_path


def _read_active_case(dataset_root: str | Path) -> dict[str, Any]:
    dataset_path = _resolve_dataset_root(dataset_root)
    active_case_path = active_case_path_for(dataset_path)
    if not active_case_path.exists():
        raise CliUsageError(
            "当前没有 active case。请先运行 phase1-step --stage case-context，或显式提供 --case-dir。"
        )
    payload = read_json(active_case_path)
    case_dir_value = payload.get("case_dir")
    if not isinstance(case_dir_value, str) or not case_dir_value.strip():
        raise CliUsageError("active_case.json 缺少有效的 case_dir。")
    return payload


def _resolve_case_dir(
    *,
    case_dir: str | Path | None,
    dataset_root: str | Path,
    stage: str,
) -> Path:
    if case_dir is not None:
        return Path(case_dir)
    active_case = _read_active_case(dataset_root)
    return Path(str(active_case["case_dir"]))


def _provisional_case_context_path(
    *,
    dataset_root: str | Path,
    seed: int | None,
    requested_family_id: str | None,
) -> tuple[Path, str]:
    selection = select_family(seed=seed, requested_family_id=requested_family_id)
    case_id = build_case_id(normalize_seed(seed), selection["family_id"])
    dataset_path = _resolve_dataset_root(dataset_root)
    return case_dir_for(dataset_path, case_id), case_id


def _load_runtime_context(case_dir: str | Path) -> dict[str, Any]:
    case_path = Path(case_dir)
    return {
        "case_path": case_path,
        "case_context": validate_case_context(read_json(case_path / "input" / "case_context.json")),
        "story_plan": validate_story_plan(read_json(case_path / "input" / "story_plan.json")),
    }


def run_phase1_case_context(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    family_id: str | None = None,
    difficulty: str | None = None,
    comparison_target: str = "default_memory_architectures",
    skip_preflight: bool = False,
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    if not skip_preflight:
        _preflight_stage("case-context")
    dataset_path = _resolve_dataset_root(dataset_root)
    ensure_dir(dataset_path)
    normalized_seed = normalize_seed(seed)
    provisional_case_path, provisional_case_id = _provisional_case_context_path(
        dataset_root=dataset_path,
        seed=normalized_seed,
        requested_family_id=family_id,
    )
    try:
        case_context, model_call_entries = generate_case_context(
            seed=normalized_seed,
            requested_family_id=family_id,
            difficulty=difficulty,
            comparison_target=comparison_target,
        )
    except ModelBackendError as exc:
        ensure_case_layout(provisional_case_path)
        append_model_call_log(
            case_path=provisional_case_path,
            entries=[
                build_model_call_failure_log_entry(
                    stage="case-context",
                    error=exc,
                    case_id=provisional_case_id,
                    artifact_path="input/case_context.json",
                )
            ],
        )
        raise
    except ModelPayloadValidationError as exc:
        ensure_case_layout(provisional_case_path)
        append_model_call_log(
            case_path=provisional_case_path,
            entries=[
                build_model_call_validation_failure_log_entry(
                    stage="case-context",
                    error=exc,
                    case_id=provisional_case_id,
                    artifact_path="input/case_context.json",
                )
            ],
        )
        raise
    case_path = case_dir_for(dataset_path, case_context["case_id"])
    ensure_case_layout(case_path)
    log_path = append_model_call_log(case_path=case_path, entries=model_call_entries)
    artifact_path = Path("input") / "case_context.json"
    write_json(case_path / artifact_path, case_context)
    result = _artifact_result(
        stage="case-context",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=case_context,
    )
    result["model_call_log_path"] = str(log_path)
    result["active_case_path"] = str(_write_active_case(
        case_path=case_path,
        case_context=case_context,
        last_completed_stage="case-context",
    ))
    return result


def run_phase1_spec_generation(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    family_id: str | None = None,
    difficulty: str | None = None,
    comparison_target: str = "default_memory_architectures",
    skip_preflight: bool = False,
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    result = run_phase1_case_context(
        dataset_root=dataset_root,
        seed=seed,
        family_id=family_id,
        difficulty=difficulty,
        comparison_target=comparison_target,
        skip_preflight=skip_preflight,
    )
    case_path = Path(result["case_dir"])
    case_context = result["artifact"]
    case_spec = _case_spec_from_context(case_context)
    case_spec_path = Path("case_spec.json")
    write_json(case_path / case_spec_path, case_spec)
    result["stage"] = "spec-generation"
    result["artifacts"] = [
        {"artifact_path": result["artifact_path"], "artifact": case_context},
        {"artifact_path": str(case_path / case_spec_path), "artifact": case_spec},
    ]
    result.pop("artifact_path", None)
    result.pop("artifact", None)
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="spec-generation",
        )
    )
    return result


def _ensure_story_plan(
    *,
    case_path: Path,
    case_context: dict[str, Any],
    stage: str,
    skip_preflight: bool = False,
) -> dict[str, Any]:
    story_plan_path = case_path / "input" / "story_plan.json"
    if story_plan_path.exists():
        return _load_story_plan(case_path, stage=stage)
    if not skip_preflight:
        _preflight_stage("story-plan")
    try:
        story_plan, model_call_entries = generate_story_plan(case_context=case_context)
    except ModelBackendError as exc:
        append_model_call_log(
            case_path=case_path,
            entries=[
                build_model_call_failure_log_entry(
                    stage="story-plan",
                    error=exc,
                    case_id=str(case_context["case_id"]),
                    artifact_path="input/story_plan.json",
                )
            ],
        )
        raise
    except ModelPayloadValidationError as exc:
        append_model_call_log(
            case_path=case_path,
            entries=[
                build_model_call_validation_failure_log_entry(
                    stage="story-plan",
                    error=exc,
                    case_id=str(case_context["case_id"]),
                    artifact_path="input/story_plan.json",
                )
            ],
        )
        raise
    append_model_call_log(case_path=case_path, entries=model_call_entries)
    write_json(story_plan_path, story_plan)
    return story_plan


def run_phase1_story_plan(*, case_dir: str | Path, skip_preflight: bool = False) -> dict[str, Any]:
    if not skip_preflight:
        _preflight_stage("story-plan")
    case_path = _require_case_path(case_dir, stage="story-plan")
    case_context = _load_case_context(case_path, stage="story-plan")
    try:
        story_plan, model_call_entries = generate_story_plan(case_context=case_context)
    except ModelBackendError as exc:
        append_model_call_log(
            case_path=case_path,
            entries=[
                build_model_call_failure_log_entry(
                    stage="story-plan",
                    error=exc,
                    case_id=str(case_context["case_id"]),
                    artifact_path="input/story_plan.json",
                )
            ],
        )
        raise
    except ModelPayloadValidationError as exc:
        append_model_call_log(
            case_path=case_path,
            entries=[
                build_model_call_validation_failure_log_entry(
                    stage="story-plan",
                    error=exc,
                    case_id=str(case_context["case_id"]),
                    artifact_path="input/story_plan.json",
                )
            ],
        )
        raise
    log_path = append_model_call_log(case_path=case_path, entries=model_call_entries)
    task_actor_layout_artifact = validate_task_actor_layout_artifact(
        build_task_actor_layout_artifact(case_context=case_context, story_plan=story_plan)
    )
    case_world_artifact = validate_case_world_artifact(
        build_case_world_artifact(
            case_context=case_context,
            task_actor_layout_artifact=task_actor_layout_artifact,
            story_plan=story_plan,
        )
    )
    story_beats_artifact = validate_story_beats_artifact(
        build_story_beats_artifact(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_plan=story_plan,
        )
    )
    conversation_plan_artifact = validate_conversation_plan_artifact(
        build_conversation_plan_artifact(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_beats_artifact=story_beats_artifact,
            story_plan=story_plan,
        )
    )
    characters = _characters_from_layout(
        case_context=case_context,
        task_actor_layout=task_actor_layout_artifact,
        case_world=case_world_artifact,
    )
    actor_registry = _actor_registry_from_characters(characters)
    story_plan_path = Path("input") / "story_plan.json"
    task_actor_layout_path = Path("input") / "task_actor_layout.json"
    case_world_path = Path("input") / "case_world.json"
    characters_path = Path("input") / "characters.json"
    registry_path = Path("input") / "actor_registry.json"
    story_beats_path = Path("input") / "story_beats.json"
    conversation_plan_path = Path("input") / "conversation_plan.json"
    write_json(case_path / story_plan_path, story_plan)
    write_json(case_path / task_actor_layout_path, task_actor_layout_artifact)
    write_json(case_path / case_world_path, case_world_artifact)
    write_json(case_path / characters_path, characters)
    write_json(case_path / registry_path, actor_registry)
    write_json(case_path / story_beats_path, story_beats_artifact)
    write_json(case_path / conversation_plan_path, conversation_plan_artifact)
    result = _multi_artifact_result(
        stage="story-plan",
        case_path=case_path,
        artifacts=[
            {"artifact_path": str(case_path / story_plan_path), "artifact": story_plan},
            {
                "artifact_path": str(case_path / task_actor_layout_path),
                "artifact": task_actor_layout_artifact,
            },
            {"artifact_path": str(case_path / case_world_path), "artifact": case_world_artifact},
            {"artifact_path": str(case_path / characters_path), "artifact": characters},
            {"artifact_path": str(case_path / registry_path), "artifact": actor_registry},
            {"artifact_path": str(case_path / story_beats_path), "artifact": story_beats_artifact},
            {
                "artifact_path": str(case_path / conversation_plan_path),
                "artifact": conversation_plan_artifact,
            },
        ],
    )
    result["model_call_log_path"] = str(log_path)
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="story-plan",
        )
    )
    return result


def run_phase1_family_selection(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="family-selection")
    case_context = _load_case_context(case_path, stage="family-selection")
    family_selection = _family_selection_from_context(case_context)
    artifact_path = Path("input") / "family_selection.json"
    write_json(case_path / artifact_path, family_selection)
    result = _artifact_result(
        stage="family-selection",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=family_selection,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="family-selection",
        )
    )
    return result


def run_phase1_capability_brief(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="capability-brief")
    case_context = _load_case_context(case_path, stage="capability-brief")
    capability_brief = build_memory_capability_brief(family_id=str(case_context["family_id"]))
    artifact_path = Path("input") / "memory_capability_brief.json"
    write_json(case_path / artifact_path, capability_brief)
    result = _artifact_result(
        stage="capability-brief",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=capability_brief,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="capability-brief",
        )
    )
    return result


def run_phase1_task_actor_layout(*, case_dir: str | Path, skip_preflight: bool = False) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="task-actor-layout")
    case_context = _load_case_context(case_path, stage="task-actor-layout")
    story_plan = _ensure_story_plan(
        case_path=case_path,
        case_context=case_context,
        stage="task-actor-layout",
        skip_preflight=skip_preflight,
    )
    task_actor_layout_artifact = validate_task_actor_layout_artifact(
        build_task_actor_layout_artifact(case_context=case_context, story_plan=story_plan)
    )
    artifact_path = Path("input") / "task_actor_layout.json"
    write_json(case_path / artifact_path, task_actor_layout_artifact)
    result = _artifact_result(
        stage="task-actor-layout",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=task_actor_layout_artifact,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="task-actor-layout",
        )
    )
    return result


def run_phase1_case_world(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="case-world")
    case_context = _load_case_context(case_path, stage="case-world")
    story_plan = _load_story_plan(case_path, stage="case-world")
    task_actor_layout_artifact = _load_task_actor_layout(case_path, stage="case-world")
    case_world_artifact = validate_case_world_artifact(
        build_case_world_artifact(
            case_context=case_context,
            task_actor_layout_artifact=task_actor_layout_artifact,
            story_plan=story_plan,
        )
    )
    artifact_path = Path("input") / "case_world.json"
    write_json(case_path / artifact_path, case_world_artifact)
    result = _artifact_result(
        stage="case-world",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=case_world_artifact,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="case-world",
        )
    )
    return result


def run_phase1_characters(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="characters")
    case_context = _load_case_context(case_path, stage="characters")
    task_actor_layout = _load_task_actor_layout(case_path, stage="characters")
    case_world = validate_case_world_artifact(
        _read_required_json(case_path, Path("input") / "case_world.json", stage="characters")
    )
    characters = _characters_from_layout(
        case_context=case_context,
        task_actor_layout=task_actor_layout,
        case_world=case_world,
    )
    actor_registry = _actor_registry_from_characters(characters)
    characters_path = Path("input") / "characters.json"
    registry_path = Path("input") / "actor_registry.json"
    write_json(case_path / characters_path, characters)
    write_json(case_path / registry_path, actor_registry)
    result = _multi_artifact_result(
        stage="characters",
        case_path=case_path,
        artifacts=[
            {"artifact_path": str(case_path / characters_path), "artifact": characters},
            {"artifact_path": str(case_path / registry_path), "artifact": actor_registry},
        ],
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="characters",
        )
    )
    return result


def run_phase1_state_trajectory(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="state-trajectory")
    case_context = _load_case_context(case_path, stage="state-trajectory")
    story_plan = _load_story_plan(case_path, stage="state-trajectory")
    state_trajectory = _state_trajectory_from_story_plan(case_context=case_context, story_plan=story_plan)
    artifact_path = Path("input") / "state_trajectory.json"
    write_json(case_path / artifact_path, state_trajectory)
    result = _artifact_result(
        stage="state-trajectory",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=state_trajectory,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="state-trajectory",
        )
    )
    return result


def run_phase1_coverage_spec(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="coverage-spec")
    case_context = _load_case_context(case_path, stage="coverage-spec")
    story_plan = _load_story_plan(case_path, stage="coverage-spec")
    coverage_spec = _coverage_spec_from_story_plan(case_context=case_context, story_plan=story_plan)
    artifact_path = Path("input") / "coverage_spec.json"
    write_json(case_path / artifact_path, coverage_spec)
    result = _artifact_result(
        stage="coverage-spec",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=coverage_spec,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="coverage-spec",
        )
    )
    return result


def run_phase1_story_beats(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="story-beats")
    case_context = _load_case_context(case_path, stage="story-beats")
    story_plan = _load_story_plan(case_path, stage="story-beats")
    case_world_artifact = validate_case_world_artifact(
        _read_required_json(case_path, Path("input") / "case_world.json", stage="story-beats")
    )
    story_beats_artifact = validate_story_beats_artifact(
        build_story_beats_artifact(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_plan=story_plan,
        )
    )
    artifact_path = Path("input") / "story_beats.json"
    write_json(case_path / artifact_path, story_beats_artifact)
    result = _artifact_result(
        stage="story-beats",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=story_beats_artifact,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="story-beats",
        )
    )
    return result


def run_phase1_conversation_plan(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="conversation-plan")
    case_context = _load_case_context(case_path, stage="conversation-plan")
    story_plan = _load_story_plan(case_path, stage="conversation-plan")
    case_world_artifact = validate_case_world_artifact(
        _read_required_json(case_path, Path("input") / "case_world.json", stage="conversation-plan")
    )
    story_beats_artifact = validate_story_beats_artifact(
        _read_required_json(case_path, Path("input") / "story_beats.json", stage="conversation-plan")
    )
    conversation_plan_artifact = validate_conversation_plan_artifact(
        build_conversation_plan_artifact(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_beats_artifact=story_beats_artifact,
            story_plan=story_plan,
        )
    )
    artifact_path = Path("input") / "conversation_plan.json"
    write_json(case_path / artifact_path, conversation_plan_artifact)
    result = _artifact_result(
        stage="conversation-plan",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=conversation_plan_artifact,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="conversation-plan",
        )
    )
    return result


def run_phase1_command_plan(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="command-plan")
    case_context = _load_case_context(case_path, stage="command-plan")
    conversation_plan = _load_conversation_plan(case_path, stage="command-plan")
    task_actor_layout = _load_task_actor_layout(case_path, stage="command-plan")
    characters = validate_characters(
        _read_required_json(case_path, Path("input") / "characters.json", stage="command-plan")
    )
    actor_registry = validate_actor_registry(
        _read_required_json(case_path, Path("input") / "actor_registry.json", stage="command-plan")
    )
    command_plan = build_command_plan(
        conversation_plan=conversation_plan,
        characters=characters,
        actor_registry=actor_registry,
        task_actor_layout=task_actor_layout,
    )
    execution_plan = build_execution_plan_from_command_plan(command_plan)
    command_plan_path = Path("input") / "command_plan.jsonl"
    execution_plan_path = Path("execution_plan.json")
    write_jsonl(case_path / command_plan_path, command_plan)
    write_json(case_path / execution_plan_path, execution_plan)
    result = _multi_artifact_result(
        stage="command-plan",
        case_path=case_path,
        artifacts=[
            {"artifact_path": str(case_path / command_plan_path), "artifact": command_plan},
            {"artifact_path": str(case_path / execution_plan_path), "artifact": execution_plan},
        ],
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="command-plan",
        )
    )
    return result


def run_phase1_execute(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="execute")
    case_context = _load_case_context(case_path, stage="execute")
    execution_plan = _read_required_json(case_path, Path("execution_plan.json"), stage="execute")
    execution_result = execute_plan(
        execution_plan,
        dry_run=_fixture_backend_enabled(),
    )
    execution_result_path = Path("runtime") / "execution_result.json"
    executed_commands_path = Path("runtime") / "executed_commands.jsonl"
    executed_command_rows = execution_result_rows(execution_result)
    write_json(case_path / execution_result_path, execution_result)
    write_jsonl(case_path / executed_commands_path, executed_command_rows)
    result = _multi_artifact_result(
        stage="execute",
        case_path=case_path,
        artifacts=[
            {"artifact_path": str(case_path / execution_result_path), "artifact": execution_result},
            {"artifact_path": str(case_path / executed_commands_path), "artifact": executed_command_rows},
        ],
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="execute",
        )
    )
    return result


def run_phase1_collect(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="collect")
    case_context = _load_case_context(case_path, stage="collect")
    command_plan = _read_required_jsonl(case_path, Path("input") / "command_plan.jsonl", stage="collect")
    execution_plan = _read_required_json(case_path, Path("execution_plan.json"), stage="collect")
    execution_result = _read_required_json(
        case_path,
        Path("runtime") / "execution_result.json",
        stage="collect",
    )
    characters = validate_characters(_read_required_json(case_path, Path("input") / "characters.json", stage="collect"))
    actor_registry = validate_actor_registry(
        _read_required_json(case_path, Path("input") / "actor_registry.json", stage="collect")
    )
    fetch_records = [] if _fixture_backend_enabled() else collect_fetch_records(execution_plan, execution_result)
    collected_messages, openclaw_ingress = build_observed_messages(
        case_id=case_context["case_id"],
        task_id=case_context["task_id"],
        command_plan=command_plan,
        execution_result=execution_result,
        fetch_records=fetch_records,
        characters=characters,
        actor_registry=actor_registry,
    )
    fetch_records_path = Path("runtime") / "fetch_records.jsonl"
    collected_path = Path("data") / "collected_messages.jsonl"
    ingress_path = Path("data") / "openclaw_message_ingress.jsonl"
    write_jsonl(case_path / fetch_records_path, fetch_records)
    write_jsonl(case_path / collected_path, collected_messages)
    write_jsonl(case_path / ingress_path, openclaw_ingress)
    result = _multi_artifact_result(
        stage="collect",
        case_path=case_path,
        artifacts=[
            {
                "artifact_path": str(case_path / fetch_records_path),
                "artifact": fetch_records,
            },
            {
                "artifact_path": str(case_path / collected_path),
                "artifact": collected_messages,
            },
            {
                "artifact_path": str(case_path / ingress_path),
                "artifact": openclaw_ingress,
            },
        ],
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="collect",
        )
    )
    return result


def run_phase1_pre_annotation_validate(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="pre-annotation-validate")
    case_context = _load_case_context(case_path, stage="pre-annotation-validate")
    story_plan = _load_story_plan(case_path, stage="pre-annotation-validate")
    collected_messages = _read_required_jsonl(
        case_path,
        Path("data") / "collected_messages.jsonl",
        stage="pre-annotation-validate",
    )
    validation_report = build_pre_annotation_validation_report(
        case_id=case_context["case_id"],
        story_plan=story_plan,
        collected_messages=collected_messages,
    )
    artifact_path = Path("checks") / "pre_annotation_validation_report.json"
    write_json(case_path / artifact_path, validation_report)
    result = _artifact_result(
        stage="pre-annotation-validate",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=validation_report,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="pre-annotation-validate",
        )
    )
    return result


def run_phase2_annotation_gold(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    story_plan = context["story_plan"]
    collected_messages = read_jsonl(case_path / "data" / "collected_messages.jsonl")
    validation_report = validate_pre_annotation_report(
        read_json(case_path / "checks" / "pre_annotation_validation_report.json")
    )
    if not validation_report["is_valid"]:
        raise ValueError("pre_annotation_validation_report indicates the case is invalid")
    annotation_gold_rows = build_annotation_gold(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        story_plan=story_plan,
        collected_messages=collected_messages,
    )
    artifact_path = Path("gold") / "annotation_gold.jsonl"
    write_jsonl(case_path / artifact_path, annotation_gold_rows)
    result = _artifact_result(
        stage="annotation-gold",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=annotation_gold_rows,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="annotation-gold",
        )
    )
    return result


def run_phase2_query_benchmark(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    story_plan = context["story_plan"]
    annotation_gold_rows = read_jsonl(case_path / "gold" / "annotation_gold.jsonl")
    query_benchmark = build_query_benchmark(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        story_plan=story_plan,
        annotation_gold_rows=annotation_gold_rows,
    )
    artifact_path = Path("gold") / "query_benchmark.json"
    write_json(case_path / artifact_path, query_benchmark)
    result = _artifact_result(
        stage="query-benchmark",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=query_benchmark,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="query-benchmark",
        )
    )
    return result


def run_phase2_build_checks(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    annotation_gold_rows = read_jsonl(case_path / "gold" / "annotation_gold.jsonl")
    query_benchmark = read_json(case_path / "gold" / "query_benchmark.json")
    checks = {
        "eval_manifest": {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "annotation_count": len(annotation_gold_rows),
            "query_count": len(query_benchmark["queries"]),
            "stage_contract": list(PHASE2_STAGE_ORDER),
        },
        "integrity_gate": {
            "case_id": case_context["case_id"],
            "status": "ready_for_gold_validation",
            "annotation_gold_present": bool(annotation_gold_rows),
            "query_benchmark_present": bool(query_benchmark["queries"]),
        },
    }
    manifest_path = Path("checks") / "eval_manifest.json"
    integrity_path = Path("checks") / "integrity_gate.json"
    write_json(case_path / manifest_path, checks["eval_manifest"])
    write_json(case_path / integrity_path, checks["integrity_gate"])
    result = _multi_artifact_result(
        stage="build-checks",
        case_path=case_path,
        artifacts=[
            {"artifact_path": str(case_path / manifest_path), "artifact": checks["eval_manifest"]},
            {"artifact_path": str(case_path / integrity_path), "artifact": checks["integrity_gate"]},
        ],
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="build-checks")
    )
    return result


def run_phase2_gold_validate(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    collected_messages = read_jsonl(case_path / "data" / "collected_messages.jsonl")
    annotation_gold_rows = read_jsonl(case_path / "gold" / "annotation_gold.jsonl")
    collected_ids = {row["message_id"] for row in collected_messages}
    missing_ids = [row["message_id"] for row in annotation_gold_rows if row["message_id"] not in collected_ids]
    report = {
        "case_id": case_context["case_id"],
        "status": "passed" if not missing_ids else "failed",
        "annotation_count": len(annotation_gold_rows),
        "missing_message_ids": missing_ids,
    }
    artifact_path = Path("checks") / "gold_validation_report.json"
    write_json(case_path / artifact_path, report)
    result = _artifact_result(
        stage="gold-validate",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=report,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="gold-validate")
    )
    return result


def run_phase2_replay_runtime(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    query_benchmark = read_json(case_path / "gold" / "query_benchmark.json")
    predictions = {
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "runtime": "task_wiki_replay_placeholder",
        "answers": [
            {
                "query_id": query["query_id"],
                "answer": query["expected_good_behavior"],
                "supporting_message_ids": query["supporting_message_ids"],
            }
            for query in query_benchmark["queries"]
        ],
    }
    artifact_path = Path("predictions") / "task_wiki_replay_predictions.json"
    write_json(case_path / artifact_path, predictions)
    result = _artifact_result(
        stage="replay-runtime",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=predictions,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="replay-runtime")
    )
    return result


def run_phase2_replay_eval(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    query_benchmark = read_json(case_path / "gold" / "query_benchmark.json")
    replay_eval = build_replay_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        query_benchmark=query_benchmark,
    )
    artifact_path = Path("reports") / "replay_eval.json"
    write_json(case_path / artifact_path, replay_eval)
    result = _artifact_result(
        stage="replay-eval",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=replay_eval,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="replay-eval")
    )
    return result


def run_phase3_memory_md_baseline(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    replay_eval = validate_replay_eval(read_json(case_path / "reports" / "replay_eval.json"))
    baseline_eval = build_baseline_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        replay_eval=replay_eval,
    )
    artifact_path = Path("reports") / "baseline_eval.json"
    write_json(case_path / artifact_path, baseline_eval)
    result = _artifact_result(
        stage="memory-md-baseline",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=baseline_eval,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="memory-md-baseline")
    )
    return result


def run_phase3_value_eval(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    baseline_eval = read_json(case_path / "reports" / "baseline_eval.json")
    value_eval = build_value_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        baseline_eval=baseline_eval,
    )
    artifact_path = Path("reports") / "value_eval.json"
    write_json(case_path / artifact_path, value_eval)
    result = _artifact_result(
        stage="value-eval",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=value_eval,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="value-eval")
    )
    return result


def run_phase3_report(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    replay_eval = validate_replay_eval(read_json(case_path / "reports" / "replay_eval.json"))
    baseline_eval = read_json(case_path / "reports" / "baseline_eval.json")
    value_eval = read_json(case_path / "reports" / "value_eval.json")
    report_text = build_benchmark_report(
        case_context=case_context,
        replay_eval=replay_eval,
        baseline_eval=baseline_eval,
        value_eval=value_eval,
    )
    artifact_path = Path("reports") / "final_benchmark_report.md"
    write_text(case_path / artifact_path, report_text)
    result = _artifact_result(
        stage="report",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=report_text,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="report")
    )
    return result


PHASE1_STAGE_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "spec-generation": run_phase1_spec_generation,
    "family-selection": run_phase1_family_selection,
    "capability-brief": run_phase1_capability_brief,
    "task-actor-layout": run_phase1_task_actor_layout,
    "case-world": run_phase1_case_world,
    "characters": run_phase1_characters,
    "state-trajectory": run_phase1_state_trajectory,
    "coverage-spec": run_phase1_coverage_spec,
    "story-beats": run_phase1_story_beats,
    "conversation-plan": run_phase1_conversation_plan,
    "case-context": run_phase1_case_context,
    "story-plan": run_phase1_story_plan,
    "command-plan": run_phase1_command_plan,
    "execute": run_phase1_execute,
    "collect": run_phase1_collect,
    "pre-annotation-validate": run_phase1_pre_annotation_validate,
}


def run_phase1_step(
    *,
    stage: str,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    case_dir: str | Path | None = None,
    seed: int | None = None,
    family_id: str | None = None,
    difficulty: str | None = None,
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    if stage not in PHASE1_STAGE_REGISTRY:
        raise CliUsageError(f"不支持的 phase1 stage: {stage}")
    if stage == "spec-generation":
        return run_phase1_spec_generation(
            dataset_root=dataset_root,
            seed=seed,
            family_id=family_id,
            difficulty=difficulty,
            comparison_target=comparison_target,
        )
    if stage == "case-context":
        return run_phase1_case_context(
            dataset_root=dataset_root,
            seed=seed,
            family_id=family_id,
            difficulty=difficulty,
            comparison_target=comparison_target,
        )
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage=stage)
    return PHASE1_STAGE_REGISTRY[stage](case_dir=resolved_case_dir)


def generate_dataset_plan_stage(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    dataset_size: int = 4,
    seed: int | None = None,
    difficulty: str | None = None,
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    dataset_path = _resolve_dataset_root(dataset_root)
    ensure_dir(dataset_path)
    plan = build_dataset_generation_plan(dataset_size=dataset_size, seed=seed, difficulty=difficulty)
    write_json(dataset_path / "dataset_generation_plan.json", plan)
    return {"dataset_root": str(dataset_path), "dataset_generation_plan": plan}


def current_case(*, dataset_root: str | Path = DEFAULT_DATASET_ROOT) -> dict[str, Any]:
    dataset_path = _resolve_dataset_root(dataset_root)
    active_case = _read_active_case(dataset_path)
    return {"dataset_root": str(dataset_path), **active_case}


def compile_phase1(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    difficulty: str | None = None,
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    preflight_model_backend()
    spec_generation_result = run_phase1_spec_generation(
        dataset_root=dataset_root,
        seed=seed,
        family_id=family_id,
        difficulty=difficulty,
        comparison_target=comparison_target,
        skip_preflight=True,
    )
    case_path = Path(spec_generation_result["case_dir"])
    run_phase1_family_selection(case_dir=case_path)
    run_phase1_capability_brief(case_dir=case_path)
    run_phase1_task_actor_layout(case_dir=case_path, skip_preflight=True)
    for stage in PHASE1_STAGE_ORDER[4:]:
        run_phase1_step(stage=stage, case_dir=case_path)
    case_context = _load_case_context(case_path, stage="phase1")
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "completed_stages": list(PHASE1_STAGE_ORDER),
        "model_call_log_path": str(case_path / MODEL_CALL_LOG_PATH),
        "active_case_path": str(active_case_path_for(dataset_root_for_case(case_path))),
    }


def compile_phase2(
    *,
    case_dir: str | Path | None = None,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
) -> dict[str, Any]:
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage="phase2")
    case_path = Path(resolved_case_dir)
    for stage in PHASE2_STAGE_ORDER:
        {
            "annotation-gold": run_phase2_annotation_gold,
            "query-benchmark": run_phase2_query_benchmark,
            "build-checks": run_phase2_build_checks,
            "gold-validate": run_phase2_gold_validate,
            "replay-runtime": run_phase2_replay_runtime,
            "replay-eval": run_phase2_replay_eval,
        }[stage](case_dir=case_path)
    case_context = _load_case_context(case_path, stage="phase2")
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "completed_stages": list(PHASE2_STAGE_ORDER),
        "active_case_path": str(active_case_path_for(dataset_root_for_case(case_path))),
    }


def compile_phase3(
    *,
    case_dir: str | Path | None = None,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
) -> dict[str, Any]:
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage="phase3")
    case_path = Path(resolved_case_dir)
    for stage in PHASE3_STAGE_ORDER:
        {
            "memory-md-baseline": run_phase3_memory_md_baseline,
            "value-eval": run_phase3_value_eval,
            "report": run_phase3_report,
        }[stage](case_dir=case_path)
    case_context = _load_case_context(case_path, stage="phase3")
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "completed_stages": list(PHASE3_STAGE_ORDER),
        "active_case_path": str(active_case_path_for(dataset_root_for_case(case_path))),
    }


def build_all(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    difficulty: str | None = None,
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    phase1 = compile_phase1(
        dataset_root=dataset_root,
        seed=seed,
        difficulty=difficulty,
        family_id=family_id,
        comparison_target=comparison_target,
    )
    phase2 = compile_phase2(case_dir=phase1["case_dir"])
    phase3 = compile_phase3(case_dir=phase1["case_dir"])
    return {
        "case_dir": phase1["case_dir"],
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu Task Wiki Benchmark Builder")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_difficulty = resolve_default_difficulty()

    dataset_plan_parser = subparsers.add_parser("dataset-plan")
    dataset_plan_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    dataset_plan_parser.add_argument("--dataset-size", type=int, default=4)
    dataset_plan_parser.add_argument("--seed", type=int, default=1)
    dataset_plan_parser.add_argument("--difficulty", default=default_difficulty)

    subparsers.add_parser("auth-check")
    current_case_parser = subparsers.add_parser("current-case")
    current_case_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))

    phase1_step_parser = subparsers.add_parser("phase1-step")
    phase1_step_parser.add_argument("--stage", choices=PHASE1_STAGE_CHOICES, required=True)
    phase1_step_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    phase1_step_parser.add_argument("--case-dir")
    phase1_step_parser.add_argument("--seed", type=int)
    phase1_step_parser.add_argument("--family-id")
    phase1_step_parser.add_argument("--difficulty", default=default_difficulty)
    phase1_step_parser.add_argument("--comparison-target", default="default_memory_architectures")

    for name in ("phase1", "build-all"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
        subparser.add_argument("--seed", type=int)
        subparser.add_argument("--difficulty", default=default_difficulty)
        subparser.add_argument("--family-id")
        subparser.add_argument("--comparison-target", default="default_memory_architectures")

    for name in ("phase2", "phase3"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
        subparser.add_argument("--case-dir")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "dataset-plan":
            result = generate_dataset_plan_stage(
                dataset_root=args.dataset_root,
                dataset_size=args.dataset_size,
                seed=args.seed,
                difficulty=args.difficulty,
            )
        elif args.command == "auth-check":
            result = run_auth_check()
        elif args.command == "current-case":
            result = current_case(dataset_root=args.dataset_root)
        elif args.command == "phase1-step":
            result = run_phase1_step(
                stage=args.stage,
                dataset_root=args.dataset_root,
                case_dir=args.case_dir,
                seed=args.seed,
                family_id=args.family_id,
                difficulty=args.difficulty,
                comparison_target=args.comparison_target,
            )
        elif args.command == "phase1":
            result = compile_phase1(
                dataset_root=args.dataset_root,
                seed=args.seed,
                difficulty=args.difficulty,
                family_id=args.family_id,
                comparison_target=args.comparison_target,
            )
        elif args.command == "phase2":
            result = compile_phase2(case_dir=args.case_dir, dataset_root=args.dataset_root)
        elif args.command == "phase3":
            result = compile_phase3(case_dir=args.case_dir, dataset_root=args.dataset_root)
        elif args.command == "build-all":
            result = build_all(
                dataset_root=args.dataset_root,
                seed=args.seed,
                difficulty=args.difficulty,
                family_id=args.family_id,
                comparison_target=args.comparison_target,
            )
        else:
            parser.error(f"Unsupported command: {args.command}")
            return 2
    except (ArtifactDependencyError, CliUsageError) as exc:
        parser.exit(2, f"{exc}\n")
    except ModelBackendError as exc:
        if args.command == "auth-check":
            parser.exit(2, f"{json.dumps(_build_auth_check_error_payload(exc), ensure_ascii=False, indent=2)}\n")
        stage_label = "builder 模型阶段"
        if args.command == "phase1-step":
            stage_label = f"phase1-step::{args.stage}"
        elif args.command == "phase1":
            stage_label = "phase1 预检或模型阶段"
        elif args.command == "build-all":
            stage_label = "build-all / phase1 预检或模型阶段"
        parser.exit(2, f"{_build_model_backend_error_message(stage_label=stage_label, error=exc)}\n")
    except ModelPayloadValidationError as exc:
        stage_label = "builder payload 校验阶段"
        if args.command == "phase1-step":
            stage_label = f"phase1-step::{args.stage}"
        elif args.command == "phase1":
            stage_label = "phase1 payload 校验阶段"
        elif args.command == "build-all":
            stage_label = "build-all / phase1 payload 校验阶段"
        parser.exit(2, f"{stage_label} 失败：\n{exc}\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
