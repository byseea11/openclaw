from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .builder_settings import resolve_default_difficulty
from .builder_settings import resolve_difficulty_settings
from .config import ACTIVE_BATCH_FILENAME
from .config import BATCHES_DIRNAME
from .config import DEFAULT_DATASET_ROOT
from .config import FORMAL_FAMILY_IDS
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
    validate_official_file_plan,
    validate_pre_annotation_report,
    validate_replay_eval,
    validate_story_beats_artifact,
    validate_story_plan,
    validate_task_actor_layout_artifact,
)
from .stages.annotation_gold import build_annotation_gold
from .stages.case_context import generate_case_context
from .stages.case_spec import build_case_spec
from .stages.case_world import build_case_world_artifact
from .stages.command_plan import build_command_plan
from .stages.conversation_plan import generate_conversation_plan
from .stages.comparative_eval import build_comparative_eval
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
from .stages.official_file_plan import build_official_file_plan
from .stages.plan_mapper import build_execution_plan_from_command_plan
from .stages.query_benchmark import build_query_benchmark
from .stages.replay_eval import build_replay_eval
from .stages.semantic_gold import generate_semantic_gold
from .stages.story_beats import build_story_beats_artifact
from .stages.story_plan import generate_story_plan
from .stages.task_actor_layout import build_task_actor_layout_artifact


class ArtifactDependencyError(FileNotFoundError):
    """Raised when a required artifact for a stage is missing."""


class CliUsageError(ValueError):
    """Raised when a CLI command is missing required explicit inputs."""


