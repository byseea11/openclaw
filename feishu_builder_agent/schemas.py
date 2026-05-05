from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .builder_settings import load_builder_settings, resolve_difficulty_settings


class ValidationError(ValueError):
    """Raised when a builder artifact does not match the expected schema."""


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CASE_ID_RE = re.compile(r"^case_[a-z0-9_]+$")
_TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9A-Za-z]+$")


def _require_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} must be a non-empty string")
    return text


def _optional_string(value: Any) -> str:
    return str(value or "").strip()


def _optional_chinese_string(value: Any, field: str) -> str:
    text = _optional_string(value)
    if text and not _CJK_RE.search(text):
        raise ValidationError(f"{field} must contain Chinese text")
    return text


def _require_chinese_string(value: Any, field: str) -> str:
    text = _require_string(value, field)
    if not _CJK_RE.search(text):
        raise ValidationError(f"{field} must contain Chinese text")
    return text


def _default_simulated_open_id(person_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_]+", "_", person_id).strip("_").lower()
    return f"ou_sim_{safe_id}"


def _require_simulated_open_id(value: Any, person_id: str, field: str) -> str:
    open_id = _require_string(value, field)
    expected = _default_simulated_open_id(person_id)
    if open_id != expected:
        raise ValidationError(f"{field} must equal {expected}")
    return open_id


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    return value


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object")
    return value


def _require_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be an integer") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    return number


def _require_string_list(value: Any, field: str) -> list[str]:
    return [_require_string(item, f"{field}[]") for item in _require_list(value, field)]


def _validate_complexity_profile(value: Any, field: str) -> dict[str, int]:
    profile = _require_dict(value, field)
    defaults = {
        "session_count_target": 3,
        "source_session_count_target": 3,
        "message_count_target": 18,
        "topic_count_target": 3,
        "thread_reply_depth_target": 3,
        "state_transition_target": 4,
        "supersession_target": 1,
        "cross_source_revision_target": 1,
        "event_family_target": 5,
    }
    normalized: dict[str, int] = {}
    for key, default_value in defaults.items():
        normalized[key] = _require_int(profile.get(key, default_value), f"{field}.{key}", minimum=1)
    return normalized


