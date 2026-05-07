from __future__ import annotations

from typing import Any

from ..schemas import validate_task_actor_layout_artifact


def build_task_actor_layout_artifact(
    *,
    case_context: dict[str, Any],
    story_plan: dict[str, Any],
) -> dict[str, Any]:
    return validate_task_actor_layout_artifact(
        {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "task_id": case_context["task_id"],
            "actors": story_plan["actors"],
            "task_actor_layout": story_plan["task_actor_layout"],
        }
    )
