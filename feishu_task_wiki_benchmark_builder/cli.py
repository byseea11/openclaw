from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_DATASET_ROOT
from .io import ensure_dir, read_json, read_jsonl, write_json, write_jsonl, write_text
from .prompt import (
    build_capability_brief_system_prompt,
    build_case_world_system_prompt,
    build_family_selection_system_prompt,
    build_story_plan_system_prompt,
)
from .runtime.collector import collect_messages
from .runtime.executor import execute_command_plan
from .schemas import (
    validate_case_spec,
    validate_case_world,
    validate_memory_capability_brief,
    validate_pre_annotation_report,
    validate_replay_eval,
    validate_story_plan,
)
from .stages.annotation_gold import build_annotation_gold
from .stages.baseline_eval import build_baseline_eval
from .stages.benchmark_report import build_benchmark_report
from .stages.capability_brief import build_memory_capability_brief
from .stages.case_spec import build_case_spec
from .stages.case_world import build_case_world
from .stages.command_plan import build_command_plan
from .stages.common import case_dir_for, ensure_case_layout
from .stages.dataset_plan import build_dataset_generation_plan
from .stages.family_selection import select_family
from .stages.observed_validation import build_pre_annotation_validation_report
from .stages.query_benchmark import build_query_benchmark
from .stages.replay_eval import build_replay_eval
from .stages.story_plan import build_story_plan
from .stages.value_eval import build_value_eval


def _resolve_dataset_root(dataset_root: str | Path | None) -> Path:
    return Path(dataset_root) if dataset_root is not None else DEFAULT_DATASET_ROOT


def _load_case_context(case_dir: str | Path) -> dict[str, Any]:
    case_path = Path(case_dir)
    return {
        "case_path": case_path,
        "case_spec": validate_case_spec(read_json(case_path / "case_spec.json")),
        "capability_brief": validate_memory_capability_brief(
            read_json(case_path / "input" / "memory_capability_brief.json")
        ),
        "case_world": validate_case_world(read_json(case_path / "input" / "case_world.json")),
        "story_plan": validate_story_plan(read_json(case_path / "input" / "story_plan.json")),
    }


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


def compile_phase1(
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    seed: int | None = None,
    difficulty: str = "medium",
    family_id: str | None = None,
    comparison_target: str = "default_memory_architectures",
) -> dict[str, Any]:
    dataset_path = _resolve_dataset_root(dataset_root)
    family_prompt = build_family_selection_system_prompt()
    selection = select_family(seed=seed, requested_family_id=family_id)
    capability_prompt = build_capability_brief_system_prompt()
    brief = build_memory_capability_brief(family_id=selection["family_id"])
    case_spec = build_case_spec(
        family_id=selection["family_id"],
        difficulty=difficulty,
        seed=selection["seed"],
        comparison_target=comparison_target,
    )
    case_path = case_dir_for(dataset_path, case_spec["case_id"])
    ensure_case_layout(case_path)
    world_prompt = build_case_world_system_prompt()
    case_world = build_case_world(case_spec=case_spec, capability_brief=brief)
    story_prompt = build_story_plan_system_prompt()
    story_plan = build_story_plan(case_spec=case_spec, case_world=case_world, capability_brief=brief)
    command_plan = build_command_plan(story_plan=story_plan)
    execution_rows = execute_command_plan(case_id=case_spec["case_id"], command_plan=command_plan)
    collected_messages, openclaw_ingress = collect_messages(
        case_id=case_spec["case_id"],
        execution_rows=execution_rows,
    )
    validation_report = build_pre_annotation_validation_report(
        case_id=case_spec["case_id"],
        story_plan=story_plan,
        collected_messages=collected_messages,
    )

    write_json(case_path / "input" / "family_selection.json", selection)
    write_json(case_path / "input" / "memory_capability_brief.json", brief)
    write_json(case_path / "case_spec.json", case_spec)
    write_json(case_path / "input" / "case_world.json", case_world)
    write_json(case_path / "input" / "story_plan.json", story_plan)
    write_jsonl(case_path / "input" / "command_plan.jsonl", command_plan)
    write_jsonl(case_path / "runtime" / "executed_commands.jsonl", execution_rows)
    write_jsonl(case_path / "data" / "collected_messages.jsonl", collected_messages)
    write_jsonl(case_path / "data" / "openclaw_message_ingress.jsonl", openclaw_ingress)
    write_json(case_path / "checks" / "pre_annotation_validation_report.json", validation_report)

    return {
        "case_dir": str(case_path),
        "case_id": case_spec["case_id"],
        "prompt_builders_used": {
            "family-selection": family_prompt.splitlines()[0] if family_prompt else "",
            "memory-capability-brief": capability_prompt.splitlines()[0] if capability_prompt else "",
            "case-world": world_prompt.splitlines()[0] if world_prompt else "",
            "story-plan": story_prompt.splitlines()[0] if story_prompt else "",
        },
    }


