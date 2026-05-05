from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .actor_registry import build_actor_registry
from .adapter import adapt_fetch_records
from .build_report import build_case_report
from .catalog_generator import generate_case_profile_catalog_with_mode
from .case_profiles import sample_case_seed_components
from .case_world_generator import generate_case_world_with_mode
from .character_generator import generate_characters_with_mode
from .collected_message_builder import build_collected_messages
from .collector import collect_fetch_records
from .command_plan_generator import generate_command_plan_with_mode
from .complexity_validator import build_complexity_report
from .config import DATASET_ROOT
from .conversation_plan_generator import generate_conversation_plan_with_mode
from .dataset_validator import build_dataset_validation_report
from .executor import execute_plan
from .gold_generator import generate_gold_artifacts
from .io_utils import case_dir, read_json, read_jsonl, write_json, write_jsonl
from .llm_client import DisabledLLMClient, build_llm_client_from_env
from .logging_utils import builder_log
from .plan_mapper import build_execution_plan_from_command_plan
from .schemas import ValidationError, validate_case_seed, validate_case_spec
from .story_generator import generate_story_with_mode
from .target_gold_generator import generate_target_state
from .timeline_planner import generate_timeline_with_mode


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _update_dataset_manifest(dataset_root: str | Path) -> dict[str, Any]:
    root = Path(dataset_root)
    cases_root = root / "cases"
    case_ids = sorted(path.name for path in cases_root.iterdir() if path.is_dir()) if cases_root.exists() else []
    manifest = {
        "dataset_version": "v2",
        "builder_version": "v2",
        "case_count": len(case_ids),
        "case_ids": case_ids,
        "created_at": _utc_now_iso(),
        "default_operator_mode": {
            "operator_identity": "user",
            "delivery_mode": "prefixed_single_operator",
        },
    }
    write_json(root / "dataset_manifest.json", manifest)
    return manifest


def _load_case_spec(path: str | Path) -> dict[str, Any]:
    return validate_case_spec(read_json(path))


def _aggregate_llm_mode(generation_modes: dict[str, str]) -> str:
    modes = [mode for mode in generation_modes.values() if mode in {"live", "fallback", "mixed"}]
    if not modes:
        return "deterministic"
    if all(mode == "live" for mode in modes):
        return "live"
    if all(mode == "fallback" for mode in modes):
        return "fallback"
    return "mixed"


def _derive_case_seed(case_spec: dict[str, Any]) -> dict[str, Any]:
    spec = validate_case_spec(case_spec)
    sampled = sample_case_seed_components(
        task_id=spec["task_id"],
        difficulty=spec["difficulty"],
        seed=spec["seed"],
        profile_id=spec.get("scenario_profile"),
        department_hints=spec["department_hints"],
        title_hint=spec["title_hint"] or spec["title"],
        main_goal_hint=spec["main_goal_hint"] or spec["main_goal"],
        company_type_hint=spec["company_type"],
    )
    return validate_case_seed(
        {
            "case_id": spec["case_id"],
            "task_id": spec["task_id"],
            "title": sampled["title"],
            "domain": sampled["domain"],
            "company_type": sampled["company_type"],
            "departments": sampled["departments"],
            "scenario_profile": spec.get("scenario_profile") or "enterprise_release_coordination",
            "main_goal": sampled["main_goal"],
            "difficulty": spec["difficulty"],
            "seed": spec["seed"],
            "complexity_profile": sampled["complexity_profile"],
        }
    )


def _prepare_case_generation(*, case_spec_path: str | Path, dataset_root: str | Path) -> tuple[dict[str, Any], Path, Any]:
    case_spec = _load_case_spec(case_spec_path)
    output_dir = case_dir(dataset_root, case_spec["case_id"])
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    return case_spec, output_dir, active_llm_client


def _missing_prerequisite(stage: str, case_path: Path, relative_path: str, recommended_phase: str) -> ValidationError:
    message = (
        f"missing prerequisite: {relative_path} in {case_path}. "
        f"please run phase '{recommended_phase}' first."
    )
    builder_log(stage, message)
    return ValidationError(message)


def _require_case_dir(case_dir_path: str | Path) -> Path:
    case_path = Path(case_dir_path)
    if not case_path.exists():
        raise ValidationError(f"case directory does not exist: {case_path}")
    return case_path


def _read_required_json(case_path: Path, relative_path: str, *, stage: str, recommended_phase: str) -> Any:
    target = case_path / relative_path
    if not target.exists():
        raise _missing_prerequisite(stage, case_path, relative_path, recommended_phase)
    return read_json(target)


