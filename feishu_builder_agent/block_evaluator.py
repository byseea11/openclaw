from __future__ import annotations

from collections import defaultdict
from typing import Any

from .eval_common import normalize_text
from .schemas import validate_block_annotations, validate_block_eval


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _task_wiki_topics(task_wiki_state: dict[str, Any]) -> set[str]:
    topics: set[str] = set()
    for item in task_wiki_state.get("related_blocks") or []:
        if isinstance(item, dict):
            for key in ("topic_key", "topic_title"):
                value = normalize_text(item.get(key))
                if value:
                    topics.add(value)
    for section_items in (task_wiki_state.get("sections") or {}).values():
        if not isinstance(section_items, list):
            continue
        for item in section_items:
            if isinstance(item, dict):
                value = normalize_text(item.get("topic_key") or item.get("topic_title"))
                if value:
                    topics.add(value)
    return topics


def _all_claims(task_wiki_state: dict[str, Any]) -> str:
    claims: list[str] = [normalize_text(task_wiki_state.get("current_summary"))]
    for section_items in (task_wiki_state.get("sections") or {}).values():
        if not isinstance(section_items, list):
            continue
        for item in section_items:
            if isinstance(item, dict):
                claims.append(normalize_text(item.get("claim") or item.get("summary")))
    return " ".join(item for item in claims if item)


def evaluate_blocks(
    *,
    case_id: str,
    block_annotations: dict[str, Any],
    event_alignment: dict[str, Any],
    task_wiki_state: dict[str, Any],
) -> dict[str, Any]:
    blocks = validate_block_annotations(block_annotations)
    topics = _task_wiki_topics(task_wiki_state)
    all_claims = _all_claims(task_wiki_state)
    aligned_ids = {
        item["annotation_id"]
        for item in event_alignment.get("alignments") or []
        if item.get("alignment_type") in {"exact", "partial"}
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped["overall"] = blocks["blocks"]
    for block in blocks["blocks"]:
        grouped[block["failure_mode"]].append(block)

    def compute(rows: list[dict[str, Any]], *, aligned_only: bool) -> dict[str, Any]:
        eligible = []
        for block in rows:
            if not aligned_only:
                eligible.append(block)
                continue
            if any(annotation_id in aligned_ids for annotation_id in block["gold_event_annotation_ids"]):
                eligible.append(block)
        topic_hits = 0
        current_state_hits = 0
        for block in eligible:
            if block["topic_key"] in topics or block["topic_title"] in topics:
                topic_hits += 1
            if any(state["value"] in all_claims for state in block["current_state"]):
                current_state_hits += 1
        count = len(eligible)
        return {
            "eligible_blocks": count,
            "topic_hit_rate": _safe_div(topic_hits, count),
            "current_state_hit_rate": _safe_div(current_state_hits, count),
        }

    overall = compute(grouped["overall"], aligned_only=False)
    aligned = compute(grouped["overall"], aligned_only=True)
    report = {
        "case_id": case_id,
        "overall": {
            "topic_hit_rate": overall["topic_hit_rate"],
            "current_state_hit_rate": overall["current_state_hit_rate"],
        },
        "by_failure_mode": {
            key: compute(value, aligned_only=False)
            for key, value in grouped.items()
            if key != "overall"
        },
        "block_eval_on_all_gold_events": {
            "extractor_failure_view": 1.0 - overall["topic_hit_rate"],
            "projector_failure_view": 1.0 - overall["current_state_hit_rate"],
        },
        "block_eval_on_aligned_events_only": {
            "extractor_failure_view": 1.0 - aligned["topic_hit_rate"],
            "projector_failure_view": 1.0 - aligned["current_state_hit_rate"],
        },
    }
    return validate_block_eval(report)
