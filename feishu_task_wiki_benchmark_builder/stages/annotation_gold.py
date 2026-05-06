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
    message_lookup = {row["beat_id"]: row for row in collected_messages}
    for beat in story_plan["message_beats"]:
        observed = message_lookup[beat["beat_id"]]
        rows.append(
            {
                "annotation_id": f"{case_id}_{beat['beat_id']}",
                "case_id": case_id,
                "family_id": family_id,
                "beat_id": beat["beat_id"],
                "purpose": beat["purpose"],
                "message_id": observed["message_id"],
                "evidence_text": observed["message_text"],
                "session_id": observed["session_id"],
                "annotation_type": "observed_event",
            }
        )
    return validate_annotation_gold_rows(rows)