def _read_required_jsonl(case_path: Path, relative_path: str, *, stage: str, recommended_phase: str) -> list[dict[str, Any]]:
    target = case_path / relative_path
    if not target.exists():
        raise _missing_prerequisite(stage, case_path, relative_path, recommended_phase)
    return read_jsonl(target)


def generate_case_profile_catalog_stage(*, output_path: str | Path | None = None) -> dict[str, Any]:
    from .case_profiles import CATALOG_PATH, load_case_profile_catalog

    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    if active_llm_client is None:
        raise ValidationError("generate-case-profile-catalog requires a live LLM client from .env")
    target = Path(output_path) if output_path else CATALOG_PATH
    builder_log("catalog", f"开始生成 case profile catalog，输出路径={target}")
    current_catalog = load_case_profile_catalog()
    generated_catalog, llm_mode = generate_case_profile_catalog_with_mode(
        llm_client=active_llm_client,
        current_catalog=current_catalog,
    )
    write_json(target, generated_catalog)
    builder_log("catalog", "完成并写入 case profile catalog")
    return {
        "output_path": str(target),
        "llm_mode": llm_mode,
        "catalog": generated_catalog,
    }


def generate_case_world_stage(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT) -> dict[str, Any]:
    builder_log("case-world", f"开始生成 case_world，读取 case spec: {case_spec_path}")
    case_spec, output_dir, active_llm_client = _prepare_case_generation(case_spec_path=case_spec_path, dataset_root=dataset_root)
    builder_log("case-world", f"case_id={case_spec['case_id']} 输出目录={output_dir}")
    case_seed = _derive_case_seed(case_spec)
    resolved_case_spec = {
        **case_spec,
        "title": case_seed["title"],
        "company_type": case_seed["company_type"],
        "departments": case_seed["departments"],
        "department_hints": case_spec["department_hints"],
        "main_goal": case_seed["main_goal"],
    }
    case_world, case_world_mode = generate_case_world_with_mode(case_seed, llm_client=active_llm_client)
    write_json(output_dir / "case_spec.json", resolved_case_spec)
    write_json(output_dir / "input" / "case_seed.json", case_seed)
    write_json(output_dir / "input" / "case_world.json", case_world)
    manifest = _update_dataset_manifest(dataset_root)
    builder_log("case-world", "完成并写入 input/case_seed.json 与 input/case_world.json")
    return {
        "case_dir": str(output_dir),
        "dataset_manifest": manifest,
        "llm_mode": case_world_mode,
        "generation_modes": {"case_world": case_world_mode},
        "case_spec": resolved_case_spec,
        "case_seed": case_seed,
        "case_world": case_world,
    }


def generate_characters_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("characters", f"开始生成 characters，输入目录={case_path}")
    case_spec = _read_required_json(case_path, "case_spec.json", stage="characters", recommended_phase="case-world")
    case_seed = _read_required_json(case_path, "input/case_seed.json", stage="characters", recommended_phase="case-world")
    case_world = _read_required_json(case_path, "input/case_world.json", stage="characters", recommended_phase="case-world")
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    story, _story_mode = generate_story_with_mode(case_spec, llm_client=active_llm_client)
    characters, characters_mode = generate_characters_with_mode(
        case_spec,
        case_seed,
        case_world,
        story,
        llm_client=active_llm_client,
    )
    actor_registry = build_actor_registry(characters)
    write_json(case_path / "input" / "characters.json", characters)
    write_json(case_path / "input" / "actor_registry.json", actor_registry)
    builder_log("characters", "完成并写入 input/characters.json 与 input/actor_registry.json")
    return {
        "case_dir": str(case_path),
        "llm_mode": characters_mode,
        "generation_modes": {"characters": characters_mode},
        "characters": characters,
        "actor_registry": actor_registry,
    }