def validate_case_spec(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_difficulties = set(load_builder_settings()["difficulty_profiles"].keys())
    departments = [
        _require_chinese_string(item, "department_hints[]")
        for item in _require_list(payload.get("department_hints") or [], "department_hints")
    ]
    case_id = _require_string(payload.get("case_id"), "case_id")
    if not _CASE_ID_RE.fullmatch(case_id):
        raise ValidationError("case_id must use lower_snake_case and start with case_")
    task_id = _require_string(payload.get("task_id"), "task_id")
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ValidationError("task_id must use UPPER-SLUG form like FEISHU-231")
    difficulty = str(payload.get("difficulty") or "medium").strip() or "medium"
    if difficulty not in allowed_difficulties:
        raise ValidationError(f"difficulty must be one of: {', '.join(sorted(allowed_difficulties))}")
    return {
        "case_id": case_id,
        "task_id": task_id,
        "title": _optional_chinese_string(payload.get("title"), "title"),
        "company_type": _optional_chinese_string(payload.get("company_type"), "company_type"),
        "department_hints": departments,
        "scenario_profile": _optional_string(payload.get("scenario_profile")) or "enterprise_release_coordination",
        "title_hint": _optional_chinese_string(payload.get("title_hint"), "title_hint"),
        "main_goal_hint": _optional_chinese_string(payload.get("main_goal_hint"), "main_goal_hint"),
        "main_goal": _optional_chinese_string(payload.get("main_goal"), "main_goal"),
        "difficulty": difficulty,
        "seed": int(payload.get("seed") or 0),
    }


def validate_case_seed(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_difficulties = set(load_builder_settings()["difficulty_profiles"].keys())
    department_hints = [
        _require_chinese_string(item, "case_seed.department_hints[]")
        for item in _require_list(payload.get("department_hints") or [], "case_seed.department_hints")
    ]
    difficulty = str(payload.get("difficulty") or "medium").strip() or "medium"
    if difficulty not in allowed_difficulties:
        raise ValidationError(f"case_seed.difficulty must be one of: {', '.join(sorted(allowed_difficulties))}")
    return {
        "case_id": _require_string(payload.get("case_id"), "case_seed.case_id"),
        "task_id": _require_string(payload.get("task_id"), "case_seed.task_id"),
        "domain": _require_string(payload.get("domain") or "enterprise_product_launch", "case_seed.domain"),
        "company_type_hint": _optional_chinese_string(payload.get("company_type_hint"), "case_seed.company_type_hint"),
        "department_hints": department_hints,
        "scenario_profile": _optional_string(payload.get("scenario_profile")) or "enterprise_release_coordination",
        "title_hint": _optional_chinese_string(payload.get("title_hint"), "case_seed.title_hint"),
        "main_goal_hint": _optional_chinese_string(payload.get("main_goal_hint"), "case_seed.main_goal_hint"),
        "difficulty": difficulty,
        "seed": int(payload.get("seed") or 0),
        "complexity_profile": _validate_complexity_profile(
            payload.get("complexity_profile")
            or {
                "session_count_target": 3,
                "source_session_count_target": 3,
                "message_count_target": 18,
                "topic_count_target": 3,
                "thread_reply_depth_target": 3,
                "state_transition_target": 4,
                "supersession_target": 1,
                "cross_source_revision_target": 1,
                "event_family_target": 5,
            },
            "case_seed.complexity_profile",
        ),
    }


def validate_case_world(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_difficulties = set(load_builder_settings()["difficulty_profiles"].keys())
    selected_topics = _require_list(payload.get("selected_topics"), "case_world.selected_topics")
    normalized_topics: list[dict[str, Any]] = []
    for topic in selected_topics:
        topic_obj = _require_dict(topic, "case_world.selected_topics[]")
        topic_key = _require_string(topic_obj.get("topic_key"), "case_world.selected_topics.topic_key")
        turn_templates = _require_list(topic_obj.get("turn_templates"), f"{topic_key}.turn_templates")
        normalized_topics.append(
            {
                "topic_key": topic_key,
                "topic_title": _require_chinese_string(topic_obj.get("topic_title"), f"{topic_key}.topic_title"),
                "desired_event_types": _require_string_list(topic_obj.get("desired_event_types"), f"{topic_key}.desired_event_types"),
                "state_transitions": [
                    _require_chinese_string(item, f"{topic_key}.state_transitions[]")
                    for item in _require_list(topic_obj.get("state_transitions"), f"{topic_key}.state_transitions")
                ],
                "turn_templates": [
                    {
                        "session_id": _require_string(turn.get("session_id"), f"{topic_key}.turn_templates[].session_id"),
                        "speaker_department": _require_chinese_string(
                            turn.get("speaker_department"),
                            f"{topic_key}.turn_templates[].speaker_department",
                        ),
                        "turn_purpose": _require_chinese_string(
                            turn.get("turn_purpose"),
                            f"{topic_key}.turn_templates[].turn_purpose",
                        ),
                        "supports_event_types": _require_string_list(
                            turn.get("supports_event_types"),
                            f"{topic_key}.turn_templates[].supports_event_types",
                        ),
                        "state_transition": _require_chinese_string(
                            turn.get("state_transition"),
                            f"{topic_key}.turn_templates[].state_transition",
                        ),
                        "semantic_payload_template": _require_chinese_string(
                            turn.get("semantic_payload_template"),
                            f"{topic_key}.turn_templates[].semantic_payload_template",
                        ),
                    }
                    for turn in turn_templates
                ],
            }
        )
    difficulty = str(payload.get("difficulty") or "medium").strip() or "medium"
    if difficulty not in allowed_difficulties:
        raise ValidationError(f"case_world.difficulty must be one of: {', '.join(sorted(allowed_difficulties))}")
    difficulty_settings = resolve_difficulty_settings(difficulty)
    departments = [
        _require_chinese_string(item, "case_world.departments[]")
        for item in _require_list(payload.get("departments"), "case_world.departments")
    ]
    if len(departments) < int(difficulty_settings["department_count"]):
        raise ValidationError(
            f"case_world.departments must contain at least {difficulty_settings['department_count']} items for difficulty={difficulty}"
        )
    if len(normalized_topics) < int(difficulty_settings["topic_count"]):
        raise ValidationError(
            f"case_world.selected_topics must contain at least {difficulty_settings['topic_count']} topics for difficulty={difficulty}"
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "case_world.case_id"),
        "task_id": _require_string(payload.get("task_id"), "case_world.task_id"),
        "scenario_profile": _optional_string(payload.get("scenario_profile")) or "enterprise_release_coordination",
        "difficulty": difficulty,
        "seed": _require_int(payload.get("seed"), "case_world.seed", minimum=0),
        "title": _require_chinese_string(payload.get("title"), "case_world.title"),
        "domain": _require_string(payload.get("domain"), "case_world.domain"),
        "company_type": _require_chinese_string(payload.get("company_type"), "case_world.company_type"),
        "departments": departments,
        "main_goal": _require_chinese_string(payload.get("main_goal"), "case_world.main_goal"),
        "organization_background": _require_chinese_string(payload.get("organization_background"), "case_world.organization_background"),
        "external_pressure": _require_chinese_string(payload.get("external_pressure"), "case_world.external_pressure"),
        "stakeholders": [_require_chinese_string(item, "case_world.stakeholders[]") for item in _require_list(payload.get("stakeholders"), "case_world.stakeholders")],
        "conflict_axes": [_require_chinese_string(item, "case_world.conflict_axes[]") for item in _require_list(payload.get("conflict_axes"), "case_world.conflict_axes")],
        "hidden_constraints": [_require_chinese_string(item, "case_world.hidden_constraints[]") for item in _require_list(payload.get("hidden_constraints"), "case_world.hidden_constraints")],
        "reversal_points": [_require_chinese_string(item, "case_world.reversal_points[]") for item in _require_list(payload.get("reversal_points"), "case_world.reversal_points")],
        "selected_topics": normalized_topics,
        "complexity_profile": _validate_complexity_profile(payload.get("complexity_profile"), "case_world.complexity_profile"),
    }


def validate_story(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": _require_string(payload.get("case_id"), "story.case_id"),
        "task_id": _require_string(payload.get("task_id"), "story.task_id"),
        "title": _require_chinese_string(payload.get("title"), "story.title"),
        "background": _require_chinese_string(payload.get("background"), "story.background"),
        "business_pressure": _require_chinese_string(payload.get("business_pressure"), "story.business_pressure"),
        "project_goal": _require_chinese_string(payload.get("project_goal"), "story.project_goal"),
        "initial_assumption": _require_chinese_string(payload.get("initial_assumption"), "story.initial_assumption"),
        "main_conflicts": [_require_chinese_string(item, "story.main_conflicts[]") for item in _require_list(payload.get("main_conflicts"), "story.main_conflicts")],
        "in_scope": [_require_chinese_string(item, "story.in_scope[]") for item in _require_list(payload.get("in_scope"), "story.in_scope")],
        "out_of_scope": [_require_chinese_string(item, "story.out_of_scope[]") for item in _require_list(payload.get("out_of_scope"), "story.out_of_scope")],
    }


def validate_characters(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "characters.case_id")
    characters = _require_list(payload.get("characters"), "characters.characters")
    settings = load_builder_settings()
    difficulty_profiles = settings["difficulty_profiles"]
    min_allowed = min(profile["character_count_min"] for profile in difficulty_profiles.values())
    max_allowed = max(profile["character_count_max"] for profile in difficulty_profiles.values())
    if not min_allowed <= len(characters) <= max_allowed:
        raise ValidationError(f"characters.characters must contain {min_allowed} to {max_allowed} roles")
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for character in characters:
        if not isinstance(character, dict):
            raise ValidationError("characters.characters[] must be an object")
        person_id = _require_string(character.get("person_id"), "characters.person_id")
        if person_id in seen_ids:
            raise ValidationError(f"duplicate person_id: {person_id}")
        seen_ids.add(person_id)
        normalized.append(
            {
                "person_id": person_id,
                "name": _require_chinese_string(character.get("name"), f"{person_id}.name"),
                "department": _require_chinese_string(character.get("department"), f"{person_id}.department"),
                "role": _require_chinese_string(character.get("role"), f"{person_id}.role"),
                "simulated_open_id": _require_simulated_open_id(
                    character.get("simulated_open_id") or _default_simulated_open_id(person_id),
                    person_id,
                    f"{person_id}.simulated_open_id",
                ),
                "responsibility": _require_chinese_string(character.get("responsibility"), f"{person_id}.responsibility"),
                "communication_style": _require_chinese_string(character.get("communication_style"), f"{person_id}.communication_style"),
                "conflict_bias": _require_chinese_string(character.get("conflict_bias"), f"{person_id}.conflict_bias"),
                "stance": _require_chinese_string(character.get("stance") or "倾向于在可控风险下推进目标。", f"{person_id}.stance"),
                "risk_preference": _require_chinese_string(character.get("risk_preference") or "中等风险偏好", f"{person_id}.risk_preference"),
                "information_access_level": _require_chinese_string(character.get("information_access_level") or "掌握部分上下游信息", f"{person_id}.information_access_level"),
                "default_channels": _require_string_list(character.get("default_channels") or ["main_chat"], f"{person_id}.default_channels"),
            }
        )
    return {"case_id": case_id, "characters": normalized}


def validate_actor_registry(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "actor_registry.case_id")
    actors = _require_list(payload.get("actors"), "actor_registry.actors")
    normalized: list[dict[str, Any]] = []
    seen_person_ids: set[str] = set()
    for actor in actors:
        actor_obj = _require_dict(actor, "actor_registry.actors[]")
        person_id = _require_string(actor_obj.get("person_id"), "actor_registry.person_id")
        if person_id in seen_person_ids:
            raise ValidationError(f"duplicate actor_registry.person_id: {person_id}")
        seen_person_ids.add(person_id)
        normalized.append(
            {
                "person_id": person_id,
                "simulated_open_id": _require_simulated_open_id(
                    actor_obj.get("simulated_open_id") or _default_simulated_open_id(person_id),
                    person_id,
                    f"{person_id}.simulated_open_id",
                ),
                "name": _require_chinese_string(actor_obj.get("name"), f"{person_id}.name"),
                "department": _require_chinese_string(actor_obj.get("department"), f"{person_id}.department"),
                "role": _require_chinese_string(actor_obj.get("role"), f"{person_id}.role"),
                "default_channels": _require_string_list(actor_obj.get("default_channels") or ["main_chat"], f"{person_id}.default_channels"),
            }
        )
    return {"case_id": case_id, "actors": normalized}


def validate_conversation_plan(payload: dict[str, Any], *, allowed_actor_refs: set[str] | None = None) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "conversation_plan.case_id")
    task_id = _require_string(payload.get("task_id"), "conversation_plan.task_id")
    topic_registry = _require_list(payload.get("topic_registry"), "conversation_plan.topic_registry")
    sessions = _require_list(payload.get("sessions"), "conversation_plan.sessions")
    turns = _require_list(payload.get("turns"), "conversation_plan.turns")
    if len(topic_registry) < 3:
        raise ValidationError("conversation_plan.topic_registry must contain at least 3 topics")
    if len(sessions) < 3:
        raise ValidationError("conversation_plan.sessions must contain at least 3 sessions")
    if len(turns) < 18:
        raise ValidationError("conversation_plan.turns must contain at least 18 turns")
    normalized_topics: list[dict[str, Any]] = []
    topic_keys: set[str] = set()
    for topic in topic_registry:
        topic_obj = _require_dict(topic, "conversation_plan.topic_registry[]")
        topic_key = _require_string(topic_obj.get("topic_key"), "conversation_plan.topic_key")
        if topic_key in topic_keys:
            raise ValidationError(f"duplicate conversation_plan.topic_key: {topic_key}")
        topic_keys.add(topic_key)
        normalized_topics.append(
            {
                "topic_key": topic_key,
                "topic_title": _require_chinese_string(topic_obj.get("topic_title"), f"{topic_key}.topic_title"),
                "desired_event_types": _require_string_list(topic_obj.get("desired_event_types"), f"{topic_key}.desired_event_types"),
                "state_transitions": [_require_chinese_string(item, f"{topic_key}.state_transitions[]") for item in _require_list(topic_obj.get("state_transitions"), f"{topic_key}.state_transitions")],
            }
        )
    normalized_sessions: list[dict[str, Any]] = []
    session_ids: set[str] = set()
    for session in sessions:
        session_obj = _require_dict(session, "conversation_plan.sessions[]")
        session_id = _require_string(session_obj.get("session_id"), "conversation_plan.session_id")
        if session_id in session_ids:
            raise ValidationError(f"duplicate conversation_plan.session_id: {session_id}")
        session_ids.add(session_id)
        source_type = _require_string(session_obj.get("source_type"), f"{session_id}.source_type")
        if source_type not in {"chat", "thread", "comment", "doc"}:
            raise ValidationError(f"{session_id}.source_type must be one of chat/thread/comment/doc")
        normalized_sessions.append(
            {
                "session_id": session_id,
                "source_type": source_type,
                "source_ref": _require_string(session_obj.get("source_ref"), f"{session_id}.source_ref"),
                "chat_ref": _require_string(session_obj.get("chat_ref"), f"{session_id}.chat_ref"),
                "title": _require_chinese_string(session_obj.get("title"), f"{session_id}.title"),
                "topic_keys": [_require_string(item, f"{session_id}.topic_keys[]") for item in _require_list(session_obj.get("topic_keys"), f"{session_id}.topic_keys")],
                "planned_turn_count": _require_int(session_obj.get("planned_turn_count"), f"{session_id}.planned_turn_count", minimum=1),
                "root_turn_id": str(session_obj.get("root_turn_id") or "").strip() or None,
            }
        )
    normalized_turns: list[dict[str, Any]] = []
    turn_ids: set[str] = set()
    for turn in turns:
        turn_obj = _require_dict(turn, "conversation_plan.turns[]")
        turn_id = _require_string(turn_obj.get("turn_id"), "conversation_plan.turn_id")
        if turn_id in turn_ids:
            raise ValidationError(f"duplicate conversation_plan.turn_id: {turn_id}")
        turn_ids.add(turn_id)
        speaker_ref = _require_string(turn_obj.get("speaker_ref"), f"{turn_id}.speaker_ref")
        if allowed_actor_refs is not None and speaker_ref not in allowed_actor_refs:
            raise ValidationError(f"{turn_id}.speaker_ref must exist in characters.json")
        session_id = _require_string(turn_obj.get("session_id"), f"{turn_id}.session_id")
        if session_id not in session_ids:
            raise ValidationError(f"{turn_id}.session_id must exist in conversation_plan.sessions")
        topic_key = _require_string(turn_obj.get("topic_key"), f"{turn_id}.topic_key")
        if topic_key not in topic_keys:
            raise ValidationError(f"{turn_id}.topic_key must exist in topic_registry")
        normalized_turns.append(
            {
                "turn_id": turn_id,
                "sequence_no": _require_int(turn_obj.get("sequence_no"), f"{turn_id}.sequence_no", minimum=1),
                "session_id": session_id,
                "speaker_ref": speaker_ref,
                "topic_key": topic_key,
                "turn_purpose": _require_chinese_string(turn_obj.get("turn_purpose"), f"{turn_id}.turn_purpose"),
                "supports_event_types": _require_string_list(turn_obj.get("supports_event_types"), f"{turn_id}.supports_event_types"),
                "references_previous_turns": [str(item).strip() for item in _require_list(turn_obj.get("references_previous_turns") or [], f"{turn_id}.references_previous_turns")],
                "state_transition": _require_chinese_string(turn_obj.get("state_transition"), f"{turn_id}.state_transition"),
                "semantic_payload": _require_chinese_string(turn_obj.get("semantic_payload"), f"{turn_id}.semantic_payload"),
            }
        )
    return {
        "case_id": case_id,
        "task_id": task_id,
        "topic_registry": normalized_topics,
        "sessions": normalized_sessions,
        "turns": sorted(normalized_turns, key=lambda item: (item["sequence_no"], item["turn_id"])),
    }


def validate_utterance_plan(rows: list[dict[str, Any]], *, allowed_actor_refs: set[str] | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    turn_ids: set[str] = set()
    for row in rows:
        row_obj = _require_dict(row, "utterance_plan[]")
        turn_id = _require_string(row_obj.get("turn_id"), "utterance_plan.turn_id")
        if turn_id in turn_ids:
            raise ValidationError(f"duplicate utterance_plan.turn_id: {turn_id}")
        turn_ids.add(turn_id)
        speaker_ref = _require_string(row_obj.get("speaker_ref"), f"{turn_id}.speaker_ref")
        if allowed_actor_refs is not None and speaker_ref not in allowed_actor_refs:
            raise ValidationError(f"{turn_id}.speaker_ref must exist in characters.json")
        normalized.append(
            {
                "turn_id": turn_id,
                "sequence_no": _require_int(row_obj.get("sequence_no"), f"{turn_id}.sequence_no", minimum=1),
                "session_id": _require_string(row_obj.get("session_id"), f"{turn_id}.session_id"),
                "source_type": _require_string(row_obj.get("source_type"), f"{turn_id}.source_type"),
                "source_ref": _require_string(row_obj.get("source_ref"), f"{turn_id}.source_ref"),
                "chat_ref": _require_string(row_obj.get("chat_ref"), f"{turn_id}.chat_ref"),
                "speaker_ref": speaker_ref,
                "topic_key": _require_string(row_obj.get("topic_key"), f"{turn_id}.topic_key"),
                "turn_purpose": _require_chinese_string(row_obj.get("turn_purpose"), f"{turn_id}.turn_purpose"),
                "supports_event_types": _require_string_list(row_obj.get("supports_event_types"), f"{turn_id}.supports_event_types"),
                "references_previous_turns": [str(item).strip() for item in _require_list(row_obj.get("references_previous_turns") or [], f"{turn_id}.references_previous_turns")],
                "state_transition": _require_chinese_string(row_obj.get("state_transition"), f"{turn_id}.state_transition"),
                "semantic_payload": _require_chinese_string(row_obj.get("semantic_payload"), f"{turn_id}.semantic_payload"),
                "root_turn_id": str(row_obj.get("root_turn_id") or "").strip() or None,
            }
        )
    return sorted(normalized, key=lambda item: (item["sequence_no"], item["turn_id"]))


def validate_command_plan(rows: list[dict[str, Any]], *, allowed_actor_refs: set[str] | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    output_refs: set[str] = set()
    for row in rows:
        row_obj = _require_dict(row, "command_plan[]")
        step_id = _require_string(row_obj.get("step_id"), "command_plan.step_id")
        if step_id in step_ids:
            raise ValidationError(f"duplicate command_plan.step_id: {step_id}")
        step_ids.add(step_id)
        action_type = _require_string(row_obj.get("action_type"), f"{step_id}.action_type")
        if action_type not in {"create_chat", "send_message", "reply_in_thread", "fetch_chat_messages", "fetch_thread_messages"}:
            raise ValidationError(f"{step_id}.action_type is not supported: {action_type}")
        speaker_ref = str(row_obj.get("speaker_ref") or "").strip()
        if speaker_ref and allowed_actor_refs is not None and speaker_ref not in allowed_actor_refs:
            raise ValidationError(f"{step_id}.speaker_ref must exist in characters.json")
        output_ref = str(row_obj.get("output_ref") or "").strip() or None
        if output_ref:
            if output_ref in output_refs:
                raise ValidationError(f"duplicate command_plan.output_ref: {output_ref}")
            output_refs.add(output_ref)
        params = _require_dict(row_obj.get("params"), f"{step_id}.params")
        content_text = str(params.get("content_text") or "").strip()
        if action_type in {"send_message", "reply_in_thread"} and not _CJK_RE.search(content_text):
            raise ValidationError(f"{step_id}.params.content_text must contain Chinese text")
        normalized.append(
            {
                "case_id": _require_string(row_obj.get("case_id"), f"{step_id}.case_id"),
                "step_id": step_id,
                "sequence_no": _require_int(row_obj.get("sequence_no"), f"{step_id}.sequence_no", minimum=1),
                "action_type": action_type,
                "session_id": _require_string(row_obj.get("session_id"), f"{step_id}.session_id"),
                "source_type": _require_string(row_obj.get("source_type"), f"{step_id}.source_type"),
                "source_ref": _require_string(row_obj.get("source_ref"), f"{step_id}.source_ref"),
                "channel_scope": _require_string(row_obj.get("channel_scope"), f"{step_id}.channel_scope"),
                "chat_ref": _require_string(row_obj.get("chat_ref"), f"{step_id}.chat_ref"),
                "topic_key": _require_string(row_obj.get("topic_key"), f"{step_id}.topic_key"),
                "turn_purpose": _require_chinese_string(row_obj.get("turn_purpose"), f"{step_id}.turn_purpose"),
                "speaker_role": _require_string(row_obj.get("speaker_role") or "system", f"{step_id}.speaker_role"),
                "speaker_ref": speaker_ref,
                "supports_event_types": _require_string_list(row_obj.get("supports_event_types") or [], f"{step_id}.supports_event_types"),
                "depends_on_step_ids": [str(item).strip() for item in _require_list(row_obj.get("depends_on_step_ids") or [], f"{step_id}.depends_on_step_ids") if str(item).strip()],
                "gold_intent_refs": _require_string_list(row_obj.get("gold_intent_refs") or [], f"{step_id}.gold_intent_refs"),
                "expected_effect": _require_chinese_string(row_obj.get("expected_effect"), f"{step_id}.expected_effect"),
                "state_transition": _require_chinese_string(row_obj.get("state_transition"), f"{step_id}.state_transition"),
                "semantic_payload": _require_chinese_string(row_obj.get("semantic_payload"), f"{step_id}.semantic_payload"),
                "root_turn_id": str(row_obj.get("root_turn_id") or "").strip() or None,
                "root_message_ref": str(row_obj.get("root_message_ref") or "").strip() or None,
                "output_ref": output_ref,
                "params": params,
                "lark_cli_command": _require_string(row_obj.get("lark_cli_command"), f"{step_id}.lark_cli_command"),
            }
        )
    step_id_set = {row["step_id"] for row in normalized}
    output_ref_set = {row["output_ref"] for row in normalized if row.get("output_ref")}
    for row in normalized:
        for dep in row["depends_on_step_ids"]:
            if dep not in step_id_set:
                raise ValidationError(f"{row['step_id']}.depends_on_step_ids references unknown step_id: {dep}")
        if row["action_type"] == "reply_in_thread":
            root_message_ref = str(row.get("root_message_ref") or "").strip()
            if not root_message_ref:
                raise ValidationError(f"{row['step_id']}.root_message_ref is required for reply_in_thread")
            if root_message_ref not in output_ref_set:
                raise ValidationError(f"{row['step_id']}.root_message_ref must reference an earlier output_ref")
    return sorted(normalized, key=lambda item: (item["sequence_no"], item["step_id"]))


def validate_realized_messages(rows: list[dict[str, Any]], *, allowed_actor_refs: set[str] | None = None) -> list[dict[str, Any]]:
    normalized = validate_utterance_plan(rows, allowed_actor_refs=allowed_actor_refs)
    output: list[dict[str, Any]] = []
    for row in normalized:
        payload = dict(row)
        payload["content_text"] = _require_chinese_string((next(item for item in rows if str(item.get("turn_id")) == row["turn_id"])).get("content_text"), f"{row['turn_id']}.content_text")
        output.append(payload)
    return output


def validate_collected_messages(rows: list[dict[str, Any]], *, allowed_actor_refs: set[str] | None = None) -> list[dict[str, Any]]:
    normalized = validate_realized_messages(rows, allowed_actor_refs=allowed_actor_refs)
    output: list[dict[str, Any]] = []
    for row in normalized:
        original = next(item for item in rows if str(item.get("turn_id")) == row["turn_id"])
        payload = dict(row)
        payload["message_id"] = _require_string(original.get("message_id"), f"{row['turn_id']}.message_id")
        payload["collect_source"] = _require_string(original.get("collect_source") or "fetch_records", f"{row['turn_id']}.collect_source")
        actual_sender = _require_dict(original.get("actual_sender") or {}, f"{row['turn_id']}.actual_sender")
        simulated_speaker = _require_dict(original.get("simulated_speaker") or {}, f"{row['turn_id']}.simulated_speaker")
        prefix_speaker_hint = _require_dict(original.get("prefix_speaker_hint") or {}, f"{row['turn_id']}.prefix_speaker_hint")
        payload["actual_sender"] = {
            "open_id": _optional_string(actual_sender.get("open_id")),
            "name": _optional_string(actual_sender.get("name")),
            "sender_type": _require_string(actual_sender.get("sender_type") or "user", f"{row['turn_id']}.actual_sender.sender_type"),
        }
        payload["simulated_speaker"] = {
            "speaker_ref": _require_string(simulated_speaker.get("speaker_ref"), f"{row['turn_id']}.simulated_speaker.speaker_ref"),
            "open_id": _require_string(simulated_speaker.get("open_id"), f"{row['turn_id']}.simulated_speaker.open_id"),
            "name": _require_chinese_string(simulated_speaker.get("name"), f"{row['turn_id']}.simulated_speaker.name"),
            "department": _require_chinese_string(simulated_speaker.get("department"), f"{row['turn_id']}.simulated_speaker.department"),
            "role": _require_chinese_string(simulated_speaker.get("role"), f"{row['turn_id']}.simulated_speaker.role"),
            "stance": _require_chinese_string(simulated_speaker.get("stance"), f"{row['turn_id']}.simulated_speaker.stance"),
        }
        payload["normalized_actor_id"] = _require_string(original.get("normalized_actor_id"), f"{row['turn_id']}.normalized_actor_id")
        payload["speaker_resolution_mode"] = _require_string(
            original.get("speaker_resolution_mode") or "command_plan_only",
            f"{row['turn_id']}.speaker_resolution_mode",
        )
        payload["prefix_speaker_hint"] = {
            "speaker_ref": _optional_string(prefix_speaker_hint.get("speaker_ref")),
            "name": _optional_string(prefix_speaker_hint.get("name")),
            "department": _optional_string(prefix_speaker_hint.get("department")),
        }
        output.append(payload)
    return output


def validate_expected_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required_fields_by_type = {
        "conclusion_event": ["conclusion", "target"],
        "rationale_event": ["reason"],
        "objection_event": ["objection", "objector", "target"],
        "constraint_event": ["constraint", "target"],
        "commitment_event": ["owner", "action"],
        "status_event": ["status", "target"],
        "time_event": ["time_target", "time_value", "certainty"],
        "scope_event": ["scope_target"],
    }
    normalized: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    for row in rows:
        row_obj = _require_dict(row, "expected_events[]")
        event_id = _require_string(row_obj.get("event_id"), "expected_events.event_id")
        if event_id in event_ids:
            raise ValidationError(f"duplicate expected_events.event_id: {event_id}")
        event_ids.add(event_id)
        event_type = _require_string(row_obj.get("event_type"), f"{event_id}.event_type")
        source = _require_dict(row_obj.get("source"), f"{event_id}.source")
        verification = _require_dict(row_obj.get("verification"), f"{event_id}.verification")
        gold_meta = _require_dict(row_obj.get("gold_meta"), f"{event_id}.gold_meta")
        context_quotes = _require_list(row_obj.get("context_quotes") or [], f"{event_id}.context_quotes")
        normalized_context_quotes = []
        for quote in context_quotes:
            quote_obj = _require_dict(quote, f"{event_id}.context_quotes[]")
            normalized_context_quotes.append(
                {
                    "entry_id": _require_string(quote_obj.get("entry_id"), f"{event_id}.context_quotes.entry_id"),
                    "quote": _require_chinese_string(quote_obj.get("quote"), f"{event_id}.context_quotes.quote"),
                    "role": _require_string(quote_obj.get("role"), f"{event_id}.context_quotes.role"),
                }
            )
        base_row = {
            "event_id": event_id,
            "task_ref": _require_string(row_obj.get("task_ref"), f"{event_id}.task_ref"),
            "source_session_id": _require_string(row_obj.get("source_session_id"), f"{event_id}.source_session_id"),
            "ingest_version": _require_int(row_obj.get("ingest_version"), f"{event_id}.ingest_version", minimum=1),
            "event_type": event_type,
            "claim": _require_chinese_string(row_obj.get("claim"), f"{event_id}.claim"),
            "core_entry_id": _require_string(row_obj.get("core_entry_id"), f"{event_id}.core_entry_id"),
            "evidence_quote": _require_chinese_string(row_obj.get("evidence_quote"), f"{event_id}.evidence_quote"),
            "context_quotes": normalized_context_quotes,
            "participants": _require_string_list(row_obj.get("participants") or [], f"{event_id}.participants"),
            "event_time": _require_string(row_obj.get("event_time"), f"{event_id}.event_time"),
            "source": {
                "source_type": _require_string(source.get("source_type"), f"{event_id}.source.source_type"),
                "source_id": _require_string(source.get("source_id"), f"{event_id}.source.source_id"),
                "chat_id": _optional_string(source.get("chat_id")) or None,
                "thread_id": _optional_string(source.get("thread_id")) or None,
                "root_id": _optional_string(source.get("root_id")) or None,
                "locator": _optional_string(source.get("locator")) or None,
            },
            "confidence": float(row_obj.get("confidence") or 1.0),
            "verification": {
                "core_quote_found": bool(verification.get("core_quote_found")),
                "claim_supported_by_quote": bool(verification.get("claim_supported_by_quote")),
                "context_only_generation": bool(verification.get("context_only_generation")),
                "single_atomic_claim": bool(verification.get("single_atomic_claim")),
                "required_fields_complete": bool(verification.get("required_fields_complete")),
                "no_unsupported_inference": bool(verification.get("no_unsupported_inference")),
                "verdict": _require_string(verification.get("verdict"), f"{event_id}.verification.verdict"),
            },
            "gold_meta": {
                "topic_key": _require_string(gold_meta.get("topic_key"), f"{event_id}.gold_meta.topic_key"),
                "turn_id": _require_string(gold_meta.get("turn_id"), f"{event_id}.gold_meta.turn_id"),
                "normalized_actor_id": _require_string(gold_meta.get("normalized_actor_id"), f"{event_id}.gold_meta.normalized_actor_id"),
                "evidence_turn_id": _require_string(gold_meta.get("evidence_turn_id"), f"{event_id}.gold_meta.evidence_turn_id"),
                "expected_lifecycle": _require_string(gold_meta.get("expected_lifecycle") or "active", f"{event_id}.gold_meta.expected_lifecycle"),
            },
        }
        for field in required_fields_by_type.get(event_type, []):
            base_row[field] = _require_chinese_string(row_obj.get(field), f"{event_id}.{field}")
        normalized.append(
            base_row
        )
    return normalized


def validate_expected_memory_blocks(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "expected_memory_blocks.case_id")
    blocks = _require_list(payload.get("blocks"), "expected_memory_blocks.blocks")
    normalized: list[dict[str, Any]] = []
    for block in blocks:
        block_obj = _require_dict(block, "expected_memory_blocks.blocks[]")
        block_id = _require_string(block_obj.get("block_id"), "expected_memory_blocks.block_id")
        slot_event_map = _require_dict(block_obj.get("slot_event_map"), f"{block_id}.slot_event_map")
        normalized.append(
            {
                "block_id": block_id,
                "topic_key": _require_string(block_obj.get("topic_key"), f"{block_id}.topic_key"),
                "topic_title": _require_chinese_string(block_obj.get("topic_title"), f"{block_id}.topic_title"),
                "supporting_event_ids": _require_string_list(block_obj.get("supporting_event_ids"), f"{block_id}.supporting_event_ids"),
                "slot_event_map": {str(key): _require_string_list(value, f"{block_id}.slot_event_map.{key}") for key, value in slot_event_map.items()},
            }
        )
    return {"case_id": case_id, "blocks": normalized}


def validate_target_state(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "target_state.case_id")
    expected_topics = _require_string_list(payload.get("expected_topics"), "target_state.expected_topics")
    block_targets = _require_list(payload.get("expected_block_targets"), "target_state.expected_block_targets")
    current_targets = _require_list(payload.get("expected_current_state_targets"), "target_state.expected_current_state_targets")
    normalized_block_targets: list[dict[str, Any]] = []
    for item in block_targets:
        item_obj = _require_dict(item, "target_state.expected_block_targets[]")
        normalized_block_targets.append(
            {
                "topic_key": _require_string(item_obj.get("topic_key"), "target_state.block_target.topic_key"),
                "topic_title": _require_chinese_string(item_obj.get("topic_title"), "target_state.block_target.topic_title"),
                "slots": _require_string_list(item_obj.get("slots"), "target_state.block_target.slots"),
            }
        )
    normalized_current_targets: list[dict[str, Any]] = []
    for item in current_targets:
        item_obj = _require_dict(item, "target_state.expected_current_state_targets[]")
        normalized_current_targets.append(
            {
                "topic_key": _require_string(item_obj.get("topic_key"), "target_state.current_target.topic_key"),
                "slot": _require_string(item_obj.get("slot"), "target_state.current_target.slot"),
                "claim_hint": _require_chinese_string(item_obj.get("claim_hint"), "target_state.current_target.claim_hint"),
            }
        )
    return {
        "case_id": case_id,
        "expected_topics": expected_topics,
        "expected_block_targets": normalized_block_targets,
        "expected_current_state_targets": normalized_current_targets,
        "required_event_coverage": _require_string_list(payload.get("required_event_coverage"), "target_state.required_event_coverage"),
        "required_state_transitions": _require_string_list(payload.get("required_state_transitions"), "target_state.required_state_transitions"),
        "required_cross_source_revisions": _require_string_list(
            payload.get("required_cross_source_revisions"), "target_state.required_cross_source_revisions"
        ),
    }


def validate_expected_current_state(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "expected_current_state.case_id")
    current_items = _require_list(payload.get("current_items"), "expected_current_state.current_items")
    normalized: list[dict[str, Any]] = []
    for item in current_items:
        item_obj = _require_dict(item, "expected_current_state.current_items[]")
        normalized.append(
            {
                "topic_key": _require_string(item_obj.get("topic_key"), "expected_current_state.topic_key"),
                "slot": _require_string(item_obj.get("slot"), "expected_current_state.slot"),
                "event_id": _require_string(item_obj.get("event_id"), "expected_current_state.event_id"),
                "claim": _require_chinese_string(item_obj.get("claim"), "expected_current_state.claim"),
                "source_session_id": _require_string(item_obj.get("source_session_id"), "expected_current_state.source_session_id"),
            }
        )
    return {"case_id": case_id, "current_items": normalized}


def validate_complexity_report(payload: dict[str, Any]) -> dict[str, Any]:
    report = _require_dict(payload, "complexity_report")
    metrics = _require_dict(report.get("metrics"), "complexity_report.metrics")
    thresholds = _require_dict(report.get("thresholds"), "complexity_report.thresholds")
    return {
        "case_id": _require_string(report.get("case_id"), "complexity_report.case_id"),
        "passed": bool(report.get("passed")),
        "failed_checks": _require_string_list(report.get("failed_checks") or [], "complexity_report.failed_checks"),
        "metrics": {str(key): _require_int(value, f"complexity_report.metrics.{key}", minimum=0) for key, value in metrics.items()},
        "thresholds": {str(key): _require_int(value, f"complexity_report.thresholds.{key}", minimum=0) for key, value in thresholds.items()},
    }


def validate_dataset_validation_report(payload: dict[str, Any]) -> dict[str, Any]:
    report = _require_dict(payload, "dataset_validation_report")
    return {
        "case_id": _require_string(report.get("case_id"), "dataset_validation_report.case_id"),
        "passed": bool(report.get("passed")),
        "errors": _require_string_list(report.get("errors") or [], "dataset_validation_report.errors"),
        "checks": _require_dict(report.get("checks"), "dataset_validation_report.checks"),
    }


def validate_timeline(payload: dict[str, Any], *, allowed_actor_refs: set[str] | None = None) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "timeline.case_id")
    events = _require_list(payload.get("timeline"), "timeline.timeline")
    if not 6 <= len(events) <= 12:
        raise ValidationError("timeline.timeline must contain 6 to 12 events")
    normalized: list[dict[str, Any]] = []
    previous_order = 0
    for event in events:
        if not isinstance(event, dict):
            raise ValidationError("timeline.timeline[] must be an object")
        actor_refs = [_require_string(item, "timeline.actor_refs[]") for item in _require_list(event.get("actor_refs"), "timeline.actor_refs")]
        if allowed_actor_refs is not None:
            unknown = [ref for ref in actor_refs if ref not in allowed_actor_refs]
            if unknown:
                raise ValidationError(f"timeline actor_refs not in characters.json: {', '.join(unknown)}")
        time_order = int(event.get("time_order") or 0)
        if time_order <= previous_order:
            raise ValidationError("timeline.time_order must be strictly increasing")
        previous_order = time_order
        normalized.append(
            {
                "timeline_id": _require_string(event.get("timeline_id"), "timeline.timeline_id"),
                "time_order": time_order,
                "event_type": _require_string(event.get("event_type"), "timeline.event_type"),
                "description": _require_chinese_string(event.get("description"), "timeline.description"),
                "actor_refs": actor_refs,
                "affected_topic": _require_chinese_string(event.get("affected_topic"), "timeline.affected_topic"),
                "state_effect": _require_chinese_string(event.get("state_effect"), "timeline.state_effect"),
                "should_surface_in_message": bool(event.get("should_surface_in_message", True)),
            }
        )
    return {"case_id": case_id, "timeline": normalized}


def validate_execution_plan(payload: dict[str, Any], *, allowed_sender_refs: set[str] | None = None) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "plan.case_id")
    operator_identity = str(payload.get("operator_identity") or "user").strip() or "user"
    delivery_mode = str(payload.get("delivery_mode") or "prefixed_single_operator").strip() or "prefixed_single_operator"
    actions = _require_list(payload.get("actions"), "plan.actions")
    if not actions:
        raise ValidationError("plan.actions must not be empty")
    action_ids: set[str] = set()
    output_refs: set[str] = set()
    normalized: list[dict[str, Any]] = []
    message_output_refs: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            raise ValidationError("plan.actions[] must be an object")
        action_id = _require_string(action.get("action_id"), "plan.action_id")
        if action_id in action_ids:
            raise ValidationError(f"duplicate action_id: {action_id}")
        action_ids.add(action_id)
        action_type = _require_string(action.get("action_type"), "plan.action_type")
        params = action.get("params")
        if not isinstance(params, dict):
            raise ValidationError(f"{action_id}.params must be an object")
        output_ref = str(action.get("output_ref") or "").strip()
        if output_ref:
            if output_ref in output_refs:
                raise ValidationError(f"duplicate output_ref: {output_ref}")
            output_refs.add(output_ref)
        sender_ref = str(params.get("sender_ref") or "").strip()
        if sender_ref and allowed_sender_refs is not None and sender_ref not in allowed_sender_refs:
            raise ValidationError(f"{action_id}.sender_ref must exist in characters.json")
        if action_type == "create_chat":
            _require_chinese_string(params.get("name"), f"{action_id}.params.name")
        if action_type in {"send_message", "reply_in_thread"}:
            _require_chinese_string(params.get("content_text"), f"{action_id}.params.content_text")
        depends_on = [str(item).strip() for item in action.get("depends_on", []) if str(item).strip()]
        normalized_action = {
            "action_id": action_id,
            "action_type": action_type,
            "depends_on": depends_on,
            "params": params,
        }
        if output_ref:
            normalized_action["output_ref"] = output_ref
        normalized.append(normalized_action)
        if action_type == "send_message" and output_ref:
            message_output_refs.add(output_ref)
    for action in normalized:
        if action["action_type"] == "reply_in_thread":
            root_ref = str(action["params"].get("root_message_ref") or "").strip()
            if root_ref not in message_output_refs:
                raise ValidationError(
                    f"{action['action_id']}.params.root_message_ref must reference an existing send_message output_ref"
                )
    return {
        "case_id": case_id,
        "operator_identity": operator_identity,
        "delivery_mode": delivery_mode,
        "actions": normalized,
    }


def validate_execution_result(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "execution_result.case_id")
    status = str(payload.get("status") or "unknown").strip() or "unknown"
    created_resources = payload.get("created_resources")
    action_status = payload.get("action_status")
    if not isinstance(created_resources, dict):
        raise ValidationError("execution_result.created_resources must be an object")
    if not isinstance(action_status, list):
        raise ValidationError("execution_result.action_status must be a list")
    return {
        "case_id": case_id,
        "status": status,
        "operator_identity": str(payload.get("operator_identity") or "user"),
        "delivery_mode": str(payload.get("delivery_mode") or "prefixed_single_operator"),
        "created_resources": created_resources,
        "thread_id_to_chat_id": payload.get("thread_id_to_chat_id") or {},
        "action_status": action_status,
        "preflight": payload.get("preflight") or {},
    }


def validate_build_report(payload: dict[str, Any]) -> dict[str, Any]:
    required = [
        "case_id",
        "status",
        "operator_identity",
        "delivery_mode",
        "preflight",
        "fetch_identity",
        "num_characters",
        "num_topics",
        "num_source_sessions",
        "num_collected_messages",
        "num_planned_actions",
        "num_executed_actions",
        "num_lark_messages_collected",
        "num_openclaw_ingress_events",
        "warnings",
    ]
    for field in required:
        if field not in payload:
            raise ValidationError(f"build_report missing field: {field}")
    return dict(payload)


@dataclass(frozen=True)
class ArtifactBundle:
    case_spec: dict[str, Any]
    story: dict[str, Any]
    characters: dict[str, Any]
    timeline: dict[str, Any]
    execution_plan: dict[str, Any]
