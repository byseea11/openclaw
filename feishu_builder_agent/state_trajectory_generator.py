from __future__ import annotations

from typing import Any

from .schemas import (
    validate_case_world_v3,
    validate_characters,
    validate_memory_failure_blueprint,
    validate_state_trajectory,
    validate_task_actor_layout,
)


def generate_state_trajectory(
    memory_failure_blueprint: dict[str, Any],
    task_actor_layout: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
) -> dict[str, Any]:
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    validate_task_actor_layout(task_actor_layout)
    world = validate_case_world_v3(case_world)
    roster = validate_characters(characters)
    owner_names = [item["name"] for item in roster["characters"][:3]] or ["Bob", "Alice", "xzy"]
    transitions: list[dict[str, Any]] = []
    for index, trap in enumerate(blueprint["traps"], start=1):
        failure_mode = trap["failure_mode"]
        if failure_mode == "static_memory_stale_state":
            final_name = owner_names[2] if len(owner_names) >= 3 else "xzy"
            states = owner_names[:2] + [final_name]
            previous_transition_id = ""
            for state_index, owner_name in enumerate(states, start=1):
                transition_id = f"transition_owner_{index:02d}_{state_index:02d}"
                transitions.append(
                    {
                        "transition_id": transition_id,
                        "trap_id": trap["trap_id"],
                        "failure_mode": failure_mode,
                        "state_field": "owner",
                        "from_value": "" if state_index == 1 else states[state_index - 2],
                        "to_value": owner_name,
                        "creates_stale_state": "" if state_index == 1 else states[state_index - 2],
                        "supersedes_transition_id": previous_transition_id,
                        "is_final_current_state": state_index == len(states),
                        "source_session_ref": world["source_sessions"][min(state_index - 1, len(world["source_sessions"]) - 1)]["source_ref"],
                        "evidence_requirement": f"需要明确记录 owner 从 {states[state_index - 2] if state_index > 1 else '未指定'} 变为 {owner_name} 的证据。",
                    }
                )
                previous_transition_id = transition_id
        elif failure_mode == "dependency_propagation_failure":
            transitions.append(
                {
                    "transition_id": f"transition_dependency_{index:02d}_01",
                    "trap_id": trap["trap_id"],
                    "failure_mode": failure_mode,
                    "state_field": "dependency_status",
                    "from_value": "ready",
                    "to_value": "blocked_by_upstream",
                    "creates_stale_state": "ready",
                    "supersedes_transition_id": "",
                    "is_final_current_state": True,
                    "source_session_ref": world["source_sessions"][-1]["source_ref"],
                    "evidence_requirement": "需要明确记录上游依赖变化如何反转目标任务当前状态。",
                }
            )
        else:
            state_field = "blocker" if failure_mode == "unverifiable_summary_claim" else "owner"
            transitions.append(
                {
                    "transition_id": f"transition_{failure_mode}_{index:02d}_01",
                    "trap_id": trap["trap_id"],
                    "failure_mode": failure_mode,
                    "state_field": state_field,
                    "from_value": "",
                    "to_value": "待确认",
                    "creates_stale_state": "",
                    "supersedes_transition_id": "",
                    "is_final_current_state": True,
                    "source_session_ref": world["source_sessions"][0]["source_ref"],
                    "evidence_requirement": "需要至少一条强证据消息和一条修正消息，以验证任务状态不是静态摘要。",
                }
            )
    final_current_state = {
        "owner": owner_names[2] if len(owner_names) >= 3 else owner_names[-1],
        "release_window": "暂不锁死具体发布日期",
        "dependency_status": "部分上游依赖待确认",
    }
    return validate_state_trajectory(
        {
            "case_id": blueprint["case_id"],
            "task_id": blueprint["task_id"],
            "transitions": transitions,
            "final_current_state": final_current_state,
        }
    )
