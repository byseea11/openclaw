from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .actor_registry import build_actor_registry
from .annotation_gold_generator import generate_annotation_gold
from .builder_settings import resolve_default_difficulty
from .case_world_generator import generate_case_world_with_mode
from .case_manifest import update_case_manifest
from .character_generator import generate_characters_with_mode
from .check_builder import build_checks
from .collected_message_builder import build_collected_messages
from .collector import collect_fetch_records, utc_now_iso
from .command_plan_generator import generate_command_plan_with_mode
from .config import DATASET_ROOT
from .conversation_plan_generator import generate_conversation_plan_with_mode
from .event_alignment import align_events
from .event_evaluator import evaluate_events
from .executor import execute_plan
from .failure_mode_selector import normalized_failure_mode_spec
from .block_evaluator import evaluate_blocks
from .gold_validator import validate_gold_against_observed_data
from .io_utils import case_dir, read_json, read_jsonl, write_json, write_jsonl
from .llm_client import DisabledLLMClient, build_llm_client_from_env
from .logging_utils import builder_log
from .memory_failure_blueprint_generator import generate_memory_failure_blueprint_with_mode
from .memory_md_baseline_runner import run_memory_md_baseline
from .plan_mapper import build_execution_plan_from_command_plan
from .pre_annotation_validator import build_pre_annotation_validation_report
from .qa_evaluator import evaluate_qa
from .raw_message_rag_runner import run_raw_message_rag
from .replay_runtime import replay_runtime
from .report_builder import build_reports
from .schemas import ValidationError, validate_case_manifest, validate_case_spec
from .spec_generator import generate_case_spec_with_mode, normalize_seed
from .state_trajectory_generator import generate_state_trajectory
from .task_actor_layout_generator import generate_task_actor_layout
from .value_evaluator import evaluate_value


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _active_llm_client() -> Any | None:
    llm_client = build_llm_client_from_env()
    return None if isinstance(llm_client, DisabledLLMClient) else llm_client


