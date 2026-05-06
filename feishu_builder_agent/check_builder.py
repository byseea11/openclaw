from __future__ import annotations

from typing import Any

from .schemas import (
    validate_block_annotations,
    validate_case_spec,
    validate_coverage_spec,
    validate_event_annotations,
    validate_pre_annotation_validation_report,
    validate_query_benchmark,
)


def build_checks(
    *,
    case_spec: dict[str, Any],
    coverage_spec: dict[str, Any],
    pre_annotation_validation_report: dict[str, Any],
    event_annotations: list[dict[str, Any]],
    block_annotations: dict[str, Any],
    query_benchmark: dict[str, Any],
) -> dict[str, Any]:
    case_spec = validate_case_spec(case_spec)
    coverage_spec = validate_coverage_spec(coverage_spec)
    prevalidation = validate_pre_annotation_validation_report(pre_annotation_validation_report)
    event_annotations = validate_event_annotations(event_annotations)
    block_annotations = validate_block_annotations(block_annotations)
    query_benchmark = validate_query_benchmark(query_benchmark)

    observed_modes = {row["failure_mode"] for row in event_annotations}
    required_modes = set(coverage_spec["required_failure_modes"])
    complexity_gate = {
        "case_id": case_spec["case_id"],
        "status": "pass" if required_modes.issubset(observed_modes) else "fail",
        "required_failure_modes": sorted(required_modes),
        "observed_failure_modes": sorted(observed_modes),
        "required_query_types": coverage_spec["required_query_types"],
        "query_count": len(query_benchmark["queries"]),
        "event_annotation_count": len(event_annotations),
        "block_annotation_count": len(block_annotations["blocks"]),
    }
    integrity_gate = {
        "case_id": case_spec["case_id"],
        "status": prevalidation["status"],
        "pre_annotation_status": prevalidation["status"],
        "all_traps_landed": all(item["landed"] for item in prevalidation["traps"]),
        "missing_failure_modes": prevalidation["missing_failure_modes"],
        "query_count": len(query_benchmark["queries"]),
    }
    eval_manifest = {
        "case_id": case_spec["case_id"],
        "task_id": case_spec["task_id"],
        "dataset_version": "v3",
        "builder_version": "v3-phase3",
        "gold_artifacts": {
            "event_annotations": "gold/event_annotations.jsonl",
            "block_annotations": "gold/block_annotations.json",
            "query_benchmark": "gold/query_benchmark.json",
        },
        "prediction_artifacts": {
            "candidate_events": "predictions/candidate_events.jsonl",
            "session_events": "predictions/session_events.jsonl",
            "task_wiki_state": "predictions/task_wiki_state.json",
        },
        "reports": {
            "event_alignment": "reports/event_alignment.json",
            "event_eval": "reports/event_eval.json",
            "block_eval": "reports/block_eval.json",
            "qa_eval": "reports/qa_eval.json",
            "value_eval": "reports/value_eval.json",
            "overall_eval": "reports/overall_eval.json",
        },
    }
    return {
        "complexity_gate": complexity_gate,
        "integrity_gate": integrity_gate,
        "eval_manifest": eval_manifest,
    }
