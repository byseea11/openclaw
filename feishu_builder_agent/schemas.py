from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class ValidationError(ValueError):
    """Raised when a builder artifact does not match the expected schema."""


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _require_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} must be a non-empty string")
    return text


def _require_chinese_string(value: Any, field: str) -> str:
    text = _require_string(value, field)
    if not _CJK_RE.search(text):
        raise ValidationError(f"{field} must contain Chinese text")
    return text


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    return value


def validate_case_spec(payload: dict[str, Any]) -> dict[str, Any]:
    departments = [_require_chinese_string(item, "departments[]") for item in _require_list(payload.get("departments"), "departments")]
    return {
        "case_id": _require_string(payload.get("case_id"), "case_id"),
        "task_id": _require_string(payload.get("task_id"), "task_id"),
        "title": _require_chinese_string(payload.get("title"), "title"),
        "company_type": _require_chinese_string(payload.get("company_type"), "company_type"),
        "departments": departments,
        "main_goal": _require_chinese_string(payload.get("main_goal"), "main_goal"),
        "difficulty": str(payload.get("difficulty") or "medium").strip() or "medium",
        "seed": int(payload.get("seed") or 0),
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
    if not 6 <= len(characters) <= 10:
        raise ValidationError("characters.characters must contain 6 to 10 roles")
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
                "responsibility": _require_chinese_string(character.get("responsibility"), f"{person_id}.responsibility"),
                "communication_style": _require_chinese_string(character.get("communication_style"), f"{person_id}.communication_style"),
                "conflict_bias": _require_chinese_string(character.get("conflict_bias"), f"{person_id}.conflict_bias"),
            }
        )
    return {"case_id": case_id, "characters": normalized}


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
        "num_timeline_events",
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
