from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapter import adapt_fetch_records
from .build_report import build_case_report
from .case_world_generator import generate_case_world_with_mode
from .collector import collect_fetch_records
from .complexity_validator import build_complexity_report
from .config import DATASET_ROOT
from .conversation_plan_generator import generate_conversation_plan_with_mode
from .dataset_validator import build_dataset_validation_report
from .executor import execute_plan
from .gold_generator import generate_gold_artifacts
from .io_utils import case_dir, read_json, read_jsonl, write_json, write_jsonl
from .llm_client import DisabledLLMClient, build_llm_client_from_env
from .message_realizer import realize_messages_with_mode
from .plan_mapper import build_execution_plan_from_realized_messages
from .schemas import ValidationError, validate_case_seed, validate_case_spec
from .story_generator import generate_story_with_mode
from .character_generator import generate_characters_with_mode
from .timeline_planner import generate_timeline_with_mode
from .utterance_generator import generate_utterance_plan_with_mode


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
    modes = list(generation_modes.values())
    if modes and all(mode == "live" for mode in modes):
        return "live"
    if modes and all(mode == "fallback" for mode in modes):
        return "fallback"
    return "mixed"


def _derive_case_seed(case_spec: dict[str, Any]) -> dict[str, Any]:
    spec = validate_case_spec(case_spec)
    profile_by_difficulty = {
        "easy": {
            "session_count_target": 3,
            "source_session_count_target": 3,
            "message_count_target": 18,
            "topic_count_target": 3,
            "thread_reply_depth_target": 3,
            "state_transition_target": 4,
            "supersession_target": 1,
            "cross_source_revision_target": 1,
            "event_family_target": 5,
        },
        "medium": {
            "session_count_target": 3,
            "source_session_count_target": 3,
            "message_count_target": 20,
            "topic_count_target": 4,
            "thread_reply_depth_target": 5,
            "state_transition_target": 8,
            "supersession_target": 1,
            "cross_source_revision_target": 2,
            "event_family_target": 6,
        },
        "hard": {
            "session_count_target": 4,
            "source_session_count_target": 4,
            "message_count_target": 24,
            "topic_count_target": 4,
            "thread_reply_depth_target": 6,
            "state_transition_target": 10,
            "supersession_target": 2,
            "cross_source_revision_target": 2,
            "event_family_target": 7,
        },
    }
    profile = profile_by_difficulty.get(spec["difficulty"], profile_by_difficulty["medium"])
    return validate_case_seed(
        {
            "case_id": spec["case_id"],
            "task_id": spec["task_id"],
            "title": spec["title"],
            "domain": "enterprise_product_launch",
            "company_type": spec["company_type"],
            "departments": spec["departments"],
            "main_goal": spec["main_goal"],
            "difficulty": spec["difficulty"],
            "seed": spec["seed"],
            "complexity_profile": profile,
        }
    )


def _write_v2_artifacts(
    *,
    output_dir: Path,
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
    conversation_plan: dict[str, Any],
    utterance_plan: list[dict[str, Any]],
    realized_messages: list[dict[str, Any]],
    expected_events: list[dict[str, Any]],
    expected_memory_blocks: dict[str, Any],
    expected_current_state: dict[str, Any],
    complexity_report: dict[str, Any],
    dataset_validation_report: dict[str, Any],
) -> None:
    write_json(output_dir / "input" / "case_seed.json", case_seed)
    write_json(output_dir / "input" / "case_world.json", case_world)
    write_json(output_dir / "input" / "characters.json", characters)
    write_json(output_dir / "input" / "conversation_plan.json", conversation_plan)
    write_jsonl(output_dir / "input" / "utterance_plan.jsonl", utterance_plan)
    write_jsonl(output_dir / "data" / "realized_messages.jsonl", realized_messages)
    write_jsonl(output_dir / "gold" / "expected_events.jsonl", expected_events)
    write_json(output_dir / "gold" / "expected_memory_blocks.json", expected_memory_blocks)
    write_json(output_dir / "gold" / "expected_current_state.json", expected_current_state)
    write_json(output_dir / "checks" / "conversation_complexity_report.json", complexity_report)
    write_json(output_dir / "checks" / "dataset_validation_report.json", dataset_validation_report)