class RuntimeScriptError(RuntimeError):
    """Raised when a Phase 3 Node runtime script fails after writing diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        failure_artifact_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.failure_artifact_path = failure_artifact_path


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
PHASE1_STAGE_CHOICES = PHASE1_STAGE_ORDER
PHASE2_STAGE_ORDER = (
    "annotation-gold",
    "semantic-gold",
    "query-benchmark",
    "build-checks",
    "gold-validate",
    "replay-runtime",
    "replay-eval",
)
PHASE3_STAGE_ORDER = (
    "task-wiki-runtime-eval",
    "openclaw-real-baseline-eval",
    "comparative-score",
)
BATCH_PHASE1_STAGE = "phase1"
BATCH_PHASE2_STAGE = "phase2"
BATCH_PHASE3_STAGE = "phase3"


def _resolve_dataset_root(dataset_root: str | Path | None) -> Path:
    return Path(dataset_root) if dataset_root is not None else DEFAULT_DATASET_ROOT


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _truncate_text(value: str, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def _build_batch_id() -> str:
    return f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S%f')}"


def _batch_dir_for(dataset_root: Path, batch_id: str) -> Path:
    return dataset_root / BATCHES_DIRNAME / batch_id


def _active_batch_path_for(dataset_root: Path) -> Path:
    return dataset_root / ACTIVE_BATCH_FILENAME


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

_SUPPORT_DEPARTMENTS = (
    "项目管理",
    "研发平台",
    "质量保障",
    "运维保障",
    "安全合规",
    "客户协作",
    "财务运营",
    "组织发展",
    "知识管理",
    "数据平台",
    "发布治理",
    "业务运营",
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
    character_count_min = int(resolve_difficulty_settings(str(case_context["difficulty"]))["character_count_min"])
    support_index = 1
    while len(rows) < character_count_min:
        person_id = f"support_actor_{support_index:03d}"
        if any(row["person_id"] == person_id for row in rows):
            support_index += 1
            continue
        name = _PERSON_NAMES[len(rows) % len(_PERSON_NAMES)]
        department = _SUPPORT_DEPARTMENTS[len(rows) % len(_SUPPORT_DEPARTMENTS)]
        rows.append(
            {
                "person_id": person_id,
                "actor_slot_id": person_id,
                "simulated_open_id": default_simulated_open_id(person_id),
                "name": name,
                "department": department,
                "role": "协作参与人",
                "task_ids": [str(case_context["task_id"])],
                "default_channels": default_channels,
                "profile": f"{name}来自{department}，用于补足真实企业协作中的背景、确认和噪声消息。",
            }
        )
        support_index += 1
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
    elif error.error_code == "output_truncated":
        lines.append("模型返回的 JSON 被长度上限截断。")
        lines.append("修复方法：降低当前阶段输出规模、压缩 prompt，或提高该 stage 的 `max_tokens`。")
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
    if stage in {"conversation-plan"}:
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


def _builder_runs_dir(case_path: Path) -> Path:
    return case_path / "runtime" / "builder_runs"


def _failure_dir(case_path: Path, phase: str) -> Path:
    return case_path / "runtime" / "failures" / phase


def _dataset_failure_dir(dataset_root: str | Path, phase: str) -> Path:
    return _resolve_dataset_root(dataset_root) / "runtime" / "failures" / phase


def _write_builder_journal(case_path: Path, payload: dict[str, Any]) -> Path:
    run_dir = ensure_dir(_builder_runs_dir(case_path))
    run_id = str(payload.get("run_id") or _run_id())
    payload["run_id"] = run_id
    payload["updated_at"] = _utc_now_iso()
    latest_path = run_dir / "latest.json"
    historical_path = run_dir / f"{run_id}.json"
    write_json(latest_path, payload)
    write_json(historical_path, payload)
    return latest_path


def _write_stage_failure(
    *,
    phase: str,
    stage: str,
    error: BaseException,
    case_path: Path | None = None,
    dataset_root: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    run_id = _run_id()
    if case_path is not None:
        directory = ensure_dir(_failure_dir(case_path, phase))
    elif dataset_root is not None:
        directory = ensure_dir(_dataset_failure_dir(dataset_root, phase))
    else:
        raise ValueError("case_path or dataset_root is required for failure artifact")
    payload = {
        "phase": phase,
        "stage": stage,
        "status": "failed",
        "run_id": run_id,
        "failed_at": _utc_now_iso(),
        "case_dir": str(case_path) if case_path is not None else None,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "extra": extra or {},
    }
    failure_path = directory / f"{stage}_{run_id}.json"
    write_json(failure_path, payload)
    if case_path is not None:
        latest_path = _failure_dir(case_path, phase) / f"{stage}_latest.json"
        write_json(latest_path, payload | {"failure_artifact_path": str(failure_path)})
    return failure_path


def _stage_result_artifact_paths(result: dict[str, Any]) -> list[str]:
    if "artifact_path" in result and isinstance(result["artifact_path"], str):
        return [result["artifact_path"]]
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        return [
            str(item["artifact_path"])
            for item in artifacts
            if isinstance(item, dict) and isinstance(item.get("artifact_path"), str)
        ]
    return []


def _skipped_stage_result(*, stage: str, case_path: Path, artifact_paths: list[str]) -> dict[str, Any]:
    return {
        "stage": stage,
        "case_dir": str(case_path),
        "skipped": True,
        "skip_reason": "resume_artifacts_present",
        "artifact_paths": artifact_paths,
    }


def _stage_artifacts_readable(case_path: Path, relative_paths: list[str | Path]) -> bool:
    try:
        for relative_path in relative_paths:
            path = case_path / relative_path
            if not path.exists():
                return False
            if path.suffix == ".json":
                read_json(path)
            elif path.suffix == ".jsonl":
                read_jsonl(path)
            else:
                path.read_text(encoding="utf-8")
        return True
    except Exception:
        return False


def _resume_artifact_paths(*, phase: str, stage: str) -> list[Path]:
    phase_stage_paths: dict[tuple[str, str], list[Path]] = {
        ("phase1", "spec-generation"): [Path("input/case_context.json"), Path("case_spec.json")],
        ("phase1", "family-selection"): [Path("input/family_selection.json")],
        ("phase1", "capability-brief"): [Path("input/memory_capability_brief.json")],
        ("phase1", "task-actor-layout"): [Path("input/task_actor_layout.json"), Path("input/story_plan.json")],
        ("phase1", "case-world"): [Path("input/case_world.json")],
        ("phase1", "characters"): [Path("input/characters.json"), Path("input/actor_registry.json")],
        ("phase1", "state-trajectory"): [Path("input/state_trajectory.json")],
        ("phase1", "coverage-spec"): [Path("input/coverage_spec.json")],
        ("phase1", "story-beats"): [Path("input/story_beats.json"), Path("input/official_file_plan.json")],
        ("phase1", "conversation-plan"): [Path("input/conversation_plan.json")],
        ("phase1", "command-plan"): [Path("input/command_plan.jsonl"), Path("execution_plan.json")],
        ("phase1", "execute"): [Path("runtime/execution_result.json"), Path("runtime/executed_commands.jsonl")],
        ("phase1", "collect"): [Path("data/collected_messages.jsonl"), Path("data/openclaw_message_ingress.jsonl")],
        ("phase1", "pre-annotation-validate"): [Path("checks/pre_annotation_validation_report.json")],
        ("phase2", "annotation-gold"): [Path("gold/annotation_gold.jsonl")],
        ("phase2", "semantic-gold"): [Path("gold/task_wiki_semantic_gold.json")],
        ("phase2", "query-benchmark"): [Path("gold/query_benchmark.json")],
        ("phase2", "build-checks"): [Path("checks/eval_manifest.json"), Path("checks/integrity_gate.json")],
        ("phase2", "gold-validate"): [Path("checks/gold_validation_report.json")],
        ("phase2", "replay-runtime"): [Path("predictions/task_wiki_replay_predictions.json")],
        ("phase2", "replay-eval"): [Path("reports/replay_eval.json")],
        ("phase3", "task-wiki-runtime-eval"): [
            Path("runtime/task_wiki_replay/summary.json"),
            Path("runtime/task_wiki_replay/layer_metrics.json"),
            Path("runtime/task_wiki_replay/task_wiki_runtime_predictions.json"),
        ],
        ("phase3", "openclaw-real-baseline-eval"): [
            Path("runtime/openclaw_baseline/answers.json"),
            Path("runtime/openclaw_baseline/evidence_traces.json"),
            Path("runtime/openclaw_baseline/replay_metadata.json"),
            Path("reports/openclaw_baseline_eval.json"),
        ],
        ("phase3", "comparative-score"): [Path("reports/phase3_score.json")],
    }
    return phase_stage_paths.get((phase, stage), [])


def _can_resume_stage(*, case_path: Path, phase: str, stage: str, force: bool = False) -> bool:
    if force:
        return False
    if phase == "phase3" and stage == "openclaw-real-baseline-eval":
        if (case_path / "runtime" / "openclaw_baseline" / "failure.json").exists():
            return False
    paths = _resume_artifact_paths(phase=phase, stage=stage)
    return bool(paths) and _stage_artifacts_readable(case_path, paths)


def _run_resume_stage(
    *,
    phase: str,
    stage: str,
    case_path: Path,
    runner: Callable[[Path], dict[str, Any]],
    force: bool,
) -> tuple[dict[str, Any], bool]:
    started_at = _utc_now_iso()
    if _can_resume_stage(case_path=case_path, phase=phase, stage=stage, force=force):
        paths = [str(case_path / relative_path) for relative_path in _resume_artifact_paths(phase=phase, stage=stage)]
        result = _skipped_stage_result(stage=stage, case_path=case_path, artifact_paths=paths)
        _write_builder_journal(
            case_path,
            {
                "phase": phase,
                "stage": stage,
                "status": "skipped",
                "started_at": started_at,
                "ended_at": _utc_now_iso(),
                "artifact_paths": paths,
                "skipped": True,
            },
        )
        return result, True
    try:
        result = runner(case_path)
    except Exception as exc:
        failure_path = (
            exc.failure_artifact_path
            if isinstance(exc, RuntimeScriptError) and exc.failure_artifact_path is not None
            else _write_stage_failure(phase=phase, stage=stage, error=exc, case_path=case_path)
        )
        _write_builder_journal(
            case_path,
            {
                "phase": phase,
                "stage": stage,
                "status": "failed",
                "started_at": started_at,
                "ended_at": _utc_now_iso(),
                "failure_artifact_path": str(failure_path),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "skipped": False,
            },
        )
        raise
    artifact_paths = _stage_result_artifact_paths(result)
    _write_builder_journal(
        case_path,
        {
            "phase": phase,
            "stage": stage,
            "status": "completed",
            "started_at": started_at,
            "ended_at": _utc_now_iso(),
            "artifact_paths": artifact_paths,
            "skipped": False,
        },
    )
    return result, False


def _read_active_case(dataset_root: str | Path) -> dict[str, Any]:
    dataset_path = _resolve_dataset_root(dataset_root)
    active_case_path = active_case_path_for(dataset_path)
    if not active_case_path.exists():
        raise CliUsageError(
            "当前没有 active case。请先运行 phase1-step --stage spec-generation，或显式提供 --case-dir。"
        )
    payload = read_json(active_case_path)
    case_dir_value = payload.get("case_dir")
    if not isinstance(case_dir_value, str) or not case_dir_value.strip():
        raise CliUsageError("active_case.json 缺少有效的 case_dir。")
    return payload


def _write_active_batch(
    *,
    dataset_root: str | Path,
    batch_id: str,
    batch_dir: str | Path,
    last_completed_phase: str | None = None,
) -> Path:
    dataset_path = _resolve_dataset_root(dataset_root)
    active_batch_path = _active_batch_path_for(dataset_path)
    write_json(
        active_batch_path,
        {
            "batch_id": batch_id,
            "batch_dir": str(batch_dir),
            "last_completed_phase": last_completed_phase,
            "updated_at": _utc_now_iso(),
        },
    )
    return active_batch_path


def _read_active_batch(dataset_root: str | Path) -> dict[str, Any]:
    dataset_path = _resolve_dataset_root(dataset_root)
    active_batch_path = _active_batch_path_for(dataset_path)
    if not active_batch_path.exists():
        raise CliUsageError(
            "当前没有 active batch。请先运行 phase1 --batch-size <N>，或显式提供 --batch-dir。"
        )
    payload = read_json(active_batch_path)
    batch_dir_value = payload.get("batch_dir")
    if not isinstance(batch_dir_value, str) or not batch_dir_value.strip():
        raise CliUsageError("active_batch.json 缺少有效的 batch_dir。")
    return payload


def _resolve_batch_dir(
    *,
    batch_dir: str | Path | None,
    dataset_root: str | Path,
) -> Path:
    if batch_dir is not None:
        return Path(batch_dir)
    active_batch = _read_active_batch(dataset_root)
    return Path(str(active_batch["batch_dir"]))


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
    characters = _characters_from_layout(
        case_context=case_context,
        task_actor_layout=task_actor_layout_artifact,
        case_world=case_world_artifact,
    )
    actor_registry = _actor_registry_from_characters(characters)
    official_file_plan = validate_official_file_plan(
        build_official_file_plan(case_context=case_context, story_plan=story_plan)
    )
    conversation_plan_artifact, conversation_model_call_entries = generate_conversation_plan(
        case_context=case_context,
        case_world_artifact=case_world_artifact,
        story_beats_artifact=story_beats_artifact,
        story_plan=story_plan,
        characters=characters,
        actor_registry=actor_registry,
        official_file_plan=official_file_plan,
    )
    log_path = append_model_call_log(case_path=case_path, entries=conversation_model_call_entries)
    story_plan_path = Path("input") / "story_plan.json"
    task_actor_layout_path = Path("input") / "task_actor_layout.json"
    case_world_path = Path("input") / "case_world.json"
    characters_path = Path("input") / "characters.json"
    registry_path = Path("input") / "actor_registry.json"
    official_file_plan_path = Path("input") / "official_file_plan.json"
    story_beats_path = Path("input") / "story_beats.json"
    conversation_plan_path = Path("input") / "conversation_plan.json"
    write_json(case_path / story_plan_path, story_plan)
    write_json(case_path / task_actor_layout_path, task_actor_layout_artifact)
    write_json(case_path / case_world_path, case_world_artifact)
    write_json(case_path / characters_path, characters)
    write_json(case_path / registry_path, actor_registry)
    write_json(case_path / official_file_plan_path, official_file_plan)
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
            {"artifact_path": str(case_path / official_file_plan_path), "artifact": official_file_plan},
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
    official_file_plan = validate_official_file_plan(
        build_official_file_plan(case_context=case_context, story_plan=story_plan)
    )
    artifact_path = Path("input") / "story_beats.json"
    official_file_plan_path = Path("input") / "official_file_plan.json"
    write_json(case_path / artifact_path, story_beats_artifact)
    write_json(case_path / official_file_plan_path, official_file_plan)
    result = _multi_artifact_result(
        stage="story-beats",
        case_path=case_path,
        artifacts=[
            {"artifact_path": str(case_path / artifact_path), "artifact": story_beats_artifact},
            {"artifact_path": str(case_path / official_file_plan_path), "artifact": official_file_plan},
        ],
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="story-beats",
        )
    )
    return result


def run_phase1_conversation_plan(*, case_dir: str | Path, skip_preflight: bool = False) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="conversation-plan")
    if not skip_preflight:
        _preflight_stage("conversation-plan")
    case_context = _load_case_context(case_path, stage="conversation-plan")
    story_plan = _load_story_plan(case_path, stage="conversation-plan")
    case_world_artifact = validate_case_world_artifact(
        _read_required_json(case_path, Path("input") / "case_world.json", stage="conversation-plan")
    )
    story_beats_artifact = validate_story_beats_artifact(
        _read_required_json(case_path, Path("input") / "story_beats.json", stage="conversation-plan")
    )
    characters = validate_characters(
        _read_required_json(case_path, Path("input") / "characters.json", stage="conversation-plan")
    )
    actor_registry = validate_actor_registry(
        _read_required_json(case_path, Path("input") / "actor_registry.json", stage="conversation-plan")
    )
    official_file_path = case_path / "input" / "official_file_plan.json"
    if official_file_path.exists():
        official_file_plan = validate_official_file_plan(read_json(official_file_path))
    else:
        official_file_plan = validate_official_file_plan(
            build_official_file_plan(case_context=case_context, story_plan=story_plan)
        )
        write_json(official_file_path, official_file_plan)
    try:
        conversation_plan_artifact, model_call_entries = generate_conversation_plan(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_beats_artifact=story_beats_artifact,
            story_plan=story_plan,
            characters=characters,
            actor_registry=actor_registry,
            official_file_plan=official_file_plan,
        )
    except ModelBackendError as exc:
        append_model_call_log(
            case_path=case_path,
            entries=[
                build_model_call_failure_log_entry(
                    stage="conversation-plan",
                    error=exc,
                    case_id=str(case_context["case_id"]),
                    artifact_path="input/conversation_plan.json",
                )
            ],
        )
        raise
    except ModelPayloadValidationError as exc:
        append_model_call_log(
            case_path=case_path,
            entries=[
                build_model_call_validation_failure_log_entry(
                    stage="conversation-plan",
                    error=exc,
                    case_id=str(case_context["case_id"]),
                    artifact_path="input/conversation_plan.json",
                )
            ],
        )
        raise
    log_path = append_model_call_log(case_path=case_path, entries=model_call_entries)
    artifact_path = Path("input") / "conversation_plan.json"
    write_json(case_path / artifact_path, conversation_plan_artifact)
    result = _artifact_result(
        stage="conversation-plan",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=conversation_plan_artifact,
    )
    result["model_call_log_path"] = str(log_path)
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
    openclaw_ingress = _read_required_jsonl(
        case_path,
        Path("data") / "openclaw_message_ingress.jsonl",
        stage="pre-annotation-validate",
    )
    official_file_path = case_path / "input" / "official_file_plan.json"
    official_file_plan = validate_official_file_plan(read_json(official_file_path)) if official_file_path.exists() else None
    validation_report = build_pre_annotation_validation_report(
        case_id=case_context["case_id"],
        story_plan=story_plan,
        collected_messages=collected_messages,
        openclaw_ingress=openclaw_ingress,
        official_file_plan=official_file_plan,
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


def run_phase2_semantic_gold(
    *,
    case_dir: str | Path,
    semantic_gold_mode: str = "auto",
    require_llm: bool = False,
) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    story_plan = context["story_plan"]
    collected_messages = read_jsonl(case_path / "data" / "collected_messages.jsonl")
    annotation_gold_rows = read_jsonl(case_path / "gold" / "annotation_gold.jsonl")
    artifact, model_call_entries = generate_semantic_gold(
        case_context=case_context,
        story_plan=story_plan,
        collected_messages=collected_messages,
        annotation_gold_rows=annotation_gold_rows,
        mode=semantic_gold_mode,
        require_llm=require_llm,
    )
    if model_call_entries:
        log_path = append_model_call_log(case_path=case_path, entries=model_call_entries)
    else:
        log_path = case_path / MODEL_CALL_LOG_PATH
    artifact_path = Path("gold") / "task_wiki_semantic_gold.json"
    write_json(case_path / artifact_path, artifact)
    result = _artifact_result(
        stage="semantic-gold",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=artifact,
    )
    result["model_call_log_path"] = str(log_path)
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=case_context,
            last_completed_stage="semantic-gold",
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


def _run_node_json_script(
    *,
    script_path: Path,
    case_path: Path,
    phase: str,
    stage: str,
    accept_exit_codes: set[int] | None = None,
) -> dict[str, Any]:
    accepted = accept_exit_codes or {0}
    resolved_script_path = script_path if script_path.is_absolute() else Path(__file__).resolve().parents[1] / script_path
    command = [
        "node",
        str(resolved_script_path),
        "--case-dir",
        str(case_path),
        "--semantic-gold",
        "rule",
        "--json",
    ]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in accepted:
        message = (
            "Phase 3 runtime script failed: "
            f"command={' '.join(command)} returncode={completed.returncode} stderr={completed.stderr.strip()}"
        )
        failure_path = _write_stage_failure(
            phase=phase,
            stage=stage,
            error=RuntimeError(message),
            case_path=case_path,
            extra={
                "command": command,
                "returncode": completed.returncode,
                "stdout": _truncate_text(completed.stdout),
                "stderr": _truncate_text(completed.stderr),
            },
        )
        raise RuntimeScriptError(
            message,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            failure_artifact_path=failure_path,
        )
    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError(f"Phase 3 runtime script returned empty stdout: command={' '.join(command)}")
    try:
        return json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Phase 3 runtime script did not return JSON: command={' '.join(command)} stdout={stdout}") from exc


def run_phase3_task_wiki_runtime_eval(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    summary = _run_node_json_script(
        script_path=Path("feishu_task_wiki_benchmark_builder") / "runtime" / "task_wiki_runtime_eval.mjs",
        case_path=case_path,
        phase="phase3",
        stage="task-wiki-runtime-eval",
        accept_exit_codes={0, 2},
    )
    artifact_path = Path("runtime") / "task_wiki_replay" / "summary.json"
    result = _artifact_result(
        stage="task-wiki-runtime-eval",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=summary,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=context["case_context"],
            last_completed_stage="task-wiki-runtime-eval",
        )
    )
    return result


def run_phase3_openclaw_baseline_eval(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    summary = _run_node_json_script(
        script_path=Path("feishu_task_wiki_benchmark_builder") / "runtime" / "openclaw_baseline_eval.mjs",
        case_path=case_path,
        phase="phase3",
        stage="openclaw-real-baseline-eval",
    )
    artifact_path = Path("reports") / "openclaw_baseline_eval.json"
    result = _artifact_result(
        stage="openclaw-real-baseline-eval",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=summary,
    )
    result["active_case_path"] = str(
        _write_active_case(
            case_path=case_path,
            case_context=context["case_context"],
            last_completed_stage="openclaw-real-baseline-eval",
        )
    )
    return result


def run_phase3_comparative_score(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_runtime_context(case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    comparative_eval = build_comparative_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        query_benchmark=read_json(case_path / "gold" / "query_benchmark.json"),
        semantic_gold=read_json(case_path / "gold" / "task_wiki_semantic_gold.json"),
        collected_messages=read_jsonl(case_path / "data" / "collected_messages.jsonl"),
        task_wiki_metrics=read_json(case_path / "runtime" / "task_wiki_replay" / "layer_metrics.json"),
        task_wiki_predictions=read_json(
            case_path / "runtime" / "task_wiki_replay" / "task_wiki_runtime_predictions.json"
        ),
        openclaw_answers=read_json(case_path / "runtime" / "openclaw_baseline" / "answers.json"),
        openclaw_baseline_report=read_json(case_path / "reports" / "openclaw_baseline_eval.json"),
    )
    artifact_path = Path("reports") / "phase3_score.json"
    write_json(case_path / artifact_path, comparative_eval)
    result = _artifact_result(
        stage="comparative-score",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=comparative_eval,
    )
    result["active_case_path"] = str(
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="comparative-score")
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


def current_batch(*, dataset_root: str | Path = DEFAULT_DATASET_ROOT) -> dict[str, Any]:
    dataset_path = _resolve_dataset_root(dataset_root)
    active_batch = _read_active_batch(dataset_path)
    return {"dataset_root": str(dataset_path), **active_batch}


def _manifest_path_for_batch(batch_dir: Path) -> Path:
    return batch_dir / "batch_manifest.json"


def _run_summary_path_for_batch(batch_dir: Path) -> Path:
    return batch_dir / "batch_run_summary.json"


def _read_batch_manifest(batch_dir: Path) -> dict[str, Any]:
    manifest_path = _manifest_path_for_batch(batch_dir)
    if not manifest_path.exists():
        raise CliUsageError(f"batch 缺少 batch_manifest.json: {batch_dir}")
    manifest = read_json(manifest_path)
    if not isinstance(manifest.get("cases"), list):
        raise CliUsageError("batch_manifest.json 缺少有效的 cases[]。")
    return manifest


def _write_batch_manifest(batch_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _utc_now_iso()
    write_json(_manifest_path_for_batch(batch_dir), manifest)


def _read_batch_run_summary(batch_dir: Path) -> dict[str, Any]:
    path = _run_summary_path_for_batch(batch_dir)
    if path.exists():
        return read_json(path)
    return {"batch_id": batch_dir.name, "batch_dir": str(batch_dir), "phases": {}, "updated_at": _utc_now_iso()}


def _write_batch_phase_summary(
    *,
    batch_dir: Path,
    phase: str,
    phase_summary: dict[str, Any],
) -> Path:
    summary = _read_batch_run_summary(batch_dir)
    summary["batch_id"] = batch_dir.name
    summary["batch_dir"] = str(batch_dir)
    summary.setdefault("phases", {})[phase] = phase_summary
    summary["updated_at"] = _utc_now_iso()
    path = _run_summary_path_for_batch(batch_dir)
    write_json(path, summary)
    return path


def _validate_family_id(family_id: str) -> str:
    if family_id not in FORMAL_FAMILY_IDS:
        raise CliUsageError(f"不支持的 family: {family_id}。可用值: {', '.join(FORMAL_FAMILY_IDS)}")
    return family_id


def _family_sequence(
    *,
    batch_size: int,
    families: str | None,
    family_id: str | None,
) -> tuple[list[str], str]:
    if family_id and families and families != "all":
        raise CliUsageError("--family-id 和 --families 不能同时指定不同 family 策略。")
    if family_id:
        selected = [_validate_family_id(family_id)]
        return [selected[0] for _ in range(batch_size)], f"single:{selected[0]}"
    raw_policy = families or "all"
    if raw_policy == "all":
        selected = list(FORMAL_FAMILY_IDS)
    else:
        selected = [_validate_family_id(value.strip()) for value in raw_policy.split(",") if value.strip()]
        if not selected:
            raise CliUsageError("--families 不能为空。")
    return [selected[index % len(selected)] for index in range(batch_size)], raw_policy


def _batch_case_entry(
    *,
    case_id: str | None,
    case_dir: str | Path | None,
    family_id: str,
    seed: int,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "case_id": case_id,
        "case_dir": str(case_dir) if case_dir is not None else None,
        "family_id": family_id,
        "seed": seed,
        "status": status,
        "phase1": {},
        "phase2": {},
        "phase3": {},
    }
    if error:
        entry["error"] = error
    return entry


def _phase_status_summary(*, started_at: str, cases: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    completed = [case for case in cases if case.get(phase, {}).get("status") == "completed"]
    failed = [case for case in cases if case.get(phase, {}).get("status") == "failed"]
    skipped = [case for case in cases if case.get(phase, {}).get("status") == "skipped"]
    return {
        "phase": phase,
        "status": "failed" if failed else "completed",
        "started_at": started_at,
        "completed_at": _utc_now_iso(),
        "case_count": len(cases),
        "completed_case_count": len(completed),
        "failed_case_count": len(failed),
        "skipped_case_count": len(skipped),
        "errors": [
            {
                "case_id": case.get("case_id"),
                "case_dir": case.get("case_dir"),
                "error": case.get(phase, {}).get("error") or case.get("error"),
            }
            for case in failed
        ],
    }


def _phase3_metric_value(score: dict[str, Any], system_id: str, metric: str) -> float | None:
    value = score.get("aggregate_scores", {}).get(system_id, {}).get(metric)
    if isinstance(value, int | float):
        return float(value)
    value = score.get("systems", {}).get(system_id, {}).get("metrics", {}).get(metric)
    if isinstance(value, int | float):
        return float(value)
    return None


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _aggregate_phase3_scores(*, batch_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    metrics = (
        "query_success_rate",
        "evidence_output_rate",
        "evidence_precision",
        "evidence_recall",
        "safety_score",
        "efficiency_score",
        "avg_answer_token_count",
        "avg_estimated_steps",
        "avg_estimated_time_seconds",
    )
    systems = ("task_wiki_3_layer", "openclaw_original")
    family_scores: dict[str, list[dict[str, Any]]] = {}
    scored_cases = []
    for case in manifest.get("cases", []):
        case_dir = case.get("case_dir")
        if not case_dir:
            continue
        score_path = Path(str(case_dir)) / "reports" / "phase3_score.json"
        if not score_path.exists():
            continue
        score = read_json(score_path)
        family = str(case.get("family_id") or score.get("family_id") or "unknown")
        family_scores.setdefault(family, []).append(score)
        scored_cases.append(
            {
                "case_id": case.get("case_id") or score.get("case_id"),
                "case_dir": str(case_dir),
                "family_id": family,
                "phase3_score_path": str(score_path),
            }
        )
    family_level: dict[str, Any] = {}
    global_failure_counts: dict[str, dict[str, int]] = {system: {} for system in systems}
    for family, scores in sorted(family_scores.items()):
        family_level[family] = {"case_count": len(scores), "systems": {}, "deltas": {}, "failure_reason_breakdown": {}}
        for system in systems:
            system_metrics = {
                metric: _average(
                    [
                        metric_value
                        for score in scores
                        if (metric_value := _phase3_metric_value(score, system, metric)) is not None
                    ]
                )
                for metric in metrics
            }
            family_level[family]["systems"][system] = system_metrics
            counts: dict[str, int] = {}
            for score in scores:
                breakdown = score.get("failure_reason_breakdown", {}).get(system, {})
                if isinstance(breakdown, dict):
                    for reason, count in breakdown.items():
                        if isinstance(count, int | float):
                            counts[str(reason)] = counts.get(str(reason), 0) + int(count)
                            global_failure_counts[system][str(reason)] = (
                                global_failure_counts[system].get(str(reason), 0) + int(count)
                            )
            family_level[family]["failure_reason_breakdown"][system] = dict(sorted(counts.items()))
        delta_keys = {
            key
            for score in scores
            for key, value in score.get("deltas", {}).items()
            if isinstance(value, int | float)
        }
        family_level[family]["deltas"] = {
            key: _average([float(score.get("deltas", {}).get(key)) for score in scores if isinstance(score.get("deltas", {}).get(key), int | float)])
            for key in sorted(delta_keys)
        }
    return {
        "batch_id": manifest.get("batch_id") or batch_dir.name,
        "batch_dir": str(batch_dir),
        "score_artifact": "batch_phase3_score",
        "case_count": int(manifest.get("case_count") or len(manifest.get("cases", []))),
        "scored_case_count": len(scored_cases),
        "cases": scored_cases,
        "family_level_scores": family_level,
        "failure_reason_breakdown": {
            system: dict(sorted(counts.items())) for system, counts in global_failure_counts.items()
        },
        "updated_at": _utc_now_iso(),
    }


PHASE2_STAGE_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "annotation-gold": run_phase2_annotation_gold,
    "semantic-gold": run_phase2_semantic_gold,
    "query-benchmark": run_phase2_query_benchmark,
    "build-checks": run_phase2_build_checks,
    "gold-validate": run_phase2_gold_validate,
    "replay-runtime": run_phase2_replay_runtime,
    "replay-eval": run_phase2_replay_eval,
}


def run_phase2_step(
    *,
    stage: str,
    case_dir: str | Path | None = None,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    semantic_gold_mode: str = "auto",
    require_llm: bool = False,
) -> dict[str, Any]:
    if stage not in PHASE2_STAGE_REGISTRY:
        raise CliUsageError(f"不支持的 phase2 stage: {stage}")
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage=stage)
    if stage == "semantic-gold":
        return run_phase2_semantic_gold(
            case_dir=resolved_case_dir,
            semantic_gold_mode=semantic_gold_mode,
            require_llm=require_llm,
        )
    return PHASE2_STAGE_REGISTRY[stage](case_dir=resolved_case_dir)


def compile_phase1(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    difficulty: str | None = None,
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
    force: bool = False,
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    dataset_path = _resolve_dataset_root(dataset_root)
    skipped_stages: list[str] = []
    candidate_case_path: Path | None = None
    if not force:
        if seed is not None or family_id is not None:
            candidate_case_path, _ = _provisional_case_context_path(
                dataset_root=dataset_path,
                seed=seed,
                requested_family_id=family_id,
            )
        elif active_case_path_for(dataset_path).exists():
            active_case = _read_active_case(dataset_path)
            candidate_case_path = Path(str(active_case["case_dir"]))
    if (
        candidate_case_path is not None
        and _can_resume_stage(case_path=candidate_case_path, phase="phase1", stage="spec-generation", force=force)
    ):
        case_path = candidate_case_path
        case_context = _load_case_context(case_path, stage="phase1")
        _write_active_case(case_path=case_path, case_context=case_context, last_completed_stage="spec-generation")
        _write_builder_journal(
            case_path,
            {
                "phase": "phase1",
                "stage": "spec-generation",
                "status": "skipped",
                "started_at": _utc_now_iso(),
                "ended_at": _utc_now_iso(),
                "artifact_paths": [
                    str(case_path / relative_path)
                    for relative_path in _resume_artifact_paths(phase="phase1", stage="spec-generation")
                ],
                "skipped": True,
            },
        )
        skipped_stages.append("spec-generation")
    else:
        try:
            preflight_model_backend()
            spec_generation_result = run_phase1_spec_generation(
                dataset_root=dataset_path,
                seed=seed,
                family_id=family_id,
                difficulty=difficulty,
                comparison_target=comparison_target,
                skip_preflight=True,
            )
        except Exception as exc:
            _write_stage_failure(
                phase="phase1",
                stage="spec-generation",
                error=exc,
                dataset_root=dataset_path,
            )
            raise
        case_path = Path(spec_generation_result["case_dir"])
        _write_builder_journal(
            case_path,
            {
                "phase": "phase1",
                "stage": "spec-generation",
                "status": "completed",
                "started_at": _utc_now_iso(),
                "ended_at": _utc_now_iso(),
                "artifact_paths": _stage_result_artifact_paths(spec_generation_result),
                "skipped": False,
            },
        )

    phase1_runners: dict[str, Callable[[Path], dict[str, Any]]] = {
        "family-selection": lambda case_dir: run_phase1_family_selection(case_dir=case_dir),
        "capability-brief": lambda case_dir: run_phase1_capability_brief(case_dir=case_dir),
        "task-actor-layout": lambda case_dir: run_phase1_task_actor_layout(case_dir=case_dir, skip_preflight=True),
        "case-world": lambda case_dir: run_phase1_case_world(case_dir=case_dir),
        "characters": lambda case_dir: run_phase1_characters(case_dir=case_dir),
        "state-trajectory": lambda case_dir: run_phase1_state_trajectory(case_dir=case_dir),
        "coverage-spec": lambda case_dir: run_phase1_coverage_spec(case_dir=case_dir),
        "story-beats": lambda case_dir: run_phase1_story_beats(case_dir=case_dir),
        "conversation-plan": lambda case_dir: run_phase1_conversation_plan(case_dir=case_dir, skip_preflight=True),
        "command-plan": lambda case_dir: run_phase1_command_plan(case_dir=case_dir),
        "execute": lambda case_dir: run_phase1_execute(case_dir=case_dir),
        "collect": lambda case_dir: run_phase1_collect(case_dir=case_dir),
        "pre-annotation-validate": lambda case_dir: run_phase1_pre_annotation_validate(case_dir=case_dir),
    }
    for stage in PHASE1_STAGE_ORDER[1:]:
        _, skipped = _run_resume_stage(
            phase="phase1",
            stage=stage,
            case_path=case_path,
            runner=phase1_runners[stage],
            force=force,
        )
        if skipped:
            skipped_stages.append(stage)
    case_context = _load_case_context(case_path, stage="phase1")
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "completed_stages": list(PHASE1_STAGE_ORDER),
        "skipped_stages": skipped_stages,
        "model_call_log_path": str(case_path / MODEL_CALL_LOG_PATH),
        "active_case_path": str(active_case_path_for(dataset_root_for_case(case_path))),
    }


def compile_phase2(
    *,
    case_dir: str | Path | None = None,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    semantic_gold_mode: str = "auto",
    require_llm: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage="phase2")
    case_path = Path(resolved_case_dir)
    skipped_stages: list[str] = []
    phase2_runners: dict[str, Callable[[Path], dict[str, Any]]] = {
        "annotation-gold": lambda case_dir: run_phase2_annotation_gold(case_dir=case_dir),
        "semantic-gold": lambda case_dir: run_phase2_semantic_gold(
            case_dir=case_dir,
            semantic_gold_mode=semantic_gold_mode,
            require_llm=require_llm,
        ),
        "query-benchmark": lambda case_dir: run_phase2_query_benchmark(case_dir=case_dir),
        "build-checks": lambda case_dir: run_phase2_build_checks(case_dir=case_dir),
        "gold-validate": lambda case_dir: run_phase2_gold_validate(case_dir=case_dir),
        "replay-runtime": lambda case_dir: run_phase2_replay_runtime(case_dir=case_dir),
        "replay-eval": lambda case_dir: run_phase2_replay_eval(case_dir=case_dir),
    }
    for stage in PHASE2_STAGE_ORDER:
        _, skipped = _run_resume_stage(
            phase="phase2",
            stage=stage,
            case_path=case_path,
            runner=phase2_runners[stage],
            force=force,
        )
        if skipped:
            skipped_stages.append(stage)
    case_context = _load_case_context(case_path, stage="phase2")
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "completed_stages": list(PHASE2_STAGE_ORDER),
        "skipped_stages": skipped_stages,
        "active_case_path": str(active_case_path_for(dataset_root_for_case(case_path))),
    }


def compile_phase3(
    *,
    case_dir: str | Path | None = None,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    force: bool = False,
) -> dict[str, Any]:
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage="phase3")
    case_path = Path(resolved_case_dir)
    skipped_stages: list[str] = []
    phase3_runners: dict[str, Callable[[Path], dict[str, Any]]] = {
        "task-wiki-runtime-eval": lambda case_dir: run_phase3_task_wiki_runtime_eval(case_dir=case_dir),
        "openclaw-real-baseline-eval": lambda case_dir: run_phase3_openclaw_baseline_eval(case_dir=case_dir),
        "comparative-score": lambda case_dir: run_phase3_comparative_score(case_dir=case_dir),
    }
    for stage in PHASE3_STAGE_ORDER:
        try:
            _, skipped = _run_resume_stage(
                phase="phase3",
                stage=stage,
                case_path=case_path,
                runner=phase3_runners[stage],
                force=force,
            )
        except Exception as exc:
            write_json(
                case_path / "reports" / "phase3_failure.json",
                {
                    "case_dir": str(case_path),
                    "phase": "phase3",
                    "failed_stage": stage,
                    "status": "failed",
                    "failed_at": _utc_now_iso(),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise
        if skipped:
            skipped_stages.append(stage)
    case_context = _load_case_context(case_path, stage="phase3")
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "completed_stages": list(PHASE3_STAGE_ORDER),
        "skipped_stages": skipped_stages,
        "active_case_path": str(active_case_path_for(dataset_root_for_case(case_path))),
    }


def compile_phase1_batch(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    batch_size: int,
    batch_id: str | None = None,
    seed: int | None = None,
    difficulty: str | None = None,
    family_id: str | None = None,
    families: str | None = "all",
    comparison_target: str = "default_memory_architectures",
    continue_on_error: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise CliUsageError("--batch-size 必须大于 0。")
    difficulty = _resolve_cli_difficulty(difficulty)
    dataset_path = _resolve_dataset_root(dataset_root)
    ensure_dir(dataset_path)
    normalized_batch_id = batch_id or _build_batch_id()
    batch_dir = _batch_dir_for(dataset_path, normalized_batch_id)
    if _manifest_path_for_batch(batch_dir).exists():
        raise CliUsageError(f"batch 已存在，避免覆盖: {batch_dir}")
    ensure_dir(batch_dir)
    ensure_dir(batch_dir / "reports")
    base_seed = normalize_seed(seed)
    family_ids, family_policy = _family_sequence(batch_size=batch_size, families=families, family_id=family_id)
    generation_plan = build_dataset_generation_plan(
        dataset_size=batch_size,
        seed=base_seed,
        difficulty=difficulty,
    )
    generation_plan["batch_id"] = normalized_batch_id
    generation_plan["family_policy"] = family_policy
    generation_plan["case_plan"] = [
        {"index": index, "seed": base_seed + index, "family_id": selected_family_id}
        for index, selected_family_id in enumerate(family_ids)
    ]
    write_json(batch_dir / "dataset_generation_plan.json", generation_plan)
    cases = [
        _batch_case_entry(
            case_id=build_case_id(base_seed + index, selected_family_id),
            case_dir=case_dir_for(batch_dir, build_case_id(base_seed + index, selected_family_id)),
            family_id=selected_family_id,
            seed=base_seed + index,
            status="planned",
        )
        for index, selected_family_id in enumerate(family_ids)
    ]
    manifest = {
        "batch_id": normalized_batch_id,
        "dataset_root": str(dataset_path),
        "batch_dir": str(batch_dir),
        "difficulty": difficulty,
        "base_seed": base_seed,
        "family_policy": family_policy,
        "case_count": batch_size,
        "cases": cases,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }
    _write_batch_manifest(batch_dir, manifest)
    active_batch_path = _write_active_batch(
        dataset_root=dataset_path,
        batch_id=normalized_batch_id,
        batch_dir=batch_dir,
        last_completed_phase=None,
    )
    started_at = _utc_now_iso()
    first_error: Exception | None = None
    for index, case in enumerate(cases):
        try:
            result = compile_phase1(
                dataset_root=batch_dir,
                seed=int(case["seed"]),
                difficulty=difficulty,
                family_id=str(case["family_id"]),
                comparison_target=comparison_target,
                force=force,
            )
            case["case_id"] = result["case_id"]
            case["case_dir"] = result["case_dir"]
            case["status"] = "completed"
            case["phase1"] = {
                "status": "completed",
                "completed_stages": result["completed_stages"],
                "outputs": {
                    "case_dir": result["case_dir"],
                    "model_call_log_path": result["model_call_log_path"],
                    "active_case_path": result["active_case_path"],
                },
                "completed_at": _utc_now_iso(),
            }
        except Exception as exc:
            case["status"] = "failed"
            case["phase1"] = {"status": "failed", "error": str(exc), "completed_at": _utc_now_iso()}
            first_error = exc
            _write_batch_manifest(batch_dir, manifest)
            if not continue_on_error:
                break
        finally:
            cases[index] = case
            _write_batch_manifest(batch_dir, manifest)
    phase_summary = _phase_status_summary(started_at=started_at, cases=cases, phase=BATCH_PHASE1_STAGE)
    summary_path = _write_batch_phase_summary(batch_dir=batch_dir, phase=BATCH_PHASE1_STAGE, phase_summary=phase_summary)
    if first_error is None:
        active_batch_path = _write_active_batch(
            dataset_root=dataset_path,
            batch_id=normalized_batch_id,
            batch_dir=batch_dir,
            last_completed_phase=BATCH_PHASE1_STAGE,
        )
    result = {
        "batch_id": normalized_batch_id,
        "batch_dir": str(batch_dir),
        "batch_manifest_path": str(_manifest_path_for_batch(batch_dir)),
        "batch_run_summary_path": str(summary_path),
        "active_batch_path": str(active_batch_path),
        "case_count": batch_size,
        "completed_case_count": phase_summary["completed_case_count"],
        "failed_case_count": phase_summary["failed_case_count"],
        "cases": cases,
    }
    if first_error is not None and not continue_on_error:
        raise CliUsageError(f"phase1 batch 在第 {phase_summary['completed_case_count'] + 1} 个 case 失败: {first_error}")
    return result


def compile_phase2_batch(
    *,
    batch_dir: str | Path,
    semantic_gold_mode: str = "auto",
    require_llm: bool = False,
    continue_on_error: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    batch_path = Path(batch_dir)
    manifest = _read_batch_manifest(batch_path)
    cases = list(manifest["cases"])
    started_at = _utc_now_iso()
    first_error: Exception | None = None
    for case in cases:
        if case.get("status") == "failed" or not case.get("case_dir"):
            case["phase2"] = {"status": "skipped", "reason": "phase1_failed_or_missing_case_dir"}
            continue
        try:
            result = compile_phase2(
                case_dir=str(case["case_dir"]),
                semantic_gold_mode=semantic_gold_mode,
                require_llm=require_llm,
                force=force,
            )
            case["phase2"] = {
                "status": "completed",
                "completed_stages": result["completed_stages"],
                "outputs": {
                    "annotation_gold": str(Path(str(case["case_dir"])) / "gold" / "annotation_gold.jsonl"),
                    "semantic_gold": str(Path(str(case["case_dir"])) / "gold" / "task_wiki_semantic_gold.json"),
                    "query_benchmark": str(Path(str(case["case_dir"])) / "gold" / "query_benchmark.json"),
                    "replay_eval": str(Path(str(case["case_dir"])) / "reports" / "replay_eval.json"),
                },
                "completed_at": _utc_now_iso(),
            }
        except Exception as exc:
            case["phase2"] = {"status": "failed", "error": str(exc), "completed_at": _utc_now_iso()}
            first_error = exc
            _write_batch_manifest(batch_path, manifest)
            if not continue_on_error:
                break
        finally:
            _write_batch_manifest(batch_path, manifest)
    phase_summary = _phase_status_summary(started_at=started_at, cases=cases, phase=BATCH_PHASE2_STAGE)
    reports_dir = batch_path / "reports"
    write_json(reports_dir / "batch_phase2_summary.json", phase_summary)
    summary_path = _write_batch_phase_summary(batch_dir=batch_path, phase=BATCH_PHASE2_STAGE, phase_summary=phase_summary)
    if first_error is None:
        _write_active_batch(
            dataset_root=Path(str(manifest["dataset_root"])),
            batch_id=str(manifest["batch_id"]),
            batch_dir=batch_path,
            last_completed_phase=BATCH_PHASE2_STAGE,
        )
    result = {
        "batch_id": manifest["batch_id"],
        "batch_dir": str(batch_path),
        "batch_phase2_summary_path": str(reports_dir / "batch_phase2_summary.json"),
        "batch_run_summary_path": str(summary_path),
        **phase_summary,
    }
    if first_error is not None and not continue_on_error:
        raise CliUsageError(f"phase2 batch 失败: {first_error}")
    return result


def compile_phase3_batch(
    *,
    batch_dir: str | Path,
    continue_on_error: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    batch_path = Path(batch_dir)
    manifest = _read_batch_manifest(batch_path)
    cases = list(manifest["cases"])
    started_at = _utc_now_iso()
    first_error: Exception | None = None
    for case in cases:
        if case.get("status") == "failed" or not case.get("case_dir"):
            case["phase3"] = {"status": "skipped", "reason": "phase1_failed_or_missing_case_dir"}
            continue
        try:
            result = compile_phase3(case_dir=str(case["case_dir"]), force=force)
            case["phase3"] = {
                "status": "completed",
                "completed_stages": result["completed_stages"],
                "outputs": {
                    "phase3_score": str(Path(str(case["case_dir"])) / "reports" / "phase3_score.json"),
                },
                "completed_at": _utc_now_iso(),
            }
        except Exception as exc:
            case["phase3"] = {"status": "failed", "error": str(exc), "completed_at": _utc_now_iso()}
            first_error = exc
            _write_batch_manifest(batch_path, manifest)
            if not continue_on_error:
                break
        finally:
            _write_batch_manifest(batch_path, manifest)
    phase_summary = _phase_status_summary(started_at=started_at, cases=cases, phase=BATCH_PHASE3_STAGE)
    aggregate_score = _aggregate_phase3_scores(batch_dir=batch_path, manifest=manifest)
    reports_dir = batch_path / "reports"
    score_path = reports_dir / "batch_phase3_score.json"
    write_json(score_path, aggregate_score)
    summary_path = _write_batch_phase_summary(batch_dir=batch_path, phase=BATCH_PHASE3_STAGE, phase_summary=phase_summary)
    if first_error is None:
        _write_active_batch(
            dataset_root=Path(str(manifest["dataset_root"])),
            batch_id=str(manifest["batch_id"]),
            batch_dir=batch_path,
            last_completed_phase=BATCH_PHASE3_STAGE,
        )
    result = {
        "batch_id": manifest["batch_id"],
        "batch_dir": str(batch_path),
        "batch_phase3_score_path": str(score_path),
        "batch_run_summary_path": str(summary_path),
        **phase_summary,
        "aggregate_score": aggregate_score,
    }
    if first_error is not None and not continue_on_error:
        raise CliUsageError(f"phase3 batch 失败: {first_error}")
    return result


def build_all(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    difficulty: str | None = None,
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
    force: bool = False,
) -> dict[str, Any]:
    difficulty = _resolve_cli_difficulty(difficulty)
    phase1 = compile_phase1(
        dataset_root=dataset_root,
        seed=seed,
        difficulty=difficulty,
        family_id=family_id,
        comparison_target=comparison_target,
        force=force,
    )
    phase2 = compile_phase2(case_dir=phase1["case_dir"], force=force)
    phase3 = compile_phase3(case_dir=phase1["case_dir"], force=force)
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
    current_batch_parser = subparsers.add_parser("current-batch")
    current_batch_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))

    phase1_step_parser = subparsers.add_parser("phase1-step")
    phase1_step_parser.add_argument("--stage", choices=PHASE1_STAGE_CHOICES, required=True)
    phase1_step_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    phase1_step_parser.add_argument("--case-dir")
    phase1_step_parser.add_argument("--seed", type=int)
    phase1_step_parser.add_argument("--family-id")
    phase1_step_parser.add_argument("--difficulty", default=default_difficulty)
    phase1_step_parser.add_argument("--comparison-target", default="default_memory_architectures")

    phase2_step_parser = subparsers.add_parser("phase2-step")
    phase2_step_parser.add_argument("--stage", choices=PHASE2_STAGE_ORDER, required=True)
    phase2_step_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    phase2_step_parser.add_argument("--case-dir")
    phase2_step_parser.add_argument("--semantic-gold", choices=("auto", "llm", "rule", "off"), default="auto")
    phase2_step_parser.add_argument("--require-llm", action="store_true")

    for name in ("phase1", "build-all"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
        subparser.add_argument("--seed", type=int)
        subparser.add_argument("--difficulty", default=default_difficulty)
        subparser.add_argument("--family-id")
        subparser.add_argument("--comparison-target", default="default_memory_architectures")
        subparser.add_argument("--force", action="store_true")
        if name == "phase1":
            subparser.add_argument("--batch-size", type=int)
            subparser.add_argument("--batch-id")
            subparser.add_argument("--families", default="all")
            subparser.add_argument("--continue-on-error", action="store_true")

    for name in ("phase2", "phase3"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
        subparser.add_argument("--case-dir")
        subparser.add_argument("--batch-dir")
        subparser.add_argument("--continue-on-error", action="store_true")
        subparser.add_argument("--force", action="store_true")
        if name == "phase2":
            subparser.add_argument("--semantic-gold", choices=("auto", "llm", "rule", "off"), default="auto")
            subparser.add_argument("--require-llm", action="store_true")

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
        elif args.command == "current-batch":
            result = current_batch(dataset_root=args.dataset_root)
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
        elif args.command == "phase2-step":
            result = run_phase2_step(
                stage=args.stage,
                case_dir=args.case_dir,
                dataset_root=args.dataset_root,
                semantic_gold_mode=args.semantic_gold,
                require_llm=args.require_llm,
            )
        elif args.command == "phase1":
            if args.batch_size is not None:
                result = compile_phase1_batch(
                    dataset_root=args.dataset_root,
                    batch_size=args.batch_size,
                    batch_id=args.batch_id,
                    seed=args.seed,
                    difficulty=args.difficulty,
                    family_id=args.family_id,
                    families=args.families,
                    comparison_target=args.comparison_target,
                    continue_on_error=args.continue_on_error,
                    force=args.force,
                )
            else:
                result = compile_phase1(
                    dataset_root=args.dataset_root,
                    seed=args.seed,
                    difficulty=args.difficulty,
                    family_id=args.family_id,
                    comparison_target=args.comparison_target,
                    force=args.force,
                )
        elif args.command == "phase2":
            if args.case_dir and args.batch_dir:
                raise CliUsageError("--case-dir 不能和 --batch-dir 同时使用。")
            if args.batch_dir:
                result = compile_phase2_batch(
                    batch_dir=_resolve_batch_dir(
                        batch_dir=args.batch_dir,
                        dataset_root=args.dataset_root,
                    ),
                    semantic_gold_mode=args.semantic_gold,
                    require_llm=args.require_llm,
                    continue_on_error=args.continue_on_error,
                    force=args.force,
                )
            else:
                result = compile_phase2(
                    case_dir=args.case_dir,
                    dataset_root=args.dataset_root,
                    semantic_gold_mode=args.semantic_gold,
                    require_llm=args.require_llm,
                    force=args.force,
                )
        elif args.command == "phase3":
            if args.case_dir and args.batch_dir:
                raise CliUsageError("--case-dir 不能和 --batch-dir 同时使用。")
            if args.batch_dir:
                result = compile_phase3_batch(
                    batch_dir=_resolve_batch_dir(
                        batch_dir=args.batch_dir,
                        dataset_root=args.dataset_root,
                    ),
                    continue_on_error=args.continue_on_error,
                    force=args.force,
                )
            else:
                result = compile_phase3(case_dir=args.case_dir, dataset_root=args.dataset_root, force=args.force)
        elif args.command == "build-all":
            result = build_all(
                dataset_root=args.dataset_root,
                seed=args.seed,
                difficulty=args.difficulty,
                family_id=args.family_id,
                comparison_target=args.comparison_target,
                force=args.force,
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
        elif args.command == "phase2-step":
            stage_label = f"phase2-step::{args.stage}"
        elif args.command == "phase1":
            stage_label = "phase1 预检或模型阶段"
        elif args.command == "phase2":
            stage_label = "phase2 模型阶段"
        elif args.command == "build-all":
            stage_label = "build-all / phase1 预检或模型阶段"
        parser.exit(2, f"{_build_model_backend_error_message(stage_label=stage_label, error=exc)}\n")
    except ModelPayloadValidationError as exc:
        stage_label = "builder payload 校验阶段"
        if args.command == "phase1-step":
            stage_label = f"phase1-step::{args.stage}"
        elif args.command == "phase2-step":
            stage_label = f"phase2-step::{args.stage}"
        elif args.command == "phase1":
            stage_label = "phase1 payload 校验阶段"
        elif args.command == "phase2":
            stage_label = "phase2 payload 校验阶段"
        elif args.command == "build-all":
            stage_label = "build-all / phase1 payload 校验阶段"
        parser.exit(2, f"{stage_label} 失败：\n{exc}\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