def generate_conversation_plan_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("plan", f"开始生成 conversation_plan，输入目录={case_path}")
    case_spec = _read_required_json(case_path, "case_spec.json", stage="plan", recommended_phase="case-world")
    case_seed = _read_required_json(case_path, "input/case_seed.json", stage="plan", recommended_phase="case-world")
    case_world = _read_required_json(case_path, "input/case_world.json", stage="plan", recommended_phase="case-world")
    characters = _read_required_json(case_path, "input/characters.json", stage="plan", recommended_phase="characters")
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    story, story_mode = generate_story_with_mode(case_spec, llm_client=active_llm_client)
    _timeline, timeline_mode = generate_timeline_with_mode(case_spec, story, characters, llm_client=active_llm_client)
    conversation_plan, conversation_plan_mode = generate_conversation_plan_with_mode(
        case_seed,
        case_world,
        characters,
        llm_client=active_llm_client,
    )
    write_json(case_path / "input" / "conversation_plan.json", conversation_plan)
    llm_mode = _aggregate_llm_mode(
        {
            "story": story_mode,
            "timeline": timeline_mode,
            "conversation_plan": conversation_plan_mode,
        }
    )
    builder_log("plan", "完成并写入 input/conversation_plan.json")
    return {
        "case_dir": str(case_path),
        "llm_mode": llm_mode,
        "generation_modes": {"conversation_plan": conversation_plan_mode},
        "case_seed": case_seed,
        "characters": characters,
        "conversation_plan": conversation_plan,
    }


def generate_target_gold_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("target-gold", f"开始生成 target_state，输入目录={case_path}")
    conversation_plan = _read_required_json(case_path, "input/conversation_plan.json", stage="target-gold", recommended_phase="plan")
    target_state = generate_target_state(conversation_plan)
    write_json(case_path / "gold" / "target_state.json", target_state)
    builder_log("target-gold", "完成并写入 gold/target_state.json")
    return {
        "case_dir": str(case_path),
        "llm_mode": "deterministic",
        "generation_modes": {"target_gold": "deterministic"},
        "target_state": target_state,
    }


def generate_command_plan_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("command-plan", f"开始生成 command_plan，输入目录={case_path}")
    case_seed = _read_required_json(case_path, "input/case_seed.json", stage="command-plan", recommended_phase="case-world")
    characters = _read_required_json(case_path, "input/characters.json", stage="command-plan", recommended_phase="characters")
    conversation_plan = _read_required_json(case_path, "input/conversation_plan.json", stage="command-plan", recommended_phase="plan")
    target_state = _read_required_json(case_path, "gold/target_state.json", stage="command-plan", recommended_phase="target-gold")
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    command_plan, command_plan_mode = generate_command_plan_with_mode(
        case_seed,
        conversation_plan,
        characters,
        target_state=target_state,
        llm_client=active_llm_client,
    )
    execution_plan = build_execution_plan_from_command_plan(command_plan)
    write_jsonl(case_path / "input" / "command_plan.jsonl", command_plan)
    write_json(case_path / "execution_plan.json", execution_plan)
    builder_log("command-plan", "完成并写入 input/command_plan.jsonl 与 execution_plan.json")
    return {
        "case_dir": str(case_path),
        "llm_mode": command_plan_mode,
        "generation_modes": {"command_plan": command_plan_mode},
        "command_plan": command_plan,
        "execution_plan": execution_plan,
    }


def compile_case(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT) -> dict[str, Any]:
    builder_log("compile", f"开始编译 V2 case，读取 case spec: {case_spec_path}")
    case_world_result = generate_case_world_stage(case_spec_path=case_spec_path, dataset_root=dataset_root)
    case_path = Path(case_world_result["case_dir"])
    characters_result = generate_characters_stage(case_dir_path=case_path)
    plan_result = generate_conversation_plan_stage(case_dir_path=case_path)
    target_gold_result = generate_target_gold_stage(case_dir_path=case_path)
    command_result = generate_command_plan_stage(case_dir_path=case_path)
    manifest = _update_dataset_manifest(dataset_root)
    generation_modes = {
        "case_world": case_world_result["llm_mode"],
        "characters": characters_result["llm_mode"],
        "conversation_plan": plan_result["llm_mode"],
        "target_gold": target_gold_result["llm_mode"],
        "command_plan": command_result["llm_mode"],
    }
    return {
        "case_dir": str(case_path),
        "dataset_manifest": manifest,
        "case_spec": case_world_result["case_spec"],
        "case_seed": case_world_result["case_seed"],
        "case_world": case_world_result["case_world"],
        "characters": characters_result["characters"],
        "actor_registry": characters_result["actor_registry"],
        "conversation_plan": plan_result["conversation_plan"],
        "target_state": target_gold_result["target_state"],
        "command_plan": command_result["command_plan"],
        "execution_plan": command_result["execution_plan"],
        "generation_modes": generation_modes,
        "llm_mode": _aggregate_llm_mode(generation_modes),
    }


