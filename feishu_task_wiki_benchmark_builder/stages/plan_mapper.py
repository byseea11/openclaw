from __future__ import annotations

from typing import Any

from ..schemas import validate_command_plan, validate_execution_plan


def build_execution_plan_from_command_plan(command_plan: list[dict[str, Any]]) -> dict[str, Any]:
    rows = validate_command_plan(command_plan)
    actions: list[dict[str, Any]] = []
    for row in rows:
        action = {
            "action_id": row["step_id"],
            "action_type": row["action_type"],
            "depends_on": row["depends_on_step_ids"],
            "params": row["params"],
        }
        if row.get("output_ref"):
            action["output_ref"] = row["output_ref"]
        actions.append(action)
    return validate_execution_plan(
        {
            "case_id": rows[0]["case_id"],
            "operator_identity": "user",
            "delivery_mode": "prefixed_single_operator",
            "actions": actions,
        }
    )
