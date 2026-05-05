from __future__ import annotations

from typing import Any

from .case_profiles import build_session_layouts, sample_topic_templates
from .llm_client import JsonLLMClient
from .schemas import (
    ValidationError,
    validate_case_seed,
    validate_case_world,
    validate_characters,
    validate_conversation_plan,
)


def _first_actor(roster: list[dict[str, Any]], department: str) -> str:
    for character in roster:
        if character["department"] == department:
            return character["person_id"]
    return roster[0]["person_id"]


def _render_template(template: str, context: dict[str, Any]) -> str:
    return str(template).format(**context)


def _topic_context(case_seed: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    departments = list(case_seed["departments"])
    return {
        "task_id": case_seed["task_id"],
        "title": case_seed["title"],
        "main_goal": case_seed["main_goal"],
        "target_window": "五月上旬",
        "next_window": "5 月 10 日",
        "focus_department": departments[0] if departments else "产品",
        "secondary_department": departments[1] if len(departments) > 1 else (departments[0] if departments else "研发"),
        "topic_title": topic["topic_title"],
    }


def _build_turns(
    *,
    case_seed: dict[str, Any],
    roster: list[dict[str, Any]],
    selected_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    per_topic_turns: list[list[dict[str, Any]]] = []
    topic_turn_ids: dict[str, list[str]] = {}
    for topic in selected_topics:
        turns_for_topic: list[dict[str, Any]] = []
        context = _topic_context(case_seed, topic)
        for index, template in enumerate(topic.get("turn_templates", []), start=1):
            turn_id = f"turn_{topic['topic_key']}_{index:02d}"
            topic_turn_ids.setdefault(topic["topic_key"], []).append(turn_id)
            turns_for_topic.append(
                {
                    "turn_id": turn_id,
                    "session_id": template["session_id"],
                    "speaker_ref": _first_actor(roster, template["speaker_department"]),
                    "topic_key": topic["topic_key"],
                    "turn_purpose": template["turn_purpose"],
                    "supports_event_types": template["supports_event_types"],
                    "references_previous_turns": topic_turn_ids[topic["topic_key"]][:-1][-1:] if len(topic_turn_ids[topic["topic_key"]]) > 1 else [],
                    "state_transition": template["state_transition"],
                    "semantic_payload": _render_template(template["semantic_payload_template"], context),
                }
            )
        per_topic_turns.append(turns_for_topic)
    merged: list[dict[str, Any]] = []
    max_turn_count = max((len(item) for item in per_topic_turns), default=0)
    for round_index in range(max_turn_count):
        for topic_turns in per_topic_turns:
            if round_index < len(topic_turns):
                merged.append(topic_turns[round_index])
    for index, turn in enumerate(merged, start=1):
        turn["sequence_no"] = index
    return merged


def _build_sessions(
    *,
    case_seed: dict[str, Any],
    selected_topics: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    layouts = build_session_layouts(task_id=case_seed["task_id"], profile_id=case_seed.get("scenario_profile"))
    first_turn_by_topic: dict[str, str] = {}
    for turn in turns:
        first_turn_by_topic.setdefault(turn["topic_key"], turn["turn_id"])
    session_topic_keys: dict[str, list[str]] = {}
    session_counts: dict[str, int] = {}
    for turn in turns:
        session_topic_keys.setdefault(turn["session_id"], [])
        if turn["topic_key"] not in session_topic_keys[turn["session_id"]]:
            session_topic_keys[turn["session_id"]].append(turn["topic_key"])
        session_counts[turn["session_id"]] = session_counts.get(turn["session_id"], 0) + 1
    normalized_sessions: list[dict[str, Any]] = []
    for layout in layouts:
        root_topic_key = str(layout.get("root_topic_key") or "").strip()
        normalized_sessions.append(
            {
                "session_id": layout["session_id"],
                "source_type": layout["source_type"],
                "source_ref": layout["source_ref"],
                "chat_ref": layout["chat_ref"],
                "title": layout["title"],
                "topic_keys": session_topic_keys.get(
                    layout["session_id"],
                    [item["topic_key"] for item in selected_topics],
                ),
                "planned_turn_count": session_counts.get(layout["session_id"], 0),
                "root_turn_id": first_turn_by_topic.get(root_topic_key) if root_topic_key else None,
            }
        )
    return normalized_sessions


def _fallback_conversation_plan(
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
) -> dict[str, Any]:
    seed = validate_case_seed(case_seed)
    world = validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    roster = validated_characters["characters"]
    selected_topics = sample_topic_templates(
        seed=int(seed["seed"]),
        difficulty=seed["difficulty"],
        profile_id=seed.get("scenario_profile"),
    )
    turns = _build_turns(case_seed=seed, roster=roster, selected_topics=selected_topics)
    sessions = _build_sessions(case_seed=seed, selected_topics=selected_topics, turns=turns)
    return {
        "case_id": seed["case_id"],
        "task_id": world["task_id"],
        "topic_registry": [
            {
                "topic_key": item["topic_key"],
                "topic_title": item["topic_title"],
                "desired_event_types": item["desired_event_types"],
                "state_transitions": item["state_transitions"],
            }
            for item in selected_topics
        ],
        "sessions": sessions,
        "turns": turns,
    }


def generate_conversation_plan_with_mode(
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    seed = validate_case_seed(case_seed)
    world = validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    roster_ids = {item["person_id"] for item in validated_characters["characters"]}
    if llm_client is None:
        return validate_conversation_plan(
            _fallback_conversation_plan(seed, world, validated_characters),
            allowed_actor_refs=roster_ids,
        ), "fallback"
    system_prompt = (
        "Generate one enterprise IM conversation plan as JSON. "
        "Return only a JSON object with keys: case_id, task_id, topic_registry, sessions, turns. "
        "There must be at least 3 sessions, at least 18 turns, and at least 3 topics. "
        "Use source_type values from chat, thread. "
        "All natural-language strings must be written in Simplified Chinese."
    )
    user_prompt = (
        f"Case seed:\n{seed}\nCase world:\n{world}\nCharacters:\n{validated_characters}\n"
        "请基于已有 topic/session 结构生成一个多轮、多 source 的飞书协作计划。必须至少覆盖一个日期 supersession、"
        "一个 thread 内 blocker 讨论、一个跨 source 的口径修正。"
        "turns must reference valid speaker_ref and topic_key values."
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_conversation_plan(payload, allowed_actor_refs=roster_ids), "live"
    except (Exception, ValidationError):
        return validate_conversation_plan(
            _fallback_conversation_plan(seed, world, validated_characters),
            allowed_actor_refs=roster_ids,
        ), "fallback"


def generate_conversation_plan(
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    plan, _mode = generate_conversation_plan_with_mode(
        case_seed,
        case_world,
        characters,
        llm_client=llm_client,
    )
    return plan
