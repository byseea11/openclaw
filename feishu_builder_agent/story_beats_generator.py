from __future__ import annotations

from typing import Any

from .schemas import (
    validate_case_world_v3,
    validate_memory_failure_blueprint,
    validate_story_beats,
)


def generate_story_beats(memory_failure_blueprint: dict[str, Any], case_world: dict[str, Any]) -> dict[str, Any]:
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    world = validate_case_world_v3(case_world)
    beats = []
    for index, trap in enumerate(blueprint["traps"], start=1):
        roles = trap["common"]["landing_requirements"]["required_benchmark_roles"]
        for role_index, role in enumerate(roles, start=1):
            beat_type = "trap_beat"
            if "supersession" in role or "current_state" in role:
                beat_type = "revision_beat"
            elif "distractor" in role or "pollution" in role:
                beat_type = "distractor_beat"
            beats.append(
                {
                    "beat_id": f"beat_{index:02d}_{role_index:02d}",
                    "trap_id": trap["trap_id"],
                    "failure_mode": trap["failure_mode"],
                    "beat_type": beat_type,
                    "benchmark_role": role,
                    "description": f"围绕 {trap['trap_mechanism']} 安排一个 {role}，让 baseline 在该点暴露失败。",
                    "target_session_id": world["source_sessions"][min(role_index - 1, len(world['source_sessions']) - 1)]["session_id"],
                }
            )
    return validate_story_beats({"case_id": blueprint["case_id"], "beats": beats})
