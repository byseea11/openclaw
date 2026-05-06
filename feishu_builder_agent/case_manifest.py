from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .schemas import validate_case_manifest


STAGE_ORDER = [
    "spec-generation",
    "memory-failure-blueprint",
    "task-actor-layout",
    "case-world",
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
]

ARTIFACT_CANDIDATES = {
    "case_spec": "case_spec.json",
    "case_manifest": "case_manifest.json",
    "memory_failure_blueprint": "input/memory_failure_blueprint.json",
    "task_actor_layout": "input/task_actor_layout.json",
    "case_world": "input/case_world.json",
    "characters": "input/characters.json",
    "actor_registry": "input/actor_registry.json",
    "state_trajectory": "input/state_trajectory.json",
    "conversation_plan": "input/conversation_plan.json",
    "command_plan": "input/command_plan.jsonl",
    "execution_plan": "execution_plan.json",
    "execution_result": "execution_result.json",
    "collected_messages": "data/collected_messages.jsonl",
    "openclaw_message_ingress": "data/openclaw_message_ingress.jsonl",
    "pre_annotation_validation_report": "checks/pre_annotation_validation_report.json",
    "event_annotations": "gold/event_annotations.jsonl",
    "block_annotations": "gold/block_annotations.json",
    "query_benchmark": "gold/query_benchmark.json",
    "complexity_gate": "checks/complexity_gate.json",
    "integrity_gate": "checks/integrity_gate.json",
    "eval_manifest": "checks/eval_manifest.json",
    "candidate_events": "predictions/candidate_events.jsonl",
    "session_events": "predictions/session_events.jsonl",
    "session_wiki_state": "predictions/session_wiki_state.json",
    "task_index_state": "predictions/task_index_state.json",
    "task_wiki_state": "predictions/task_wiki_state.json",
    "event_alignment": "reports/event_alignment.json",
    "event_eval": "reports/event_eval.json",
    "block_eval": "reports/block_eval.json",
    "qa_eval": "reports/qa_eval.json",
    "memory_md_baseline_report": "reports/memory_md_baseline_report.json",
    "raw_message_rag_report": "reports/raw_message_rag_report.json",
    "value_eval": "reports/value_eval.json",
    "overall_eval": "reports/overall_eval.json",
    "final_benchmark_report": "reports/final_benchmark_report.json",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def discover_artifacts(case_dir: str | Path) -> dict[str, str]:
    root = Path(case_dir)
    artifacts: dict[str, str] = {}
    for key, relpath in ARTIFACT_CANDIDATES.items():
        if (root / relpath).exists():
            artifacts[key] = relpath
    return artifacts


def _infer_completed_stages(artifacts: dict[str, str]) -> list[str]:
    completed: list[str] = []
    checks = {
        "spec-generation": "case_spec",
        "memory-failure-blueprint": "memory_failure_blueprint",
        "task-actor-layout": "task_actor_layout",
        "case-world": "case_world",
        "characters": "characters",
        "state-trajectory": "state_trajectory",
        "conversation-plan": "conversation_plan",
        "command-plan": "command_plan",
        "execute": "execution_result",
        "collect": "collected_messages",
        "pre-annotation-validate": "pre_annotation_validation_report",
        "annotation-gold": "event_annotations",
        "build-checks": "eval_manifest",
        "gold-validate": "integrity_gate",
        "replay-runtime": "task_wiki_state",
        "replay-eval": "qa_eval",
        "memory-md-baseline": "memory_md_baseline_report",
        "value-eval": "value_eval",
        "report": "final_benchmark_report",
    }
    for stage in STAGE_ORDER:
        artifact_key = checks.get(stage)
        if artifact_key and artifact_key in artifacts:
            completed.append(stage)
    return completed


def load_case_manifest(case_dir: str | Path) -> dict[str, Any] | None:
    path = Path(case_dir) / "case_manifest.json"
    if not path.exists():
        return None
    return validate_case_manifest(read_json(path))


def update_case_manifest(
    case_dir: str | Path,
    *,
    case_id: str,
    builder_version: str = "v3-phase3",
    dataset_version: str = "v3",
    completed_stage: str | None = None,
) -> dict[str, Any]:
    root = Path(case_dir)
    current = load_case_manifest(root) or {
        "case_id": case_id,
        "dataset_version": dataset_version,
        "builder_version": builder_version,
        "case_dir": str(root),
        "completed_stages": [],
        "artifacts": {},
        "updated_at": _utc_now_iso(),
    }
    artifacts = discover_artifacts(root)
    completed_stages = current.get("completed_stages", [])
    if completed_stage and completed_stage not in completed_stages:
        completed_stages = [*completed_stages, completed_stage]
    for inferred in _infer_completed_stages(artifacts):
        if inferred not in completed_stages:
            completed_stages.append(inferred)
    manifest = validate_case_manifest(
        {
            "case_id": case_id,
            "dataset_version": dataset_version,
            "builder_version": builder_version,
            "case_dir": str(root),
            "completed_stages": completed_stages,
            "artifacts": artifacts,
            "updated_at": _utc_now_iso(),
        }
    )
    write_json(root / "case_manifest.json", manifest)
    return manifest
