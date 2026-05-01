from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapter import adapt_fetch_records
from .build_report import build_case_report
from .collector import collect_fetch_records
from .config import DATASET_ROOT, default_config
from .executor import execute_plan
from .io_utils import case_dir, read_json, read_jsonl, write_json, write_jsonl
from .llm_client import DisabledLLMClient, build_llm_client_from_env
from .plan_mapper import build_execution_plan
from .schemas import validate_case_spec
from .story_generator import generate_story_with_mode
from .character_generator import generate_characters_with_mode
from .timeline_planner import generate_timeline_with_mode


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _update_dataset_manifest(dataset_root: str | Path) -> dict[str, Any]:
    root = Path(dataset_root)
    cases_root = root / "cases"
    case_ids = sorted(path.name for path in cases_root.iterdir() if path.is_dir()) if cases_root.exists() else []
    manifest = {
        "dataset_version": "v1",
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


def compile_case(*, case_spec_path: str | Path, dataset_root: str | Path = DATASET_ROOT) -> dict[str, Any]:
    case_spec = _load_case_spec(case_spec_path)
    output_dir = case_dir(dataset_root, case_spec["case_id"])
    write_json(output_dir / "case_spec.json", case_spec)
    llm_client = build_llm_client_from_env()
    active_llm_client = None if isinstance(llm_client, DisabledLLMClient) else llm_client
    story, story_mode = generate_story_with_mode(case_spec, llm_client=active_llm_client)
    write_json(output_dir / "story.json", story)
    characters, characters_mode = generate_characters_with_mode(case_spec, story, llm_client=active_llm_client)
    write_json(output_dir / "characters.json", characters)
    timeline, timeline_mode = generate_timeline_with_mode(case_spec, story, characters, llm_client=active_llm_client)
    write_json(output_dir / "conflict_timeline.json", timeline)
    plan = build_execution_plan(story, characters, timeline)
    write_json(output_dir / "execution_plan.json", plan)
    manifest = _update_dataset_manifest(dataset_root)
    generation_modes = {
        "story": story_mode,
        "characters": characters_mode,
        "timeline": timeline_mode,
    }
    return {
        "case_dir": str(output_dir),
        "dataset_manifest": manifest,
        "llm_mode": _aggregate_llm_mode(generation_modes),
        "generation_modes": generation_modes,
        "case_spec": case_spec,
        "story": story,
        "characters": characters,
        "timeline": timeline,
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
    characters = read_json(case_path / "characters.json")
    timeline = read_json(case_path / "conflict_timeline.json")
    plan = read_json(case_path / "execution_plan.json")
    report = build_case_report(
        case_id=case_spec["case_id"],
        operator_identity=execution_result["operator_identity"],
        delivery_mode=execution_result["delivery_mode"],
        preflight=execution_result.get("preflight") or {},
        fetch_identity="user",
        characters=characters,
        timeline=timeline,
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
    elif args.command == "execute-case":
        result = execute_case(case_dir_path=args.case_dir, dry_run=args.dry_run)
    elif args.command == "adapt-case":
        result = adapt_case(case_dir_path=args.case_dir)
    else:
        result = build_case(case_spec_path=args.case_spec, dataset_root=args.dataset_root, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