def execute_case(*, case_dir_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("execute", f"开始执行 execution_plan case_dir={case_path} dry_run={dry_run}")
    plan = _read_required_json(case_path, "execution_plan.json", stage="execute", recommended_phase="command-plan")
    resume_result = read_json(case_path / "execution_result.json") if (case_path / "execution_result.json").exists() else None
    if resume_result and str(resume_result.get("status") or "").strip() != "success":
        builder_log("execute", "检测到旧 execution_result 为 failed，本次不复用旧的 resume 状态")
        resume_result = None
    result = execute_plan(plan, dry_run=dry_run, resume_result=resume_result)
    write_json(case_path / "execution_result.json", result)
    builder_log("execute", f"execution_result 已写入 status={result['status']}")
    return result


def collect_case(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("collect", f"开始 collect case_dir={case_path}")
    characters = _read_required_json(case_path, "input/characters.json", stage="collect", recommended_phase="characters")
    actor_registry = _read_required_json(case_path, "input/actor_registry.json", stage="collect", recommended_phase="characters")
    command_plan = _read_required_jsonl(case_path, "input/command_plan.jsonl", stage="collect", recommended_phase="command-plan")
    execution_plan = _read_required_json(case_path, "execution_plan.json", stage="collect", recommended_phase="command-plan")
    execution_result = _read_required_json(case_path, "execution_result.json", stage="collect", recommended_phase="execute")
    fetch_records = collect_fetch_records(execution_plan, execution_result)
    collected_messages = build_collected_messages(
        characters,
        command_plan,
        execution_plan,
        execution_result,
        fetch_records,
        actor_registry=actor_registry,
    )
    write_jsonl(case_path / "lark_fetch_records.jsonl", fetch_records)
    write_jsonl(case_path / "data" / "collected_messages.jsonl", collected_messages)
    builder_log("collect", f"collect 完成 fetch_records={len(fetch_records)} collected_messages={len(collected_messages)}")
    return {
        "case_dir": str(case_path),
        "llm_mode": "deterministic",
        "generation_modes": {"collect": "deterministic"},
        "fetch_records": fetch_records,
        "collected_messages": collected_messages,
    }


def generate_gold_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("gold", f"开始生成 evidence-bound gold，输入目录={case_path}")
    target_state = _read_required_json(case_path, "gold/target_state.json", stage="gold", recommended_phase="target-gold")
    conversation_plan = _read_required_json(case_path, "input/conversation_plan.json", stage="gold", recommended_phase="plan")
    collected_messages = _read_required_jsonl(case_path, "data/collected_messages.jsonl", stage="gold", recommended_phase="collect")
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    gold, gold_mode = generate_gold_artifacts(target_state, conversation_plan, collected_messages, llm_client=active_llm_client)
    write_jsonl(case_path / "gold" / "expected_events.jsonl", gold["expected_events"])
    write_json(case_path / "gold" / "expected_memory_blocks.json", gold["expected_memory_blocks"])
    write_json(case_path / "gold" / "expected_current_state.json", gold["expected_current_state"])
    builder_log("gold", "完成并写入 expected_events / expected_memory_blocks / expected_current_state")
    return {
        "case_dir": str(case_path),
        "llm_mode": gold_mode,
        "generation_modes": {"gold": gold_mode},
        "gold": gold,
    }


def validate_case_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("validate", f"开始执行跨阶段一致性审计，输入目录={case_path}")
    case_seed = _read_required_json(case_path, "input/case_seed.json", stage="validate", recommended_phase="case-world")
    case_world = _read_required_json(case_path, "input/case_world.json", stage="validate", recommended_phase="case-world")
    characters = _read_required_json(case_path, "input/characters.json", stage="validate", recommended_phase="characters")
    actor_registry = _read_required_json(case_path, "input/actor_registry.json", stage="validate", recommended_phase="characters")
    conversation_plan = _read_required_json(case_path, "input/conversation_plan.json", stage="validate", recommended_phase="plan")
    target_state = _read_required_json(case_path, "gold/target_state.json", stage="validate", recommended_phase="target-gold")
    command_plan = _read_required_jsonl(case_path, "input/command_plan.jsonl", stage="validate", recommended_phase="command-plan")
    _read_required_json(case_path, "execution_plan.json", stage="validate", recommended_phase="command-plan")
    _read_required_json(case_path, "execution_result.json", stage="validate", recommended_phase="execute")
    _read_required_jsonl(case_path, "lark_fetch_records.jsonl", stage="validate", recommended_phase="collect")
    collected_messages = _read_required_jsonl(case_path, "data/collected_messages.jsonl", stage="validate", recommended_phase="collect")
    expected_events = _read_required_jsonl(case_path, "gold/expected_events.jsonl", stage="validate", recommended_phase="gold")
    expected_memory_blocks = _read_required_json(case_path, "gold/expected_memory_blocks.json", stage="validate", recommended_phase="gold")
    expected_current_state = _read_required_json(case_path, "gold/expected_current_state.json", stage="validate", recommended_phase="gold")
    complexity_report = build_complexity_report(case_seed, conversation_plan, collected_messages)
    dataset_validation_report = build_dataset_validation_report(
        case_seed=case_seed,
        case_world=case_world,
        characters=characters,
        actor_registry=actor_registry,
        conversation_plan=conversation_plan,
        target_state=target_state,
        command_plan=command_plan,
        collected_messages=collected_messages,
        complexity_report=complexity_report,
        expected_events=expected_events,
        expected_memory_blocks=expected_memory_blocks,
        expected_current_state=expected_current_state,
    )
    write_json(case_path / "checks" / "conversation_complexity_report.json", complexity_report)
    write_json(case_path / "checks" / "dataset_validation_report.json", dataset_validation_report)
    builder_log("validate", f"审计完成 passed={dataset_validation_report['passed']}")
    return {
        "case_dir": str(case_path),
        "llm_mode": "deterministic",
        "generation_modes": {"validate": "deterministic"},
        "complexity_report": complexity_report,
        "dataset_validation_report": dataset_validation_report,
    }


def adapt_case(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    builder_log("adapt", f"开始生成 ingress / report case_dir={case_path}")
    case_spec = _read_required_json(case_path, "case_spec.json", stage="adapt", recommended_phase="case-world")
    characters = _read_required_json(case_path, "input/characters.json", stage="adapt", recommended_phase="characters")
    actor_registry = _read_required_json(case_path, "input/actor_registry.json", stage="adapt", recommended_phase="characters")
    execution_result = _read_required_json(case_path, "execution_result.json", stage="adapt", recommended_phase="execute")
    fetch_records = _read_required_jsonl(case_path, "lark_fetch_records.jsonl", stage="adapt", recommended_phase="collect")
    collected_messages = _read_required_jsonl(case_path, "data/collected_messages.jsonl", stage="adapt", recommended_phase="collect")
    ingress_events, adapter_report = adapt_fetch_records(
        case_spec,
        execution_result,
        fetch_records,
        collected_messages=collected_messages,
        actor_registry=actor_registry,
    )
    allowed_open_ids = {
        item["simulated_open_id"]
        for item in characters["characters"]
    }
    ingress_open_ids = {
        str(event.get("sender", {}).get("sender_id", {}).get("open_id") or "").strip()
        for event in ingress_events
        if str(event.get("sender", {}).get("sender_id", {}).get("open_id") or "").strip()
    }
    unknown_open_ids = sorted(open_id for open_id in ingress_open_ids if open_id not in allowed_open_ids)
    if unknown_open_ids:
        raise ValidationError(
            "adapt produced ingress sender open_id values missing from characters.json: "
            + ", ".join(unknown_open_ids)
        )
    write_jsonl(case_path / "openclaw_message_ingress.jsonl", ingress_events)
    write_json(case_path / "adapter_report.json", adapter_report)
    conversation_plan = _read_required_json(case_path, "input/conversation_plan.json", stage="adapt", recommended_phase="plan")
    plan = _read_required_json(case_path, "execution_plan.json", stage="adapt", recommended_phase="command-plan")
    report = build_case_report(
        case_id=case_spec["case_id"],
        operator_identity=execution_result["operator_identity"],
        delivery_mode=execution_result["delivery_mode"],
        preflight=execution_result.get("preflight") or {},
        fetch_identity="user",
        characters=characters,
        conversation_plan=conversation_plan,
        execution_plan=plan,
        execution_result=execution_result,
        fetch_records=fetch_records,
        ingress_events=ingress_events,
        warnings=list(adapter_report.get("warnings", [])),
    )
    write_json(case_path / "build_report.json", report)
    builder_log("adapt", f"adapt 完成 ingress_events={len(ingress_events)} warnings={len(adapter_report.get('warnings') or [])}")
    return {"adapter_report": adapter_report, "build_report": report}


def build_case(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT, dry_run: bool = False) -> dict[str, Any]:
    builder_log("build", f"开始执行 full build case_spec={case_spec_path} dry_run={dry_run}")
    compiled = compile_case(case_spec_path=case_spec_path, dataset_root=dataset_root)
    output_dir = Path(compiled["case_dir"])
    execution_result = execute_case(case_dir_path=output_dir, dry_run=dry_run)
    if dry_run:
        builder_log("build", "dry_run 模式，跳过 collect / gold / validate / adapt")
        return {"compiled": compiled, "execution_result": execution_result}
    collected = collect_case(case_dir_path=output_dir)
    gold = generate_gold_stage(case_dir_path=output_dir)
    validated = validate_case_stage(case_dir_path=output_dir)
    if not validated["complexity_report"]["passed"]:
        raise ValidationError(
            f"case {compiled['case_spec']['case_id']} failed complexity gate: {', '.join(validated['complexity_report']['failed_checks'])}"
        )
    if not validated["dataset_validation_report"]["passed"]:
        raise ValidationError(
            f"case {compiled['case_spec']['case_id']} failed dataset validation: {'; '.join(validated['dataset_validation_report']['errors'])}"
        )
    adapted = adapt_case(case_dir_path=output_dir)
    builder_log("build", "full build 完成")
    return {"compiled": compiled, "execution_result": execution_result, "collected": collected, "gold": gold, "validated": validated, "adapted": adapted}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Feishu IM dataset cases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile-case")
    compile_parser.add_argument("--case-spec", required=True)
    compile_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    case_world_parser = subparsers.add_parser("generate-case-world")
    case_world_parser.add_argument("--case-spec", required=True)
    case_world_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    catalog_parser = subparsers.add_parser("generate-case-profile-catalog")
    catalog_parser.add_argument("--output")

    characters_parser = subparsers.add_parser("generate-characters")
    characters_parser.add_argument("--case-dir", required=True)

    conversation_parser = subparsers.add_parser("generate-conversation-plan")
    conversation_parser.add_argument("--case-dir", required=True)

    target_gold_parser = subparsers.add_parser("generate-target-gold")
    target_gold_parser.add_argument("--case-dir", required=True)

    command_plan_parser = subparsers.add_parser("generate-command-plan")
    command_plan_parser.add_argument("--case-dir", required=True)

    execute_parser = subparsers.add_parser("execute-case")
    execute_parser.add_argument("--case-dir", required=True)
    execute_parser.add_argument("--dry-run", action="store_true")

    collect_parser = subparsers.add_parser("collect-case")
    collect_parser.add_argument("--case-dir", required=True)

    gold_parser = subparsers.add_parser("generate-gold")
    gold_parser.add_argument("--case-dir", required=True)

    validate_parser = subparsers.add_parser("validate-case")
    validate_parser.add_argument("--case-dir", required=True)

    adapt_parser = subparsers.add_parser("adapt-case")
    adapt_parser.add_argument("--case-dir", required=True)

    build_parser_cmd = subparsers.add_parser("build-case")
    build_parser_cmd.add_argument("--case-spec", required=True)
    build_parser_cmd.add_argument("--dataset-root", default=DATASET_ROOT)
    build_parser_cmd.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "compile-case":
        result = compile_case(case_spec_path=args.case_spec, dataset_root=args.dataset_root)
    elif args.command == "generate-case-world":
        result = generate_case_world_stage(case_spec_path=args.case_spec, dataset_root=args.dataset_root)
    elif args.command == "generate-case-profile-catalog":
        result = generate_case_profile_catalog_stage(output_path=args.output)
    elif args.command == "generate-characters":
        result = generate_characters_stage(case_dir_path=args.case_dir)
    elif args.command == "generate-conversation-plan":
        result = generate_conversation_plan_stage(case_dir_path=args.case_dir)
    elif args.command == "generate-target-gold":
        result = generate_target_gold_stage(case_dir_path=args.case_dir)
    elif args.command == "generate-command-plan":
        result = generate_command_plan_stage(case_dir_path=args.case_dir)
    elif args.command == "execute-case":
        result = execute_case(case_dir_path=args.case_dir, dry_run=args.dry_run)
    elif args.command == "collect-case":
        result = collect_case(case_dir_path=args.case_dir)
    elif args.command == "generate-gold":
        result = generate_gold_stage(case_dir_path=args.case_dir)
    elif args.command == "validate-case":
        result = validate_case_stage(case_dir_path=args.case_dir)
    elif args.command == "adapt-case":
        result = adapt_case(case_dir_path=args.case_dir)
    else:
        result = build_case(case_spec_path=args.case_spec, dataset_root=args.dataset_root, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
