from __future__ import annotations

from typing import Any

from .schemas import validate_build_report


def build_case_report(
    *,
    case_id: str,
    operator_identity: str,
    delivery_mode: str,
    preflight: dict[str, Any],
    fetch_identity: str,
    characters: dict[str, Any],
    timeline: dict[str, Any],
    execution_plan: dict[str, Any],
    execution_result: dict[str, Any],
    fetch_records: list[dict[str, Any]],
    ingress_events: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    report = {
        "case_id": case_id,
        "status": execution_result.get("status") or "unknown",
        "operator_identity": operator_identity,
        "delivery_mode": delivery_mode,
        "preflight": preflight,
        "fetch_identity": fetch_identity,
        "num_characters": len(characters.get("characters", [])),
        "num_timeline_events": len(timeline.get("timeline", [])),
        "num_planned_actions": len(execution_plan.get("actions", [])),
        "num_executed_actions": len(execution_result.get("action_status", [])),
        "num_lark_messages_collected": sum(
            len(((record.get("response") or {}).get("data") or {}).get("messages") or []) for record in fetch_records
        ),
        "num_openclaw_ingress_events": len(ingress_events),
        "warnings": list(warnings or []),
    }
    return validate_build_report(report)
