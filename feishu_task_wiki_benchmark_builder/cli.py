from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import BUILDER_DEFAULT_DIFFICULTY, DEFAULT_DATASET_ROOT
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
from .runtime.collector import collect_messages
from .runtime.executor import execute_command_plan
from .schemas import (
    validate_case_context,
    validate_pre_annotation_report,
    validate_replay_eval,
    validate_story_plan,
)
from .stages.annotation_gold import build_annotation_gold
from .stages.baseline_eval import build_baseline_eval
from .stages.benchmark_report import build_benchmark_report
from .stages.case_context import generate_case_context
from .stages.command_plan import build_command_plan
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
from .stages.observed_validation import build_pre_annotation_validation_report
from .stages.query_benchmark import build_query_benchmark
from .stages.replay_eval import build_replay_eval
from .stages.story_plan import generate_story_plan
from .stages.value_eval import build_value_eval


class ArtifactDependencyError(FileNotFoundError):
    """Raised when a required artifact for a stage is missing."""


class CliUsageError(ValueError):
    """Raised when a CLI command is missing required explicit inputs."""


PHASE1_STAGE_ORDER = (
    "case-context",
    "story-plan",
    "command-plan",
    "execute",
    "collect",
    "pre-annotation-validate",
)


def _resolve_dataset_root(dataset_root: str | Path | None) -> Path:
    return Path(dataset_root) if dataset_root is not None else DEFAULT_DATASET_ROOT


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
    difficulty: str = "medium",
    comparison_target: str = "default_memory_architectures",
    skip_preflight: bool = False,
) -> dict[str, Any]:
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
    artifact_path = Path("input") / "story_plan.json"
    write_json(case_path / artifact_path, story_plan)
    result = _artifact_result(
        stage="story-plan",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=story_plan,
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


def run_phase1_command_plan(*, case_dir: str | Path) -> dict[str, Any]:
    case_path = _require_case_path(case_dir, stage="command-plan")
    case_context = _load_case_context(case_path, stage="command-plan")
    story_plan = _load_story_plan(case_path, stage="command-plan")
    command_plan = build_command_plan(story_plan=story_plan)
    artifact_path = Path("input") / "command_plan.jsonl"
    write_jsonl(case_path / artifact_path, command_plan)
    result = _artifact_result(
        stage="command-plan",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=command_plan,
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
    command_plan = _read_required_jsonl(case_path, Path("input") / "command_plan.jsonl", stage="execute")
    execution_rows = execute_command_plan(case_id=case_context["case_id"], command_plan=command_plan)
    artifact_path = Path("runtime") / "executed_commands.jsonl"
    write_jsonl(case_path / artifact_path, execution_rows)
    result = _artifact_result(
        stage="execute",
        case_path=case_path,
        artifact_path=artifact_path,
        artifact=execution_rows,
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
    execution_rows = _read_required_jsonl(
        case_path,
        Path("runtime") / "executed_commands.jsonl",
        stage="collect",
    )
    collected_messages, openclaw_ingress = collect_messages(
        case_id=case_context["case_id"],
        execution_rows=execution_rows,
    )
    collected_path = Path("data") / "collected_messages.jsonl"
    ingress_path = Path("data") / "openclaw_message_ingress.jsonl"
    write_jsonl(case_path / collected_path, collected_messages)
    write_jsonl(case_path / ingress_path, openclaw_ingress)
    result = _multi_artifact_result(
        stage="collect",
        case_path=case_path,
        artifacts=[
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


PHASE1_STAGE_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
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
    difficulty: str = "medium",
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
    if stage not in PHASE1_STAGE_REGISTRY:
        raise CliUsageError(f"不支持的 phase1 stage: {stage}")
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
    difficulty: str = "medium",
) -> dict[str, Any]:
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
    difficulty: str = "medium",
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
    preflight_model_backend()
    case_context_result = run_phase1_case_context(
        dataset_root=dataset_root,
        seed=seed,
        family_id=family_id,
        difficulty=difficulty,
        comparison_target=comparison_target,
        skip_preflight=True,
    )
    case_path = Path(case_context_result["case_dir"])
    run_phase1_story_plan(case_dir=case_path, skip_preflight=True)
    for stage in PHASE1_STAGE_ORDER[2:]:
        run_phase1_step(stage=stage, case_dir=case_path)
    case_context = case_context_result["artifact"]
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
    context = _load_runtime_context(resolved_case_dir)
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
    query_benchmark = build_query_benchmark(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        story_plan=story_plan,
        annotation_gold_rows=annotation_gold_rows,
    )
    replay_eval = build_replay_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        query_benchmark=query_benchmark,
    )
    write_jsonl(case_path / "gold" / "annotation_gold.jsonl", annotation_gold_rows)
    write_json(case_path / "gold" / "query_benchmark.json", query_benchmark)
    write_json(case_path / "reports" / "replay_eval.json", replay_eval)
    active_case_path = _write_active_case(
        case_path=case_path,
        case_context=case_context,
        last_completed_stage="replay-eval",
    )
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "active_case_path": str(active_case_path),
    }


def compile_phase3(
    *,
    case_dir: str | Path | None = None,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
) -> dict[str, Any]:
    resolved_case_dir = _resolve_case_dir(case_dir=case_dir, dataset_root=dataset_root, stage="phase3")
    context = _load_runtime_context(resolved_case_dir)
    case_path = context["case_path"]
    case_context = context["case_context"]
    replay_eval = validate_replay_eval(read_json(case_path / "reports" / "replay_eval.json"))
    baseline_eval = build_baseline_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        replay_eval=replay_eval,
    )
    value_eval = build_value_eval(
        case_id=case_context["case_id"],
        family_id=case_context["family_id"],
        baseline_eval=baseline_eval,
    )
    report_text = build_benchmark_report(
        case_context=case_context,
        replay_eval=replay_eval,
        baseline_eval=baseline_eval,
        value_eval=value_eval,
    )
    write_json(case_path / "reports" / "baseline_eval.json", baseline_eval)
    write_json(case_path / "reports" / "value_eval.json", value_eval)
    write_text(case_path / "reports" / "final_benchmark_report.md", report_text)
    active_case_path = _write_active_case(
        case_path=case_path,
        case_context=case_context,
        last_completed_stage="benchmark-report",
    )
    return {
        "case_dir": str(case_path),
        "case_id": case_context["case_id"],
        "active_case_path": str(active_case_path),
    }


def build_all(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    difficulty: str = "medium",
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
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

    dataset_plan_parser = subparsers.add_parser("dataset-plan")
    dataset_plan_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    dataset_plan_parser.add_argument("--dataset-size", type=int, default=4)
    dataset_plan_parser.add_argument("--seed", type=int, default=1)
    dataset_plan_parser.add_argument("--difficulty", default=BUILDER_DEFAULT_DIFFICULTY)

    subparsers.add_parser("auth-check")
    current_case_parser = subparsers.add_parser("current-case")
    current_case_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))

    phase1_step_parser = subparsers.add_parser("phase1-step")
    phase1_step_parser.add_argument("--stage", choices=PHASE1_STAGE_ORDER, required=True)
    phase1_step_parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    phase1_step_parser.add_argument("--case-dir")
    phase1_step_parser.add_argument("--seed", type=int)
    phase1_step_parser.add_argument("--family-id")
    phase1_step_parser.add_argument("--difficulty", default=BUILDER_DEFAULT_DIFFICULTY)
    phase1_step_parser.add_argument("--comparison-target", default="default_memory_architectures")

    for name in ("phase1", "build-all"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
        subparser.add_argument("--seed", type=int)
        subparser.add_argument("--difficulty", default=BUILDER_DEFAULT_DIFFICULTY)
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
