from __future__ import annotations

from typing import Any

from ..schemas import validate_pre_annotation_report


def build_pre_annotation_validation_report(
    *,
    case_id: str,
    story_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
    openclaw_ingress: list[dict[str, Any]] | None = None,
    official_file_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    beat_ids = {row["beat_id"] for row in collected_messages if row.get("beat_id")}
    annotation_targets = [
        row for row in collected_messages if row.get("annotation_target") or row.get("event_bearing")
    ]
    session_ids = {row["session_id"] for row in collected_messages}
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
    checks.append(
        {
            "check_id": "total_message_count",
            "passed": bool(collected_messages),
            "details": f"observed messages: {len(collected_messages)}",
        }
    )
    checks.append(
        {
            "check_id": "session_distribution",
            "passed": bool(session_ids),
            "details": f"observed sessions: {len(session_ids)}",
        }
    )
    checks.append(
        {
            "check_id": "annotation_target_count",
            "passed": bool(annotation_targets),
            "details": f"annotation/event-bearing messages: {len(annotation_targets)}",
        }
    )
    if openclaw_ingress is not None:
        checks.append(
            {
                "check_id": "openclaw_ingress_count",
                "passed": len(openclaw_ingress) == len(collected_messages),
                "details": f"openclaw ingress: {len(openclaw_ingress)} / observed: {len(collected_messages)}",
            }
        )
    forbidden_snippets = ("企业协作补充事实", "收到，我先按这个口径记录")
    template_like = [
        row
        for row in collected_messages
        if any(snippet in str(row.get("message_text") or "") for snippet in forbidden_snippets)
    ]
    checks.append(
        {
            "check_id": "template_like_message_ratio",
            "passed": not template_like,
            "details": f"template-like messages: {len(template_like)}",
        }
    )
    if official_file_plan is not None:
        official_refs = {str(row.get("official_file_ref") or "") for row in collected_messages}
        private_refs = {str(row.get("private_info_ref") or "") for row in collected_messages}
        boundary_rows = [row for row in collected_messages if str(row.get("task_relevance_boundary") or "").strip()]
        family_id = str(official_file_plan.get("family_id") or "")
        if family_id == "private_info_in_official_file":
            checks.append(
                {
                    "check_id": "official_file_references_landed",
                    "passed": any(ref for ref in official_refs),
                    "details": f"official file refs in observed messages: {sorted(ref for ref in official_refs if ref)}",
                }
            )
            checks.append(
                {
                    "check_id": "private_info_boundary_landed",
                    "passed": any(ref for ref in private_refs) and bool(boundary_rows),
                    "details": (
                        f"private refs: {sorted(ref for ref in private_refs if ref)}, "
                        f"boundary rows: {len(boundary_rows)}"
                    ),
                }
            )
    payload = {
        "case_id": case_id,
        "is_valid": all(bool(check["passed"]) for check in checks),
        "checks": checks,
    }
    return validate_pre_annotation_report(payload)
