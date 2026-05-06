from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas import validate_event_annotations, validate_event_eval


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_events(
    *,
    case_id: str,
    event_annotations: list[dict[str, Any]],
    candidate_alignment: dict[str, Any],
    session_alignment: dict[str, Any],
    candidate_events: list[dict[str, Any]],
    session_events: list[dict[str, Any]],
) -> dict[str, Any]:
    annotations = validate_event_annotations(event_annotations)
    candidate_by_id = {
        item["annotation_id"]: item
        for item in candidate_alignment["alignments"]
        if not str(item["annotation_id"]).startswith("pred_only::")
    }
    session_by_id = {
        item["annotation_id"]: item
        for item in session_alignment["alignments"]
        if not str(item["annotation_id"]).startswith("pred_only::")
    }
    predicted_verified = len(session_events)
    false_verified = 0
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped["overall"] = annotations
    for annotation in annotations:
        grouped[annotation["failure_mode"]].append(annotation)

    def compute(rows: list[dict[str, Any]]) -> dict[str, Any]:
        verified_rows = [row for row in rows if row["expected_verdict"] == "verified"]
        needs_review_rows = [row for row in rows if row["expected_verdict"] == "needs_review"]
        rejected_rows = [row for row in rows if row["expected_verdict"] == "rejected"]
        no_event_rows = [row for row in rows if row["expected_verdict"] == "no_event"]
        verified_hits = sum(
            1
            for row in verified_rows
            if session_by_id.get(row["annotation_id"], {}).get("alignment_type") in {"exact", "partial"}
        )
        needs_review_hits = sum(
            1
            for row in needs_review_rows
            if candidate_by_id.get(row["annotation_id"], {}).get("alignment_type") in {"exact", "partial"}
            and session_by_id.get(row["annotation_id"], {}).get("alignment_type") == "unmatched"
        )
        rejected_hits = sum(
            1
            for row in rejected_rows
            if candidate_by_id.get(row["annotation_id"], {}).get("alignment_type") in {"exact", "partial"}
            and session_by_id.get(row["annotation_id"], {}).get("alignment_type") == "unmatched"
        )
        no_event_false_positives = sum(
            1
            for row in no_event_rows
            if candidate_by_id.get(row["annotation_id"], {}).get("alignment_type") in {"exact", "partial"}
        )
        return {
            "verified_precision": _safe_div(verified_hits, predicted_verified),
            "verified_recall": _safe_div(verified_hits, len(verified_rows)),
            "needs_review_accuracy": _safe_div(needs_review_hits, len(needs_review_rows)),
            "rejected_decision_accuracy": _safe_div(rejected_hits, len(rejected_rows)),
            "no_event_false_positive_rate": _safe_div(no_event_false_positives, len(no_event_rows)),
            "false_verified_rate": _safe_div(false_verified, max(1, len(rows))),
            "counts": {
                "verified_gold": len(verified_rows),
                "needs_review_gold": len(needs_review_rows),
                "rejected_gold": len(rejected_rows),
                "no_event_gold": len(no_event_rows),
            },
        }

    for annotation in annotations:
        if annotation["expected_verdict"] != "verified" and session_by_id.get(annotation["annotation_id"], {}).get("alignment_type") in {"exact", "partial"}:
            false_verified += 1

    report = {
        "case_id": case_id,
        "overall": compute(grouped["overall"]),
        "by_failure_mode": {
            key: compute(value)
            for key, value in grouped.items()
            if key != "overall"
        },
    }
    return validate_event_eval(report)
