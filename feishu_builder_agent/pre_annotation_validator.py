from __future__ import annotations

from typing import Any

from .schemas import (
    validate_case_spec,
    validate_collected_messages_v3,
    validate_conversation_plan_v3,
    validate_coverage_spec,
    validate_memory_failure_blueprint,
    validate_pre_annotation_validation_report,
)


def build_pre_annotation_validation_report(
    *,
    case_spec: dict[str, Any],
    memory_failure_blueprint: dict[str, Any],
    coverage_spec: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    spec = validate_case_spec(case_spec)
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    coverage = validate_coverage_spec(coverage_spec)
    plan = validate_conversation_plan_v3(conversation_plan)
    messages = validate_collected_messages_v3(collected_messages)
    del plan

    observed_failure_modes = sorted({row["memory_failure_mode"] for row in messages if row["memory_failure_mode"]})
    trap_reports = []
    for trap in blueprint["traps"]:
        landing = trap["common"]["landing_requirements"]
        trap_messages = [row for row in messages if row["memory_trap"] == trap["trap_id"]]
        observed_roles = sorted({row["benchmark_role"] for row in trap_messages if row["benchmark_role"]})
        required_roles = list(landing["required_benchmark_roles"])
        missing_roles = [role for role in required_roles if role not in observed_roles]
        observed_state_fields = sorted({field for row in trap_messages for field in row["state_field_hints"]})
        required_state_fields = list(landing["required_state_fields"])
        missing_state_fields = [field for field in required_state_fields if field not in observed_state_fields]
        evidence_messages_count = len(trap_messages)
        probe_query_ready = len(trap["common"]["probe_queries"]) >= int(landing["required_probe_queries_min"])
        landed = (
            not missing_roles
            and not missing_state_fields
            and evidence_messages_count >= int(landing["required_evidence_messages_min"])
            and probe_query_ready
        )
        notes = []
        if missing_roles:
            notes.append(f"missing roles: {', '.join(missing_roles)}")
        if missing_state_fields:
            notes.append(f"missing state fields: {', '.join(missing_state_fields)}")
        if evidence_messages_count < int(landing["required_evidence_messages_min"]):
            notes.append("insufficient evidence messages")
        if trap["failure_mode"] not in observed_failure_modes:
            notes.append("failure mode not materialized in collected_messages")
        trap_reports.append(
            {
                "trap_id": trap["trap_id"],
                "failure_mode": trap["failure_mode"],
                "landed": landed,
                "matched_roles": observed_roles,
                "missing_roles": missing_roles,
                "evidence_messages_count": evidence_messages_count,
                "required_state_fields": required_state_fields,
                "observed_state_fields": observed_state_fields,
                "missing_state_fields": missing_state_fields,
                "probe_query_ready": probe_query_ready,
                "notes": notes,
            }
        )
    missing_failure_modes = [mode for mode in coverage["required_failure_modes"] if mode not in observed_failure_modes]
    report = {
        "case_id": spec["case_id"],
        "status": "pass" if not missing_failure_modes and all(item["landed"] for item in trap_reports) else "fail",
        "required_failure_modes_observed": observed_failure_modes,
        "missing_failure_modes": missing_failure_modes,
        "traps": trap_reports,
    }
    return validate_pre_annotation_validation_report(report)