def _compile_v2_bundle(
    *,
    case_spec_path: str | Path,
    dataset_root: str | Path,
) -> dict[str, Any]:
    case_spec = _load_case_spec(case_spec_path)
    output_dir = case_dir(dataset_root, case_spec["case_id"])
    write_json(output_dir / "case_spec.json", case_spec)
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    case_seed = _derive_case_seed(case_spec)
    case_world, case_world_mode = generate_case_world_with_mode(case_seed, llm_client=active_llm_client)
    story, story_mode = generate_story_with_mode(case_spec, llm_client=active_llm_client)
    characters, characters_mode = generate_characters_with_mode(case_spec, story, llm_client=active_llm_client)
    timeline, timeline_mode = generate_timeline_with_mode(case_spec, story, characters, llm_client=active_llm_client)
    conversation_plan, conversation_plan_mode = generate_conversation_plan_with_mode(
        case_seed,
        case_world,
        characters,
        llm_client=active_llm_client,
    )
    utterance_plan, utterance_plan_mode = generate_utterance_plan_with_mode(
        conversation_plan,
        characters,
        llm_client=active_llm_client,
    )
    realized_messages, realization_mode = realize_messages_with_mode(
        utterance_plan,
        characters,
        llm_client=active_llm_client,
    )
    complexity_report = build_complexity_report(case_seed, conversation_plan, realized_messages)
    gold = generate_gold_artifacts(conversation_plan, realized_messages)
    dataset_validation_report = build_dataset_validation_report(
        case_seed=case_seed,
        case_world=case_world,
        characters=characters,
        conversation_plan=conversation_plan,
        utterance_plan=utterance_plan,
        realized_messages=realized_messages,
        complexity_report=complexity_report,
        expected_events=gold["expected_events"],
        expected_memory_blocks=gold["expected_memory_blocks"],
        expected_current_state=gold["expected_current_state"],
    )
    _write_v2_artifacts(
        output_dir=output_dir,
        case_seed=case_seed,
        case_world=case_world,
        characters=characters,
        conversation_plan=conversation_plan,
        utterance_plan=utterance_plan,
        realized_messages=realized_messages,
        expected_events=gold["expected_events"],
        expected_memory_blocks=gold["expected_memory_blocks"],
        expected_current_state=gold["expected_current_state"],
        complexity_report=complexity_report,
        dataset_validation_report=dataset_validation_report,
    )
    if not complexity_report["passed"]:
        raise ValidationError(f"case {case_spec['case_id']} failed complexity gate: {', '.join(complexity_report['failed_checks'])}")
    if not dataset_validation_report["passed"]:
        raise ValidationError(
            f"case {case_spec['case_id']} failed dataset validation: {'; '.join(dataset_validation_report['errors'])}"
        )
    generation_modes = {
        "case_world": case_world_mode,
        "story": story_mode,
        "characters": characters_mode,
        "timeline": timeline_mode,
        "conversation_plan": conversation_plan_mode,
        "utterance_plan": utterance_plan_mode,
        "message_realizer": realization_mode,
    }
    return {
        "case_spec": case_spec,
        "case_seed": case_seed,
        "case_world": case_world,
        "characters": characters,
        "conversation_plan": conversation_plan,
        "utterance_plan": utterance_plan,
        "realized_messages": realized_messages,
        "complexity_report": complexity_report,
        "dataset_validation_report": dataset_validation_report,
        "gold": gold,
        "generation_modes": generation_modes,
        "llm_mode": _aggregate_llm_mode(generation_modes),
        "case_dir": str(output_dir),
    }


def compile_case(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT) -> dict[str, Any]:
    compiled = _compile_v2_bundle(case_spec_path=case_spec_path, dataset_root=dataset_root)
    output_dir = Path(compiled["case_dir"])
    plan = build_execution_plan_from_realized_messages(
        compiled["characters"],
        compiled["conversation_plan"],
        compiled["realized_messages"],
    )
    write_json(output_dir / "execution_plan.json", plan)
    manifest = _update_dataset_manifest(dataset_root)
    return {
        "case_dir": compiled["case_dir"],
        "dataset_manifest": manifest,
        "llm_mode": compiled["llm_mode"],
        "generation_modes": compiled["generation_modes"],
        "case_spec": compiled["case_spec"],
        "case_seed": compiled["case_seed"],
        "case_world": compiled["case_world"],
        "characters": compiled["characters"],
        "conversation_plan": compiled["conversation_plan"],
        "utterance_plan": compiled["utterance_plan"],
        "realized_messages": compiled["realized_messages"],
        "complexity_report": compiled["complexity_report"],
        "dataset_validation_report": compiled["dataset_validation_report"],
        "gold": compiled["gold"],
        "execution_plan": plan,
    }