def _update_dataset_manifest(dataset_root: str | Path) -> dict[str, Any]:
    root = Path(dataset_root)
    cases_root = root / "cases"
    case_ids = sorted(path.name for path in cases_root.iterdir() if path.is_dir()) if cases_root.exists() else []
    manifest = {
        "dataset_version": "v3",
        "builder_version": "v3-phase3",
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


def _prepare_case_generation(*, case_spec_path: str | Path, dataset_root: str | Path) -> tuple[dict[str, Any], Path, Any]:
    case_spec = _load_case_spec(case_spec_path)
    output_dir = case_dir(dataset_root, case_spec["case_id"])
    return case_spec, output_dir, _active_llm_client()


def _require_case_dir(case_dir_path: str | Path) -> Path:
    case_path = Path(case_dir_path)
    if not case_path.exists():
        raise ValidationError(f"case directory does not exist: {case_path}")
    return case_path


def _read_required_json(case_path: Path, relative_path: str, stage: str) -> Any:
    target = case_path / relative_path
    if not target.exists():
        raise ValidationError(f"[{stage}] missing prerequisite: {relative_path} in {case_path}")
    return read_json(target)


def _read_required_jsonl(case_path: Path, relative_path: str, stage: str) -> list[dict[str, Any]]:
    target = case_path / relative_path
    if not target.exists():
        raise ValidationError(f"[{stage}] missing prerequisite: {relative_path} in {case_path}")
    return read_jsonl(target)


def _touch_case_manifest(case_path: Path, *, stage: str) -> dict[str, Any]:
    case_spec = _read_required_json(case_path, "case_spec.json", stage)
    return update_case_manifest(case_path, case_id=case_spec["case_id"], completed_stage=stage)


def generate_case_spec_stage(
    *,
    dataset_root: str | Path = DATASET_ROOT,
    scenario_profile: str = "enterprise_task_memory",
    difficulty: str | None = None,
    seed: int | None = None,
    user_hint: str = "",
    comparison_target: str | None = None,
    selected_failure_modes: list[str] | None = None,
    primary_failure_mode: str | None = None,
) -> dict[str, Any]:
    scenario_profile = str(scenario_profile or "enterprise_task_memory")
    user_hint = str(user_hint or "")
    normalized_seed = normalize_seed(seed)
    spec, llm_mode = generate_case_spec_with_mode(
        scenario_profile=scenario_profile,
        difficulty=difficulty or resolve_default_difficulty(),
        seed=normalized_seed,
        user_hint=user_hint,
        comparison_target=comparison_target,
        selected_failure_modes=selected_failure_modes,
        primary_failure_mode=primary_failure_mode,
        llm_client=_active_llm_client(),
    )
    spec = normalized_failure_mode_spec(spec)
    output_dir = case_dir(dataset_root, spec["case_id"])
    target = output_dir / "case_spec.json"
    write_json(target, spec)
    case_manifest = update_case_manifest(output_dir, case_id=spec["case_id"], completed_stage="spec-generation")
    manifest = _update_dataset_manifest(dataset_root)
    return {
        "case_dir": str(output_dir),
        "case_spec_path": str(target),
        "llm_mode": llm_mode,
        "case_spec": spec,
        "case_manifest": case_manifest,
        "dataset_manifest": manifest,
    }


def generate_memory_failure_blueprint_stage(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT) -> dict[str, Any]:
    case_spec, output_dir, active_llm_client = _prepare_case_generation(case_spec_path=case_spec_path, dataset_root=dataset_root)
    blueprint, llm_mode = generate_memory_failure_blueprint_with_mode(case_spec, llm_client=active_llm_client)
    write_json(output_dir / "input" / "memory_failure_blueprint.json", blueprint)
    _touch_case_manifest(output_dir, stage="memory-failure-blueprint")
    return {"case_dir": str(output_dir), "llm_mode": llm_mode, "memory_failure_blueprint": blueprint}


def generate_task_actor_layout_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    blueprint = _read_required_json(case_path, "input/memory_failure_blueprint.json", "task-actor-layout")
    layout = generate_task_actor_layout(blueprint)
    write_json(case_path / "input" / "task_actor_layout.json", layout)
    _touch_case_manifest(case_path, stage="task-actor-layout")
    return {"case_dir": str(case_path), "task_actor_layout": layout}


def generate_case_world_stage(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT) -> dict[str, Any]:
    case_spec, output_dir, active_llm_client = _prepare_case_generation(case_spec_path=case_spec_path, dataset_root=dataset_root)
    blueprint = _read_required_json(output_dir, "input/memory_failure_blueprint.json", "case-world")
    layout = _read_required_json(output_dir, "input/task_actor_layout.json", "case-world")
    case_world, llm_mode = generate_case_world_with_mode(case_spec, blueprint, layout, llm_client=active_llm_client)
    write_json(output_dir / "input" / "case_world.json", case_world)
    _touch_case_manifest(output_dir, stage="case-world")
    return {"case_dir": str(output_dir), "llm_mode": llm_mode, "case_world": case_world}


def generate_characters_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    layout = _read_required_json(case_path, "input/task_actor_layout.json", "characters")
    case_world = _read_required_json(case_path, "input/case_world.json", "characters")
    characters, llm_mode = generate_characters_with_mode(layout, case_world, llm_client=_active_llm_client())
    actor_registry = build_actor_registry(characters)
    write_json(case_path / "input" / "characters.json", characters)
    write_json(case_path / "input" / "actor_registry.json", actor_registry)
    _touch_case_manifest(case_path, stage="characters")
    return {"case_dir": str(case_path), "llm_mode": llm_mode, "characters": characters, "actor_registry": actor_registry}


def generate_state_trajectory_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    blueprint = _read_required_json(case_path, "input/memory_failure_blueprint.json", "state-trajectory")
    layout = _read_required_json(case_path, "input/task_actor_layout.json", "state-trajectory")
    case_world = _read_required_json(case_path, "input/case_world.json", "state-trajectory")
    characters = _read_required_json(case_path, "input/characters.json", "state-trajectory")
    trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
    write_json(case_path / "input" / "state_trajectory.json", trajectory)
    _touch_case_manifest(case_path, stage="state-trajectory")
    return {"case_dir": str(case_path), "state_trajectory": trajectory}


def generate_conversation_plan_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    case_world = _read_required_json(case_path, "input/case_world.json", "conversation-plan")
    characters = _read_required_json(case_path, "input/characters.json", "conversation-plan")
    blueprint = _read_required_json(case_path, "input/memory_failure_blueprint.json", "conversation-plan")
    trajectory = _read_required_json(case_path, "input/state_trajectory.json", "conversation-plan")
    plan, llm_mode = generate_conversation_plan_with_mode(
        case_world,
        characters,
        blueprint,
        trajectory,
        llm_client=_active_llm_client(),
    )
    write_json(case_path / "input" / "conversation_plan.json", plan)
    _touch_case_manifest(case_path, stage="conversation-plan")
    return {"case_dir": str(case_path), "llm_mode": llm_mode, "conversation_plan": plan}


def generate_command_plan_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    case_spec = _read_required_json(case_path, "case_spec.json", "command-plan")
    conversation_plan = _read_required_json(case_path, "input/conversation_plan.json", "command-plan")
    characters = _read_required_json(case_path, "input/characters.json", "command-plan")
    command_plan, llm_mode = generate_command_plan_with_mode(
        case_spec,
        conversation_plan,
        characters,
        llm_client=_active_llm_client(),
    )
    execution_plan = build_execution_plan_from_command_plan(command_plan)
    write_jsonl(case_path / "input" / "command_plan.jsonl", command_plan)
    write_json(case_path / "execution_plan.json", execution_plan)
    _touch_case_manifest(case_path, stage="command-plan")
    return {
        "case_dir": str(case_path),
        "llm_mode": llm_mode,
        "command_plan": command_plan,
        "execution_plan": execution_plan,
    }


def _hydrate_dry_run_execution_result(command_plan: list[dict[str, Any]], execution_result: dict[str, Any]) -> dict[str, Any]:
    if execution_result["status"] != "success":
        return execution_result
    created_resources = dict(execution_result["created_resources"])
    for row in command_plan:
        if row["action_type"] == "create_chat":
            created_resources.setdefault(row["chat_ref"], {"chat_id": f"oc_sim_{row['chat_ref']}"})
        elif row["action_type"] in {"send_message", "reply_in_thread"} and row.get("output_ref"):
            created_resources.setdefault(
                row["output_ref"],
                {
                    "message_id": f"om_sim_{row['step_id']}",
                    "thread_id": f"omt_sim_{row['turn_id'] or row['step_id']}",
                    "chat_id": f"oc_sim_{row['chat_ref']}",
                },
            )
    hydrated = dict(execution_result)
    hydrated["created_resources"] = created_resources
    return hydrated


def execute_case(*, case_dir_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    execution_plan = _read_required_json(case_path, "execution_plan.json", "execute")
    result = execute_plan(execution_plan, dry_run=dry_run)
    command_plan = _read_required_jsonl(case_path, "input/command_plan.jsonl", "execute")
    if dry_run:
        result = _hydrate_dry_run_execution_result(command_plan, result)
    write_json(case_path / "execution_result.json", result)
    _touch_case_manifest(case_path, stage="execute")
    return result


def _simulate_fetch_records(command_plan: list[dict[str, Any]], execution_result: dict[str, Any]) -> list[dict[str, Any]]:
    created_resources = execution_result["created_resources"]
    rows = []
    for row in command_plan:
        if row["action_type"] not in {"send_message", "reply_in_thread"}:
            continue
        output_ref = str(row.get("output_ref") or "").strip()
        resource = created_resources.get(output_ref, {})
        message_id = str(resource.get("message_id") or f"om_sim_{row['step_id']}").strip()
        record = {
            "record_id": f"fetch-{row['step_id']}",
            "domain": "im",
            "kind": "thread_messages_fetch" if row["action_type"] == "reply_in_thread" else "chat_messages_fetch",
            "captured_at": utc_now_iso(),
            "identity": "user",
            "command": row["lark_cli_command"],
            "response": {
                "data": {
                    "messages": [
                        {
                            "message_id": message_id,
                            "content": row["params"]["content_text"],
                            "msg_type": "text",
                            "sender": {
                                "id": created_resources.get(row["chat_ref"], {}).get("chat_id", f"ou_sim_{row['speaker_ref']}"),
                                "name": "",
                                "sender_type": "user",
                            },
                        }
                    ]
                }
            },
        }
        rows.append(record)
    return rows


def _build_openclaw_message_ingress(case_id: str, collected_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, row in enumerate(collected_messages, start=1):
        rows.append(
            {
                "ingress_id": f"ingress_{index:03d}",
                "case_id": case_id,
                "message_id": row["message_id"],
                "session_id": row["session_id"],
                "source_session_ref": row["source_ref"],
                "content_text": row["content_text"],
                "normalized_actor_id": row["normalized_actor_id"],
                "benchmark_role": row["benchmark_role"],
                "memory_failure_mode": row["memory_failure_mode"],
                "memory_trap": row["memory_trap"],
                "captured_at": utc_now_iso(),
            }
        )
    return rows


def collect_case(*, case_dir_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    command_plan = _read_required_jsonl(case_path, "input/command_plan.jsonl", "collect")
    execution_plan = _read_required_json(case_path, "execution_plan.json", "collect")
    execution_result = _read_required_json(case_path, "execution_result.json", "collect")
    characters = _read_required_json(case_path, "input/characters.json", "collect")
    actor_registry = _read_required_json(case_path, "input/actor_registry.json", "collect")
    if dry_run or execution_result["created_resources"] == {}:
        fetch_records = _simulate_fetch_records(command_plan, execution_result)
    else:
        fetch_records = collect_fetch_records(execution_plan, execution_result)
    collected_messages = build_collected_messages(
        characters,
        command_plan,
        execution_plan,
        execution_result,
        fetch_records,
        actor_registry=actor_registry,
    )
    openclaw_message_ingress = _build_openclaw_message_ingress(read_json(case_path / "case_spec.json")["case_id"], collected_messages)
    write_jsonl(case_path / "lark_fetch_records.jsonl", fetch_records)
    write_jsonl(case_path / "data" / "collected_messages.jsonl", collected_messages)
    write_jsonl(case_path / "data" / "openclaw_message_ingress.jsonl", openclaw_message_ingress)
    _touch_case_manifest(case_path, stage="collect")
    return {
        "case_dir": str(case_path),
        "fetch_records": fetch_records,
        "collected_messages": collected_messages,
        "openclaw_message_ingress": openclaw_message_ingress,
    }


def pre_annotation_validate_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    report = build_pre_annotation_validation_report(
        case_spec=_read_required_json(case_path, "case_spec.json", "pre-annotation-validate"),
        memory_failure_blueprint=_read_required_json(case_path, "input/memory_failure_blueprint.json", "pre-annotation-validate"),
        conversation_plan=_read_required_json(case_path, "input/conversation_plan.json", "pre-annotation-validate"),
        collected_messages=_read_required_jsonl(case_path, "data/collected_messages.jsonl", "pre-annotation-validate"),
    )
    write_json(case_path / "checks" / "pre_annotation_validation_report.json", report)
    _touch_case_manifest(case_path, stage="pre-annotation-validate")
    return {"case_dir": str(case_path), "pre_annotation_validation_report": report}


def annotation_gold_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    gold = generate_annotation_gold(
        case_spec=_read_required_json(case_path, "case_spec.json", "annotation-gold"),
        memory_failure_blueprint=_read_required_json(case_path, "input/memory_failure_blueprint.json", "annotation-gold"),
        state_trajectory=_read_required_json(case_path, "input/state_trajectory.json", "annotation-gold"),
        conversation_plan=_read_required_json(case_path, "input/conversation_plan.json", "annotation-gold"),
        collected_messages=_read_required_jsonl(case_path, "data/collected_messages.jsonl", "annotation-gold"),
    )
    write_jsonl(case_path / "gold" / "event_annotations.jsonl", gold["event_annotations"])
    write_json(case_path / "gold" / "block_annotations.json", gold["block_annotations"])
    write_json(case_path / "gold" / "query_benchmark.json", gold["query_benchmark"])
    _touch_case_manifest(case_path, stage="annotation-gold")
    return {"case_dir": str(case_path), **gold}


def build_checks_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    built = build_checks(
        case_spec=_read_required_json(case_path, "case_spec.json", "build-checks"),
        pre_annotation_validation_report=_read_required_json(
            case_path,
            "checks/pre_annotation_validation_report.json",
            "build-checks",
        ),
        event_annotations=_read_required_jsonl(case_path, "gold/event_annotations.jsonl", "build-checks"),
        block_annotations=_read_required_json(case_path, "gold/block_annotations.json", "build-checks"),
        query_benchmark=_read_required_json(case_path, "gold/query_benchmark.json", "build-checks"),
    )
    write_json(case_path / "checks" / "complexity_gate.json", built["complexity_gate"])
    write_json(case_path / "checks" / "integrity_gate.json", built["integrity_gate"])
    write_json(case_path / "checks" / "eval_manifest.json", built["eval_manifest"])
    _touch_case_manifest(case_path, stage="build-checks")
    return {"case_dir": str(case_path), **built}


def gold_validate_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    report = validate_gold_against_observed_data(
        collected_messages=_read_required_jsonl(case_path, "data/collected_messages.jsonl", "gold-validate"),
        event_annotations=_read_required_jsonl(case_path, "gold/event_annotations.jsonl", "gold-validate"),
        block_annotations=_read_required_json(case_path, "gold/block_annotations.json", "gold-validate"),
        query_benchmark=_read_required_json(case_path, "gold/query_benchmark.json", "gold-validate"),
    )
    integrity_gate = {
        **_read_required_json(case_path, "checks/integrity_gate.json", "gold-validate"),
        "gold_validation": report,
        "status": report["status"],
    }
    write_json(case_path / "checks" / "integrity_gate.json", integrity_gate)
    _touch_case_manifest(case_path, stage="gold-validate")
    return {"case_dir": str(case_path), "gold_validation_report": report}


def replay_runtime_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    _read_required_json(case_path, "checks/integrity_gate.json", "replay-runtime")
    result = replay_runtime(case_path)
    _touch_case_manifest(case_path, stage="replay-runtime")
    return {"case_dir": str(case_path), **result}


def replay_eval_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    case_spec = _read_required_json(case_path, "case_spec.json", "replay-eval")
    event_annotations = _read_required_jsonl(case_path, "gold/event_annotations.jsonl", "replay-eval")
    block_annotations = _read_required_json(case_path, "gold/block_annotations.json", "replay-eval")
    query_benchmark = _read_required_json(case_path, "gold/query_benchmark.json", "replay-eval")
    candidate_events = _read_required_jsonl(case_path, "predictions/candidate_events.jsonl", "replay-eval")
    session_events = _read_required_jsonl(case_path, "predictions/session_events.jsonl", "replay-eval")
    task_wiki_state = _read_required_json(case_path, "predictions/task_wiki_state.json", "replay-eval")
    candidate_alignment = align_events(
        case_id=case_spec["case_id"],
        event_annotations=event_annotations,
        predictions=candidate_events,
        prediction_source="candidate_events",
    )
    session_alignment = align_events(
        case_id=case_spec["case_id"],
        event_annotations=event_annotations,
        predictions=session_events,
        prediction_source="session_events",
    )
    event_eval = evaluate_events(
        case_id=case_spec["case_id"],
        event_annotations=event_annotations,
        candidate_alignment=candidate_alignment,
        session_alignment=session_alignment,
        candidate_events=candidate_events,
        session_events=session_events,
    )
    block_eval = evaluate_blocks(
        case_id=case_spec["case_id"],
        block_annotations=block_annotations,
        event_alignment=session_alignment,
        task_wiki_state=task_wiki_state,
    )
    qa_eval = evaluate_qa(
        case_id=case_spec["case_id"],
        query_benchmark=query_benchmark,
        session_events=session_events,
        task_wiki_state=task_wiki_state,
    )
    write_json(case_path / "reports" / "event_alignment.json", session_alignment)
    write_json(case_path / "reports" / "event_eval.json", event_eval)
    write_json(case_path / "reports" / "block_eval.json", block_eval)
    write_json(case_path / "reports" / "qa_eval.json", qa_eval)
    _touch_case_manifest(case_path, stage="replay-eval")
    return {
        "case_dir": str(case_path),
        "event_alignment": session_alignment,
        "event_eval": event_eval,
        "block_eval": block_eval,
        "qa_eval": qa_eval,
    }


def memory_md_baseline_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    report = run_memory_md_baseline(case_dir=case_path)
    _touch_case_manifest(case_path, stage="memory-md-baseline")
    return {"case_dir": str(case_path), "memory_md_baseline_report": report}


def value_eval_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    query_benchmark = _read_required_json(case_path, "gold/query_benchmark.json", "value-eval")
    task_wiki_state = _read_required_json(case_path, "predictions/task_wiki_state.json", "value-eval")
    session_events = _read_required_jsonl(case_path, "predictions/session_events.jsonl", "value-eval")
    memory_report = _read_required_json(case_path, "reports/memory_md_baseline_report.json", "value-eval")
    rag_report = run_raw_message_rag(case_dir=case_path, query_benchmark=query_benchmark)
    value_eval = evaluate_value(
        case_id=_read_required_json(case_path, "case_spec.json", "value-eval")["case_id"],
        query_benchmark=query_benchmark,
        task_wiki_state=task_wiki_state,
        session_events=session_events,
        memory_md_baseline_report=memory_report,
        raw_message_rag_report=rag_report,
    )
    write_json(case_path / "reports" / "value_eval.json", value_eval)
    _touch_case_manifest(case_path, stage="value-eval")
    return {"case_dir": str(case_path), "value_eval": value_eval, "raw_message_rag_report": rag_report}


def report_stage(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    reports = build_reports(case_path)
    _touch_case_manifest(case_path, stage="report")
    return {"case_dir": str(case_path), **reports}


def compile_case_phase1(
    *,
    case_spec_path: str | Path,
    dataset_root: str | Path = DATASET_ROOT,
    dry_run: bool = True,
) -> dict[str, Any]:
    case_spec = _load_case_spec(case_spec_path)
    case_output_dir = case_dir(dataset_root, case_spec["case_id"])
    write_json(case_output_dir / "case_spec.json", case_spec)
    blueprint = generate_memory_failure_blueprint_stage(case_spec_path=case_output_dir / "case_spec.json", dataset_root=dataset_root)
    generate_task_actor_layout_stage(case_dir_path=case_output_dir)
    case_world = generate_case_world_stage(case_spec_path=case_output_dir / "case_spec.json", dataset_root=dataset_root)
    characters = generate_characters_stage(case_dir_path=case_output_dir)
    generate_state_trajectory_stage(case_dir_path=case_output_dir)
    conversation = generate_conversation_plan_stage(case_dir_path=case_output_dir)
    command = generate_command_plan_stage(case_dir_path=case_output_dir)
    execution_result = execute_case(case_dir_path=case_output_dir, dry_run=dry_run)
    collect = collect_case(case_dir_path=case_output_dir, dry_run=dry_run)
    validation = pre_annotation_validate_stage(case_dir_path=case_output_dir)
    manifest = _update_dataset_manifest(dataset_root)
    generation_modes = {
        "memory_failure_blueprint": blueprint["llm_mode"],
        "case_world": case_world["llm_mode"],
        "characters": characters["llm_mode"],
        "conversation_plan": conversation["llm_mode"],
        "command_plan": command["llm_mode"],
    }
    creative_modes = [
        generation_modes["memory_failure_blueprint"],
        generation_modes["case_world"],
        generation_modes["characters"],
        generation_modes["conversation_plan"],
    ]
    return {
        "case_dir": str(case_output_dir),
        "dataset_manifest": manifest,
        "conversation_plan": conversation["conversation_plan"],
        "command_plan": command["command_plan"],
        "execution_result": execution_result,
        "collected_messages": collect["collected_messages"],
        "pre_annotation_validation_report": validation["pre_annotation_validation_report"],
        "llm_mode": "llm" if all(mode == "llm" for mode in creative_modes) else "fallback",
        "llm_generation_modes": generation_modes,
    }


def compile_case_phase2(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    manifest = validate_case_manifest(read_json(case_path / "case_manifest.json"))
    if "pre-annotation-validate" not in manifest["completed_stages"]:
        raise ValidationError("compile-case-phase2 requires completed Phase 1 artifacts")
    annotation = annotation_gold_stage(case_dir_path=case_path)
    checks = build_checks_stage(case_dir_path=case_path)
    gold = gold_validate_stage(case_dir_path=case_path)
    replay = replay_runtime_stage(case_dir_path=case_path)
    reports = replay_eval_stage(case_dir_path=case_path)
    return {
        "case_dir": str(case_path),
        "annotation_gold": annotation,
        "checks": checks,
        "gold_validation": gold,
        "runtime": replay,
        "reports": reports,
    }


def compile_case_phase3(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = _require_case_dir(case_dir_path)
    manifest = validate_case_manifest(read_json(case_path / "case_manifest.json"))
    if "replay-eval" not in manifest["completed_stages"]:
        compile_case_phase2(case_dir_path=case_path)
    baseline = memory_md_baseline_stage(case_dir_path=case_path)
    value = value_eval_stage(case_dir_path=case_path)
    report = report_stage(case_dir_path=case_path)
    return {
        "case_dir": str(case_path),
        "memory_md_baseline": baseline,
        "value_eval": value,
        "report": report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu-builder-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    spec = subparsers.add_parser("spec-generation")
    spec.add_argument("--dataset-root", default=DATASET_ROOT)
    spec.add_argument("--difficulty", default=resolve_default_difficulty())
    spec.add_argument("--seed", type=int, default=None)
    spec.add_argument("--comparison-target", default=None)
    spec.add_argument("--selected-failure-mode", action="append", dest="selected_failure_modes")
    spec.add_argument("--primary-failure-mode", default=None)

    for name in [
        "memory-failure-blueprint",
        "task-actor-layout",
        "characters",
        "state-trajectory",
        "conversation-plan",
        "command-plan",
        "execute",
        "collect",
        "pre-annotation-validate",
        "annotation-gold",
        "build-checks",
        "gold-validate",
        "replay-runtime",
        "replay-eval",
        "memory-md-baseline",
        "value-eval",
        "report",
    ]:
        command_parser = subparsers.add_parser(name)
        command_parser.add_argument("--case-dir", required=True)
        if name in {"execute", "collect"}:
            command_parser.add_argument("--dry-run", action="store_true")

    case_world = subparsers.add_parser("case-world")
    case_world.add_argument("--case-spec-path", required=True)
    case_world.add_argument("--dataset-root", default=DATASET_ROOT)

    compile_case = subparsers.add_parser("compile-case-phase1")
    compile_case.add_argument("--case-spec-path", required=True)
    compile_case.add_argument("--dataset-root", default=DATASET_ROOT)
    compile_case.add_argument("--dry-run", action="store_true")

    compile_case2 = subparsers.add_parser("compile-case-phase2")
    compile_case2.add_argument("--case-dir", required=True)

    compile_case3 = subparsers.add_parser("compile-case-phase3")
    compile_case3.add_argument("--case-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "spec-generation":
        result = generate_case_spec_stage(
            dataset_root=args.dataset_root,
            difficulty=args.difficulty,
            seed=args.seed,
            comparison_target=args.comparison_target,
            selected_failure_modes=args.selected_failure_modes,
            primary_failure_mode=args.primary_failure_mode,
        )
    elif args.command == "memory-failure-blueprint":
        case_dir_path = _require_case_dir(args.case_dir)
        result = generate_memory_failure_blueprint_stage(case_spec_path=case_dir_path / "case_spec.json", dataset_root=case_dir_path.parent.parent)
    elif args.command == "task-actor-layout":
        result = generate_task_actor_layout_stage(case_dir_path=args.case_dir)
    elif args.command == "case-world":
        result = generate_case_world_stage(case_spec_path=args.case_spec_path, dataset_root=args.dataset_root)
    elif args.command == "characters":
        result = generate_characters_stage(case_dir_path=args.case_dir)
    elif args.command == "state-trajectory":
        result = generate_state_trajectory_stage(case_dir_path=args.case_dir)
    elif args.command == "conversation-plan":
        result = generate_conversation_plan_stage(case_dir_path=args.case_dir)
    elif args.command == "command-plan":
        result = generate_command_plan_stage(case_dir_path=args.case_dir)
    elif args.command == "execute":
        result = execute_case(case_dir_path=args.case_dir, dry_run=args.dry_run)
    elif args.command == "collect":
        result = collect_case(case_dir_path=args.case_dir, dry_run=args.dry_run)
    elif args.command == "pre-annotation-validate":
        result = pre_annotation_validate_stage(case_dir_path=args.case_dir)
    elif args.command == "annotation-gold":
        result = annotation_gold_stage(case_dir_path=args.case_dir)
    elif args.command == "build-checks":
        result = build_checks_stage(case_dir_path=args.case_dir)
    elif args.command == "gold-validate":
        result = gold_validate_stage(case_dir_path=args.case_dir)
    elif args.command == "replay-runtime":
        result = replay_runtime_stage(case_dir_path=args.case_dir)
    elif args.command == "replay-eval":
        result = replay_eval_stage(case_dir_path=args.case_dir)
    elif args.command == "memory-md-baseline":
        result = memory_md_baseline_stage(case_dir_path=args.case_dir)
    elif args.command == "value-eval":
        result = value_eval_stage(case_dir_path=args.case_dir)
    elif args.command == "report":
        result = report_stage(case_dir_path=args.case_dir)
    elif args.command == "compile-case-phase1":
        result = compile_case_phase1(
            case_spec_path=args.case_spec_path,
            dataset_root=args.dataset_root,
            dry_run=args.dry_run,
        )
    elif args.command == "compile-case-phase2":
        result = compile_case_phase2(case_dir_path=args.case_dir)
    elif args.command == "compile-case-phase3":
        result = compile_case_phase3(case_dir_path=args.case_dir)
    else:
        raise ValidationError(f"unsupported command: {args.command}")
    return result


if __name__ == "__main__":
    json.dump(main(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


__all__ = [
    "collect_case",
    "compile_case_phase1",
    "compile_case_phase2",
    "compile_case_phase3",
    "execute_case",
    "annotation_gold_stage",
    "build_checks_stage",
    "gold_validate_stage",
    "generate_case_spec_stage",
    "generate_case_world_stage",
    "generate_characters_stage",
    "generate_command_plan_stage",
    "generate_conversation_plan_stage",
    "generate_memory_failure_blueprint_stage",
    "generate_state_trajectory_stage",
    "generate_task_actor_layout_stage",
    "main",
    "memory_md_baseline_stage",
    "pre_annotation_validate_stage",
    "replay_eval_stage",
    "replay_runtime_stage",
    "report_stage",
    "value_eval_stage",
]
