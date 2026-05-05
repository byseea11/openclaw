from __future__ import annotations

from typing import Any

from .llm_client import JsonLLMClient
from .prompt_templates import build_story_prompts
from .schemas import ValidationError, validate_case_world, validate_characters, validate_story


def _fallback_story(case_world: dict[str, Any], characters: dict[str, Any]) -> dict[str, Any]:
    world = validate_case_world(case_world)
    roster = validate_characters(characters)["characters"]
    departments = "、".join(character["department"] for character in roster[:4])
    title = world["title"]
    return {
        "case_id": world["case_id"],
        "task_id": world["task_id"],
        "title": title,
        "background": f"{title} 发生在 {world['company_type']} 的协作场景中，{departments} 等部门正在围绕同一目标持续对齐结论。",
        "business_pressure": world["external_pressure"],
        "project_goal": world["main_goal"],
        "initial_assumption": "团队最初倾向于先给出一个偏乐观的内部推进窗口，再通过多轮协作确认真实可行性。",
        "main_conflicts": list(world["conflict_axes"]),
        "in_scope": [title, "跨部门决策口径对齐", "飞书群聊与 thread 协作过程"],
        "out_of_scope": ["无关的平台迁移工作", "长尾定制化需求"],
    }


def generate_story_with_mode(
    case_world: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    world = validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    if llm_client is None:
        return validate_story(_fallback_story(world, validated_characters)), "fallback"
    system_prompt, user_prompt = build_story_prompts(
        world=world,
        validated_characters=validated_characters,
    )
    try:
        story = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        merged = {
            **story,
            "case_id": world["case_id"],
            "task_id": world["task_id"],
            "title": world["title"],
        }
        return validate_story(merged), "live"
    except (Exception, ValidationError):
        return validate_story(_fallback_story(world, validated_characters)), "fallback"


def generate_story(
    case_world: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    story, _mode = generate_story_with_mode(case_world, characters, llm_client=llm_client)
    return story
