from __future__ import annotations

from typing import Any

from .schemas import validate_case_world_v3, validate_characters, validate_task_actor_layout


NAME_LIBRARY = ["Alice", "Bob", "Carol", "xzy", "Mina", "Nina", "Owen", "Piper", "Quinn", "Rita", "Soren", "Tina"]
CHINESE_NAME_LIBRARY = ["林晨", "周宇", "陈雪", "王源", "高骏", "赵敏", "何然", "秦怡", "罗天", "苏禾", "唐越", "许薇"]


def _pick_name(index: int) -> str:
    if index < len(CHINESE_NAME_LIBRARY):
        return CHINESE_NAME_LIBRARY[index]
    return NAME_LIBRARY[index % len(NAME_LIBRARY)]


def generate_characters(task_actor_layout: dict[str, Any], case_world: dict[str, Any]) -> dict[str, Any]:
    layout = validate_task_actor_layout(task_actor_layout)
    world = validate_case_world_v3(case_world)
    characters = []
    for index, actor_slot in enumerate(layout["shared_actor_slots"]):
        person_id = actor_slot["actor_slot_id"]
        characters.append(
            {
                "person_id": person_id,
                "actor_slot_id": actor_slot["actor_slot_id"],
                "simulated_open_id": f"ou_sim_{person_id}",
                "name": _pick_name(index),
                "department": actor_slot["department"],
                "role": actor_slot["role_label"],
                "task_ids": actor_slot["task_ids"],
                "default_channels": [session["chat_ref"] for session in world["source_sessions"][:2]],
                "profile": f"{actor_slot['role_label']}，会在多个任务和多个 source 中提供不同粒度的信息，适合制造任务记忆边界测试。",
            }
        )
    return validate_characters({"case_id": layout["case_id"], "characters": characters})


def generate_characters_with_mode(
    task_actor_layout: dict[str, Any],
    case_world: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> tuple[dict[str, Any], str]:
    del llm_client
    return generate_characters(task_actor_layout, case_world), "fallback"
