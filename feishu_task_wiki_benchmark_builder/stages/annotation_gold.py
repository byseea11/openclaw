from __future__ import annotations

from typing import Any

from ..schemas import validate_annotation_gold_rows


def build_annotation_gold(
    *,
    case_id: str,
    family_id: str,
    story_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    beat_lookup = {beat["beat_id"]: beat for beat in story_plan["message_beats"]}
    for observed in collected_messages:
        if not (observed.get("annotation_target") or observed.get("event_bearing")):
            continue
        beat_id = str(observed.get("beat_id") or "")
        beat = beat_lookup.get(beat_id, {})
        annotation_key = beat_id or str(observed.get("turn_id") or observed["message_id"])
        rows.append(
            {
                "annotation_id": f"{case_id}_{annotation_key}",
                "case_id": case_id,
                "family_id": family_id,
                "beat_id": beat_id,
                "turn_id": str(observed.get("turn_id") or ""),
                "turn_kind": str(observed.get("turn_kind") or ""),
                "purpose": str(beat.get("purpose") or observed.get("turn_kind") or "event_bearing"),
                "message_id": observed["message_id"],
                "evidence_text": observed["message_text"],
                "session_id": observed["session_id"],
                "annotation_type": "observed_event",
            }
        )
    return validate_annotation_gold_rows(rows)
