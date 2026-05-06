from __future__ import annotations

from typing import Any

from .schemas import (
    validate_coverage_spec,
    validate_memory_failure_blueprint,
    validate_state_trajectory,
)


def generate_coverage_spec(memory_failure_blueprint: dict[str, Any], state_trajectory: dict[str, Any]) -> dict[str, Any]:
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    trajectory = validate_state_trajectory(state_trajectory)
    required_roles: list[str] = []
    required_state_fields: list[str] = []
    required_query_types: list[str] = ["system-correctness", "baseline-break"]
    required_traps = []
    for trap in blueprint["traps"]:
        landing = trap["common"]["landing_requirements"]
        for role in landing["required_benchmark_roles"]:
            if role not in required_roles:
                required_roles.append(role)
        for field in landing["required_state_fields"]:
            if field not in required_state_fields:
                required_state_fields.append(field)
        required_traps.append(
            {
                "trap_id": trap["trap_id"],
                "failure_mode": trap["failure_mode"],
                "landing_requirements": landing,
            }
        )
    for transition in trajectory["transitions"]:
        if transition["state_field"] not in required_state_fields:
            required_state_fields.append(transition["state_field"])
    return validate_coverage_spec(
        {
            "case_id": blueprint["case_id"],
            "required_failure_modes": blueprint["selected_failure_modes"],
            "required_benchmark_roles": required_roles,
            "required_query_types": required_query_types,
            "required_state_fields": required_state_fields,
            "trap_coverage": {"required_traps": required_traps},
            "hard_gates": {
                "min_traps": len(blueprint["traps"]),
                "min_required_roles": len(required_roles),
                "require_cross_source_revision": True,
            },
        }
    )
