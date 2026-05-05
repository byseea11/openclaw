from __future__ import annotations

import random
from typing import Any

from .case_profiles import resolve_case_profile, resolve_character_role_templates
from .llm_client import JsonLLMClient
from .schemas import ValidationError, validate_case_seed, validate_case_spec, validate_case_world, validate_characters, validate_story

NAME_LIBRARY = [
    "林晨",
    "周宇",
    "陈雪",
    "王源",
    "高骏",
    "赵敏",
    "何然",
    "秦怡",
    "罗天",
    "苏禾",
    "唐越",
    "许薇",
    "顾宁",
    "韩朔",
]


def _to_person_id(role_key: str, index: int) -> str:
    return f"{role_key}_{index + 1:02d}"


def _to_simulated_open_id(person_id: str) -> str:
    return f"ou_sim_{person_id}"
def _fallback_characters(spec: dict[str, Any], case_seed: dict[str, Any], case_world: dict[str, Any]) -> dict[str, Any]:
    spec = validate_case_spec(spec)
    seed = validate_case_seed(case_seed)
    validate_case_world(case_world)
    rng = random.Random(seed["seed"])
    names = NAME_LIBRARY[:]
    rng.shuffle(names)
    selected_departments = list(seed["departments"])
    template_map = resolve_character_role_templates(
        profile_id=seed.get("scenario_profile"),
        departments=selected_departments,
    )
    role_pool: list[tuple[str, dict[str, Any]]] = []
    for department in selected_departments:
        role_pool.extend((department, item) for item in template_map.get(department, []))
    if len(role_pool) < 8:
        all_departments = list((resolve_case_profile(seed.get("scenario_profile")).get("department_pool") or []))
        extra_template_map = resolve_character_role_templates(
            profile_id=seed.get("scenario_profile"),
            departments=all_departments,
        )
        for department, templates in extra_template_map.items():
            for item in templates:
                if (department, item) not in role_pool:
                    role_pool.append((department, item))
            if len(role_pool) >= 8:
                break
    characters = []
    for index, role_info in enumerate(role_pool[: max(8, min(12, len(role_pool)))]):
        department, template = role_info
        role_key = template["role_key"]
        name = names[index]
        person_id = _to_person_id(role_key, index)
        characters.append(
            {
                "person_id": person_id,
                "simulated_open_id": _to_simulated_open_id(person_id),
                "name": name,
                "department": department,
                "role": template["role"],
                "responsibility": template["responsibility"],
                "communication_style": template["communication_style"],
                "conflict_bias": template["conflict_bias"],
                "stance": template["stance"],
                "risk_preference": template["risk_preference"],
                "information_access_level": template["information_access_level"],
                "default_channels": template["default_channels"],
            }
        )
    return {"case_id": spec["case_id"], "characters": characters}


def generate_characters(
    case_spec: dict[str, Any],
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    story: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    characters, _mode = generate_characters_with_mode(case_spec, case_seed, case_world, story, llm_client=llm_client)
    return characters


def generate_characters_with_mode(
    case_spec: dict[str, Any],
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    story: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    spec = validate_case_spec(case_spec)
    seed = validate_case_seed(case_seed)
    world = validate_case_world(case_world)
    validated_story = validate_story(story)
    if llm_client is None:
        return validate_characters(_fallback_characters(spec, seed, world)), "fallback"
    system_prompt = (
        "Generate a concise role roster for one enterprise software delivery case. "
        "Return only JSON with keys: case_id, characters. characters must be an array of 8 to 12 objects. "
        "Each object must contain person_id, simulated_open_id, name, department, role, responsibility, communication_style, conflict_bias, "
        "stance, risk_preference, information_access_level, default_channels. "
        "All natural-language strings must be written in Simplified Chinese. "
        "Only person_id and simulated_open_id may remain snake_case."
    )
    user_prompt = (
        f"Case spec:\n{spec}\nCase seed:\n{seed}\nCase world:\n{world}\nStory:\n{validated_story}\n"
        "请生成 8 到 12 个角色，优先覆盖 case_seed.departments 中已经选中的部门。所有自然语言字段必须使用简体中文，字段尽量简短。"
        "person_id must be stable snake_case strings. simulated_open_id must look like a synthetic Feishu open_id such as "
        "'ou_sim_security_01'. default_channels should be string arrays such as "
        "['main_chat', 'launch_window_thread', 'customer_sync_chat']."
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_characters(payload), "live"
    except (Exception, ValidationError):
        return validate_characters(_fallback_characters(spec, seed, world)), "fallback"