def compile_phase2(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_case_context(case_dir)
    case_path = context["case_path"]
    collected_messages = read_jsonl(case_path / "data" / "collected_messages.jsonl")
    validation_report = validate_pre_annotation_report(
        read_json(case_path / "checks" / "pre_annotation_validation_report.json")
    )
    if not validation_report["is_valid"]:
        raise ValueError("pre_annotation_validation_report indicates the case is invalid")
    annotation_gold_rows = build_annotation_gold(
        case_id=context["case_spec"]["case_id"],
        family_id=context["case_spec"]["family_id"],
        story_plan=context["story_plan"],
        collected_messages=collected_messages,
    )
    query_benchmark = build_query_benchmark(
        case_id=context["case_spec"]["case_id"],
        family_id=context["case_spec"]["family_id"],
        story_plan=context["story_plan"],
        annotation_gold_rows=annotation_gold_rows,
    )
    replay_eval = build_replay_eval(
        case_id=context["case_spec"]["case_id"],
        family_id=context["case_spec"]["family_id"],
        query_benchmark=query_benchmark,
    )
    write_jsonl(case_path / "gold" / "annotation_gold.jsonl", annotation_gold_rows)
    write_json(case_path / "gold" / "query_benchmark.json", query_benchmark)
    write_json(case_path / "reports" / "replay_eval.json", replay_eval)
    return {"case_dir": str(case_path), "case_id": context["case_spec"]["case_id"]}


def compile_phase3(*, case_dir: str | Path) -> dict[str, Any]:
    context = _load_case_context(case_dir)
    case_path = context["case_path"]
    replay_eval = validate_replay_eval(read_json(case_path / "reports" / "replay_eval.json"))
    baseline_eval = build_baseline_eval(
        case_id=context["case_spec"]["case_id"],
        family_id=context["case_spec"]["family_id"],
        replay_eval=replay_eval,
    )
    value_eval = build_value_eval(
        case_id=context["case_spec"]["case_id"],
        family_id=context["case_spec"]["family_id"],
        baseline_eval=baseline_eval,
    )
    report_text = build_benchmark_report(
        case_spec=context["case_spec"],
        capability_brief=context["capability_brief"],
        replay_eval=replay_eval,
        baseline_eval=baseline_eval,
        value_eval=value_eval,
    )
    write_json(case_path / "reports" / "baseline_eval.json", baseline_eval)
    write_json(case_path / "reports" / "value_eval.json", value_eval)
    write_text(case_path / "reports" / "final_benchmark_report.md", report_text)
    return {"case_dir": str(case_path), "case_id": context["case_spec"]["case_id"]}


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
    dataset_plan_parser.add_argument("--difficulty", default="medium")

    for name in ("phase1", "build-all"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
        subparser.add_argument("--seed", type=int, default=1)
        subparser.add_argument("--difficulty", default="medium")
        subparser.add_argument("--family-id")
        subparser.add_argument("--comparison-target", default="default_memory_architectures")

    for name in ("phase2", "phase3"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--case-dir", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "dataset-plan":
        result = generate_dataset_plan_stage(
            dataset_root=args.dataset_root,
            dataset_size=args.dataset_size,
            seed=args.seed,
            difficulty=args.difficulty,
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
        result = compile_phase2(case_dir=args.case_dir)
    elif args.command == "phase3":
        result = compile_phase3(case_dir=args.case_dir)
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

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
