from __future__ import annotations

from typing import Any

from .eval_common import lexical_overlap, normalize_text
from .schemas import validate_event_alignment, validate_event_annotations


def _prediction_verdict(event: dict[str, Any], *, source: str) -> str:
    if source == "session_events":
        return "verified"
    verdict = normalize_text(((event.get("verification") or {}).get("verdict")))
    if verdict in {"verified", "rejected", "needs_review"}:
        return verdict
    return "candidate"


def _candidate_score(annotation: dict[str, Any], prediction: dict[str, Any]) -> float:
    score = 0.0
    if normalize_text(annotation["evidence_message_id"]) == normalize_text(prediction.get("core_entry_id")):
        score += 0.7
    score += 0.2 * lexical_overlap(annotation["evidence_quote"], prediction.get("evidence_quote") or prediction.get("claim"))
    if normalize_text(annotation["event_type_hint"]) == normalize_text(prediction.get("event_type")):
        score += 0.1
    return min(1.0, score)


def align_events(
    *,
    case_id: str,
    event_annotations: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    prediction_source: str,
) -> dict[str, Any]:
    annotations = validate_event_annotations(event_annotations)
    remaining = list(predictions)
    alignments: list[dict[str, Any]] = []

    for annotation in annotations:
        best_index = None
        best_score = 0.0
        for index, prediction in enumerate(remaining):
            score = _candidate_score(annotation, prediction)
            if score > best_score:
                best_score = score
                best_index = index
        matched = remaining.pop(best_index) if best_index is not None and best_score > 0.25 else None
        if matched is None:
            alignments.append(
                {
                    "annotation_id": annotation["annotation_id"],
                    "prediction_event_id": None,
                    "alignment_type": "unmatched",
                    "score": 0.0,
                    "failure_mode": annotation["failure_mode"],
                    "expected_verdict": annotation["expected_verdict"],
                    "prediction_verdict": None,
                }
            )
            continue
        alignment_type = "exact" if best_score >= 0.9 else "partial"
        alignments.append(
            {
                "annotation_id": annotation["annotation_id"],
                "prediction_event_id": normalize_text(matched.get("event_id")),
                "alignment_type": alignment_type,
                "score": round(best_score, 4),
                "failure_mode": annotation["failure_mode"],
                "expected_verdict": annotation["expected_verdict"],
                "prediction_verdict": _prediction_verdict(matched, source=prediction_source),
            }
        )

    for leftover in remaining:
        alignments.append(
            {
                "annotation_id": f"pred_only::{normalize_text(leftover.get('event_id'))}",
                "prediction_event_id": normalize_text(leftover.get("event_id")),
                "alignment_type": "over_split",
                "score": 0.0,
                "failure_mode": normalize_text(leftover.get("failure_mode")) or "unknown",
                "expected_verdict": "no_event",
                "prediction_verdict": _prediction_verdict(leftover, source=prediction_source),
            }
        )

    summary = {
        "exact": sum(1 for item in alignments if item["alignment_type"] == "exact"),
        "partial": sum(1 for item in alignments if item["alignment_type"] == "partial"),
        "unmatched": sum(1 for item in alignments if item["alignment_type"] == "unmatched"),
        "over_split": sum(1 for item in alignments if item["alignment_type"] == "over_split"),
        "over_merged": sum(1 for item in alignments if item["alignment_type"] == "over_merged"),
    }
    return validate_event_alignment(
        {
            "case_id": case_id,
            "target_prediction_source": prediction_source,
            "alignments": alignments,
            "summary": summary,
        }
    )
