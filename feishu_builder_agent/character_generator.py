from __future__ import annotations

from typing import Any

from .llm_client import live_llm_required
from .logging_utils import builder_log
from .prompt_registry import build_character_prompts
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
    layout = validate_task_actor_layout(task_actor_layout)
    world = validate_case_world_v3(case_world)
    scaffold = generate_characters(layout, world)
    if llm_client is None and live_llm_required():
        raise RuntimeError("characters requires live LLM but no active llm_client is available")
    if llm_client is not None:
        system_prompt, user_prompt = build_character_prompts(layout, world, scaffold)
        try:
            payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            characters = list(payload.get("characters") or [])
            if len(characters) != len(scaffold["characters"]):
                raise ValueError("character count does not match scaffold")
            merged_rows = []
            scaffold_map = {item["person_id"]: item for item in scaffold["characters"]}
            for item in characters:
                person_id = str(item.get("person_id") or "").strip()
                if person_id not in scaffold_map:
                    raise ValueError(f"unknown person_id from llm: {person_id}")
                scaffold_row = scaffold_map[person_id]
                merged = dict(scaffold_row)
                merged.update(item)
                merged["simulated_open_id"] = scaffold_row["simulated_open_id"]
                merged["actor_slot_id"] = scaffold_row["actor_slot_id"]
                merged["department"] = scaffold_row["department"]
                merged["role"] = scaffold_row["role"]
                merged["task_ids"] = scaffold_row["task_ids"]
                merged["default_channels"] = scaffold_row["default_channels"]
                merged_rows.append(merged)
            result = validate_characters({"case_id": scaffold["case_id"], "characters": merged_rows})
            builder_log("characters", f"使用 live LLM 生成人物 case_id={world['case_id']}")
            return result, "llm"
        except Exception as exc:
            if live_llm_required():
                raise RuntimeError(f"characters requires live LLM but failed: {exc}") from exc
            builder_log("characters", f"live LLM characters 生成失败，回退 fallback。reason={exc}")
    return scaffold, "fallback"
