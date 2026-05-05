from __future__ import annotations

from typing import Any

from .llm_client import JsonLLMClient
from .prompt_templates import build_timeline_prompts
from .schemas import ValidationError, validate_case_world, validate_characters, validate_story, validate_timeline


def _first_actor(characters: list[dict[str, str]], department: str) -> str:
    for character in characters:
        if character["department"] == department:
            return character["person_id"]
    return characters[0]["person_id"]


def _fallback_timeline(case_world: dict[str, Any], validated_story: dict[str, Any], roster: list[dict[str, str]]) -> dict[str, Any]:
    world = validate_case_world(case_world)
    task_id = world["task_id"]
    title = validated_story["title"]
    return {
        "case_id": world["case_id"],
        "timeline": [
            {
                "timeline_id": "tl_001",
                "time_order": 1,
                "event_type": "initial_request",
                "description": f"主群里首次明确提到 {task_id} 的客户压力，大家开始围绕发布时间和对外口径讨论。",
                "actor_refs": [_first_actor(roster, "客户成功")],
                "affected_topic": title,
                "state_effect": "形成了尽快给出时间预期的压力。",
                "should_surface_in_message": True,
            },
            {
                "timeline_id": "tl_002",
                "time_order": 2,
                "event_type": "initial_target",
                "description": "产品先提出一个内部目标日期，但强调这还不能作为对外承诺。",
                "actor_refs": [_first_actor(roster, "产品")],
                "affected_topic": "发布时间目标",
                "state_effect": "建立了一个偏乐观的内部目标。",
                "should_surface_in_message": True,
            },
            {
                "timeline_id": "tl_003",
                "time_order": 3,
                "event_type": "engineering_blocker",
                "description": "研发发现关键依赖尚未稳定，原先乐观目标出现明显不确定性。",
                "actor_refs": [_first_actor(roster, "研发")],
                "affected_topic": "依赖准备情况",
                "state_effect": "引入了实质性 blocker。",
                "should_surface_in_message": True,
            },
            {
                "timeline_id": "tl_004",
                "time_order": 4,
                "event_type": "security_constraint",
                "description": "安全侧补充评审约束，认为高风险能力在评审完成前不能写进对外口径。",
                "actor_refs": [_first_actor(roster, "安全")],
                "affected_topic": "风险处理",
                "state_effect": "增加了一个合规门槛。",
                "should_surface_in_message": True,
            },
            {
                "timeline_id": "tl_005",
                "time_order": 5,
                "event_type": "ops_risk",
                "description": "运维说明上线窗口还没有最终锁定，回滚预案准备也不完整。",
                "actor_refs": [_first_actor(roster, "运维")],
                "affected_topic": "发布日期",
                "state_effect": "削弱了大家对原目标日期的信心。",
                "should_surface_in_message": True,
            },
            {
                "timeline_id": "tl_006",
                "time_order": 6,
                "event_type": "external_messaging_fix",
                "description": "产品修正对外表述，要求目标日期不能再被当成已确认时间对外同步。",
                "actor_refs": [_first_actor(roster, "产品")],
                "affected_topic": "对外沟通口径",
                "state_effect": "修订了面对外部的表述方式。",
                "should_surface_in_message": True,
            },
        ],
    }


def generate_timeline(
    case_world: dict[str, Any],
    story: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    timeline, _mode = generate_timeline_with_mode(case_world, story, characters, llm_client=llm_client)
    return timeline


def generate_timeline_with_mode(
    case_world: dict[str, Any],
    story: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    world = validate_case_world(case_world)
    validated_story = validate_story(story)
    validated_characters = validate_characters(characters)
    roster = validated_characters["characters"]
    if llm_client is None:
        return validate_timeline(_fallback_timeline(world, validated_story, roster), allowed_actor_refs={item["person_id"] for item in roster}), "fallback"
    system_prompt, user_prompt = build_timeline_prompts(
        world=world,
        validated_story=validated_story,
        validated_characters=validated_characters,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_timeline(payload, allowed_actor_refs={item["person_id"] for item in roster}), "live"
    except (Exception, ValidationError):
        return validate_timeline(_fallback_timeline(world, validated_story, roster), allowed_actor_refs={item["person_id"] for item in roster}), "fallback"
