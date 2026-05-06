from __future__ import annotations

from typing import Any

from ..schemas import validate_pre_annotation_report


def build_pre_annotation_validation_report(
    *,
    case_id: str,
    story_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    beat_ids = {row["beat_id"] for row in collected_messages}
    checks = []
    missing_beats = [beat["beat_id"] for beat in story_plan["message_beats"] if beat["beat_id"] not in beat_ids]
    checks.append(
        {
            "check_id": "message_beat_coverage",
            "passed": not missing_beats,
            "details": "所有 story plan beats 都已落地。" if not missing_beats else f"缺少 beats: {missing_beats}",
        }
    )
    checks.append(
        {
            "check_id": "probe_queries_present",
            "passed": bool(story_plan["planned_probe_queries"]),
            "details": "story plan 已包含 planned probe queries。",
        }
    )
    checks.append(
        {
            "check_id": "state_changes_present",
            "passed": bool(story_plan["state_changes"]),
            "details": "story plan 已包含 state_changes。",
        }
    )
    payload = {
        "case_id": case_id,
        "is_valid": all(bool(check["passed"]) for check in checks),
        "checks": checks,
    }
    return validate_pre_annotation_report(payload)