def execute_case(*, case_dir_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    case_path = Path(case_dir_path)
    plan = read_json(case_path / "execution_plan.json")
    resume_result = read_json(case_path / "execution_result.json") if (case_path / "execution_result.json").exists() else None
    result = execute_plan(plan, dry_run=dry_run, resume_result=resume_result)
    write_json(case_path / "execution_result.json", result)
    return result


def adapt_case(*, case_dir_path: str | Path) -> dict[str, Any]:
    case_path = Path(case_dir_path)
    case_spec = read_json(case_path / "case_spec.json")
    execution_result = read_json(case_path / "execution_result.json")
    fetch_records = read_jsonl(case_path / "lark_fetch_records.jsonl")
    ingress_events, adapter_report = adapt_fetch_records(case_spec, execution_result, fetch_records)
    write_jsonl(case_path / "openclaw_message_ingress.jsonl", ingress_events)
    write_json(case_path / "adapter_report.json", adapter_report)
    characters = read_json(case_path / "input" / "characters.json")
    conversation_plan = read_json(case_path / "input" / "conversation_plan.json")
    plan = read_json(case_path / "execution_plan.json")
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
    return {"adapter_report": adapter_report, "build_report": report}


def build_case(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT, dry_run: bool = False) -> dict[str, Any]:
    compiled = compile_case(case_spec_path=case_spec_path, dataset_root=dataset_root)
    output_dir = Path(compiled["case_dir"])
    execution_result = execute_case(case_dir_path=output_dir, dry_run=dry_run)
    if dry_run:
        return {"compiled": compiled, "execution_result": execution_result}
    plan = read_json(output_dir / "execution_plan.json")
    fetch_records = collect_fetch_records(plan, execution_result)
    write_jsonl(output_dir / "lark_fetch_records.jsonl", fetch_records)
    adapted = adapt_case(case_dir_path=output_dir)
    return {"compiled": compiled, "execution_result": execution_result, "adapted": adapted}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Feishu IM dataset cases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile-case")
    compile_parser.add_argument("--case-spec", required=True)
    compile_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    case_world_parser = subparsers.add_parser("generate-case-world")
    case_world_parser.add_argument("--case-spec", required=True)
    case_world_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    conversation_parser = subparsers.add_parser("generate-conversation-plan")
    conversation_parser.add_argument("--case-spec", required=True)
    conversation_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    utterance_parser = subparsers.add_parser("generate-utterances")
    utterance_parser.add_argument("--case-spec", required=True)
    utterance_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    realize_parser = subparsers.add_parser("realize-messages")
    realize_parser.add_argument("--case-spec", required=True)
    realize_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    gold_parser = subparsers.add_parser("generate-gold")
    gold_parser.add_argument("--case-spec", required=True)
    gold_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    validate_parser = subparsers.add_parser("validate-case")
    validate_parser.add_argument("--case-spec", required=True)
    validate_parser.add_argument("--dataset-root", default=DATASET_ROOT)

    execute_parser = subparsers.add_parser("execute-case")
    execute_parser.add_argument("--case-dir", required=True)
    execute_parser.add_argument("--dry-run", action="store_true")

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
        result = _compile_v2_bundle(case_spec_path=args.case_spec, dataset_root=args.dataset_root)["case_world"]
    elif args.command == "generate-conversation-plan":
        result = _compile_v2_bundle(case_spec_path=args.case_spec, dataset_root=args.dataset_root)["conversation_plan"]
    elif args.command == "generate-utterances":
        result = {"rows": _compile_v2_bundle(case_spec_path=args.case_spec, dataset_root=args.dataset_root)["utterance_plan"]}
    elif args.command == "realize-messages":
        result = {"rows": _compile_v2_bundle(case_spec_path=args.case_spec, dataset_root=args.dataset_root)["realized_messages"]}
    elif args.command == "generate-gold":
        result = _compile_v2_bundle(case_spec_path=args.case_spec, dataset_root=args.dataset_root)["gold"]
    elif args.command == "validate-case":
        result = _compile_v2_bundle(case_spec_path=args.case_spec, dataset_root=args.dataset_root)["dataset_validation_report"]
    elif args.command == "execute-case":
        result = execute_case(case_dir_path=args.case_dir, dry_run=args.dry_run)
    elif args.command == "adapt-case":
        result = adapt_case(case_dir_path=args.case_dir)
    else:
        result = build_case(case_spec_path=args.case_spec, dataset_root=args.dataset_root, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
