from __future__ import annotations

import re
from typing import Any

from .builder_settings import FAILURE_MODES, load_builder_settings


class ValidationError(ValueError):
    """Raised when a builder artifact does not match the expected schema."""


_CASE_ID_RE = re.compile(r"^case_[a-z0-9_]+$")
_TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9A-Za-z]+$")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_BENCHMARK_ROLES = {
    "target_fact_turn",
    "evidence_anchor_turn",
    "stale_state_turn",
    "supersession_turn",
    "final_current_state_turn",
    "distractor_task_turn",
    "shared_actor_turn",
    "memory_pollution_turn",
    "ambiguous_claim_turn",
    "hearsay_turn",
    "weak_commitment_turn",
    "ordinary_ack_turn",
    "context_only_turn",
    "dependency_link_turn",
    "dependency_update_turn",
    "current_state_disambiguation_turn",
    "probe_setup_turn",
}
_ACTION_TYPES = {
    "create_chat",
    "send_message",
    "reply_in_thread",
    "fetch_chat_messages",
    "fetch_thread_messages",
}


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    return value


def _require_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} must be a non-empty string")
    return text


def _optional_string(value: Any) -> str:
    return str(value or "").strip()


def _require_int(value: Any, field: str, *, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be an integer") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    return number


def _require_float(value: Any, field: str, *, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a number") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    return number


def _require_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValidationError(f"{field} must be a boolean")


def _require_chinese_string(value: Any, field: str) -> str:
    text = _require_string(value, field)
    if not _CJK_RE.search(text):
        raise ValidationError(f"{field} must contain Chinese text")
    return text


def _optional_chinese_string(value: Any, field: str) -> str:
    text = _optional_string(value)
    if text and not _CJK_RE.search(text):
        raise ValidationError(f"{field} must contain Chinese text")
    return text


def _require_string_list(value: Any, field: str) -> list[str]:
    return [_require_string(item, f"{field}[]") for item in _require_list(value, field)]


def _require_unique_strings(value: Any, field: str) -> list[str]:
    result: list[str] = []
    for item in _require_string_list(value, field):
        if item not in result:
            result.append(item)
    return result


def _require_failure_modes(value: Any, field: str) -> list[str]:
    items = _require_unique_strings(value, field)
    for item in items:
        if item not in FAILURE_MODES:
            raise ValidationError(f"{field} contains unknown failure mode: {item}")
    return items


def _require_benchmark_roles(value: Any, field: str) -> list[str]:
    roles = _require_unique_strings(value, field)
    for item in roles:
        if item not in _BENCHMARK_ROLES:
            raise ValidationError(f"{field} contains unknown benchmark_role: {item}")
    return roles


def _default_simulated_open_id(person_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_]+", "_", person_id).strip("_").lower()
    return f"ou_sim_{safe_id}"


def validate_case_spec(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_difficulties = set(load_builder_settings()["difficulty_profiles"].keys())
    difficulty = _require_string(payload.get("difficulty"), "case_spec.difficulty")
    if difficulty not in allowed_difficulties:
        raise ValidationError(f"case_spec.difficulty must be one of: {', '.join(sorted(allowed_difficulties))}")
    case_id = _require_string(payload.get("case_id"), "case_spec.case_id")
    if not _CASE_ID_RE.fullmatch(case_id):
        raise ValidationError("case_spec.case_id must use lower_snake_case and start with case_")
    task_id = _require_string(payload.get("task_id"), "case_spec.task_id")
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ValidationError("case_spec.task_id must use UPPER-SLUG form like FEISHU-231")
    selected_failure_modes = _require_failure_modes(
        payload.get("selected_failure_modes"),
        "case_spec.selected_failure_modes",
    )
    primary_failure_mode = _require_string(payload.get("primary_failure_mode"), "case_spec.primary_failure_mode")
    if primary_failure_mode not in selected_failure_modes:
        raise ValidationError("case_spec.primary_failure_mode must belong to selected_failure_modes")
    comparison_target = _require_string(payload.get("comparison_target"), "case_spec.comparison_target")
    departments = [
        _require_chinese_string(item, "case_spec.department_hints[]")
        for item in _require_list(payload.get("department_hints"), "case_spec.department_hints")
    ]
    if not departments:
        raise ValidationError("case_spec.department_hints must not be empty")
    return {
        "case_id": case_id,
        "task_id": task_id,
        "title": _optional_chinese_string(payload.get("title"), "case_spec.title"),
        "company_type": _optional_chinese_string(payload.get("company_type"), "case_spec.company_type"),
        "department_hints": departments,
        "scenario_profile": _require_string(payload.get("scenario_profile"), "case_spec.scenario_profile"),
        "title_hint": _optional_chinese_string(payload.get("title_hint"), "case_spec.title_hint"),
        "main_goal_hint": _optional_chinese_string(payload.get("main_goal_hint"), "case_spec.main_goal_hint"),
        "main_goal": _optional_chinese_string(payload.get("main_goal"), "case_spec.main_goal"),
        "difficulty": difficulty,
        "seed": _require_int(payload.get("seed"), "case_spec.seed", minimum=0),
        "comparison_target": comparison_target,
        "selected_failure_modes": selected_failure_modes,
        "primary_failure_mode": primary_failure_mode,
        "user_hint": _optional_string(payload.get("user_hint")),
    }


def _validate_probe_queries(value: Any, field: str) -> list[str]:
    result = []
    for item in _require_list(value, field):
        text = _require_chinese_string(item, f"{field}[]")
        if text not in result:
            result.append(text)
    return result


def _validate_landing_requirements(payload: Any, field: str) -> dict[str, Any]:
    obj = _require_dict(payload, field)
    return {
        "required_benchmark_roles": _require_benchmark_roles(
            obj.get("required_benchmark_roles"),
            f"{field}.required_benchmark_roles",
        ),
        "required_state_fields": _require_unique_strings(
            obj.get("required_state_fields") or [],
            f"{field}.required_state_fields",
        ),
        "required_evidence_messages_min": _require_int(
            obj.get("required_evidence_messages_min"),
            f"{field}.required_evidence_messages_min",
            minimum=1,
        ),
        "required_probe_queries_min": _require_int(
            obj.get("required_probe_queries_min"),
            f"{field}.required_probe_queries_min",
            minimum=1,
        ),
    }


def _validate_typed_payload(failure_mode: str, payload: Any, field: str) -> dict[str, Any]:
    obj = _require_dict(payload, field)
    if failure_mode == "personal_memory_pollution":
        return {
            "payload_type": "personal_memory_pollution_payload",
            "target_task_summary": _require_chinese_string(obj.get("target_task_summary"), f"{field}.target_task_summary"),
            "overlapping_slots": _require_unique_strings(obj.get("overlapping_slots"), f"{field}.overlapping_slots"),
            "pollution_dimensions": _require_unique_strings(obj.get("pollution_dimensions"), f"{field}.pollution_dimensions"),
            "distractor_task_ids": _require_unique_strings(obj.get("distractor_task_ids"), f"{field}.distractor_task_ids"),
        }
    if failure_mode == "unverifiable_summary_claim":
        evidence_distribution = _require_dict(obj.get("evidence_distribution"), f"{field}.evidence_distribution")
        return {
            "payload_type": "unverifiable_summary_claim_payload",
            "target_claim": _require_chinese_string(obj.get("target_claim"), f"{field}.target_claim"),
            "evidence_distribution": {
                "verified_fact_turns": _require_int(
                    evidence_distribution.get("verified_fact_turns"),
                    f"{field}.evidence_distribution.verified_fact_turns",
                    minimum=1,
                ),
                "ambiguous_turns": _require_int(
                    evidence_distribution.get("ambiguous_turns"),
                    f"{field}.evidence_distribution.ambiguous_turns",
                    minimum=1,
                ),
                "hearsay_turns": _require_int(
                    evidence_distribution.get("hearsay_turns"),
                    f"{field}.evidence_distribution.hearsay_turns",
                    minimum=1,
                ),
                "weak_commitment_turns": _require_int(
                    evidence_distribution.get("weak_commitment_turns"),
                    f"{field}.evidence_distribution.weak_commitment_turns",
                    minimum=0,
                ),
                "no_event_turns": _require_int(
                    evidence_distribution.get("no_event_turns"),
                    f"{field}.evidence_distribution.no_event_turns",
                    minimum=1,
                ),
            },
        }
    if failure_mode == "static_memory_stale_state":
        required_state_track = _require_dict(obj.get("required_state_track"), f"{field}.required_state_track")
        return {
            "payload_type": "static_memory_stale_state_payload",
            "required_state_track": {
                "field": _require_string(required_state_track.get("field"), f"{field}.required_state_track.field"),
                "states": _require_unique_strings(required_state_track.get("states"), f"{field}.required_state_track.states"),
                "final_current_state": _require_string(
                    required_state_track.get("final_current_state"),
                    f"{field}.required_state_track.final_current_state",
                ),
                "stale_states": _require_unique_strings(
                    required_state_track.get("stale_states"),
                    f"{field}.required_state_track.stale_states",
                ),
            },
        }
    if failure_mode == "dependency_propagation_failure":
        return {
            "payload_type": "dependency_propagation_failure_payload",
            "upstream_task_id": _require_string(obj.get("upstream_task_id"), f"{field}.upstream_task_id"),
            "dependency_chain": _require_unique_strings(obj.get("dependency_chain"), f"{field}.dependency_chain"),
            "impacted_field": _require_string(obj.get("impacted_field"), f"{field}.impacted_field"),
            "expected_missed_update": _require_chinese_string(
                obj.get("expected_missed_update"),
                f"{field}.expected_missed_update",
            ),
        }
    raise ValidationError(f"{field} has unsupported failure mode: {failure_mode}")


def validate_memory_failure_blueprint(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = _require_string(payload.get("case_id"), "memory_failure_blueprint.case_id")
    task_id = _require_string(payload.get("task_id"), "memory_failure_blueprint.task_id")
    comparison_target = _require_string(
        payload.get("comparison_target"),
        "memory_failure_blueprint.comparison_target",
    )
    selected_failure_modes = _require_failure_modes(
        payload.get("selected_failure_modes"),
        "memory_failure_blueprint.selected_failure_modes",
    )
    primary_failure_mode = _require_string(
        payload.get("primary_failure_mode"),
        "memory_failure_blueprint.primary_failure_mode",
    )
    if primary_failure_mode not in selected_failure_modes:
        raise ValidationError("memory_failure_blueprint.primary_failure_mode must belong to selected_failure_modes")
    traps = []
    for index, raw_trap in enumerate(_require_list(payload.get("traps"), "memory_failure_blueprint.traps"), start=1):
        trap = _require_dict(raw_trap, f"memory_failure_blueprint.traps[{index}]")
        failure_mode = _require_string(trap.get("failure_mode"), f"memory_failure_blueprint.traps[{index}].failure_mode")
        if failure_mode not in selected_failure_modes:
            raise ValidationError("memory_failure_blueprint.traps[].failure_mode must belong to selected_failure_modes")
        common = _require_dict(trap.get("common"), f"memory_failure_blueprint.traps[{index}].common")
        normalized_trap = {
            "trap_id": _require_string(trap.get("trap_id"), f"memory_failure_blueprint.traps[{index}].trap_id"),
            "failure_mode": failure_mode,
            "target_task_id": _require_string(
                trap.get("target_task_id"),
                f"memory_failure_blueprint.traps[{index}].target_task_id",
            ),
            "trap_mechanism": _require_chinese_string(
                trap.get("trap_mechanism"),
                f"memory_failure_blueprint.traps[{index}].trap_mechanism",
            ),
            "common": {
                "distractor_tasks": _require_unique_strings(
                    common.get("distractor_tasks"),
                    f"memory_failure_blueprint.traps[{index}].common.distractor_tasks",
                ),
                "shared_actors": _require_unique_strings(
                    common.get("shared_actors"),
                    f"memory_failure_blueprint.traps[{index}].common.shared_actors",
                ),
                "probe_queries": _validate_probe_queries(
                    common.get("probe_queries"),
                    f"memory_failure_blueprint.traps[{index}].common.probe_queries",
                ),
                "metric_targets": _require_unique_strings(
                    common.get("metric_targets"),
                    f"memory_failure_blueprint.traps[{index}].common.metric_targets",
                ),
                "landing_requirements": _validate_landing_requirements(
                    common.get("landing_requirements"),
                    f"memory_failure_blueprint.traps[{index}].common.landing_requirements",
                ),
            },
            "typed_payload": _validate_typed_payload(
                failure_mode,
                trap.get("typed_payload"),
                f"memory_failure_blueprint.traps[{index}].typed_payload",
            ),
            "expected_openclaw_failure": _require_chinese_string(
                trap.get("expected_openclaw_failure"),
                f"memory_failure_blueprint.traps[{index}].expected_openclaw_failure",
            ),
            "expected_task_wiki_success": _require_chinese_string(
                trap.get("expected_task_wiki_success"),
                f"memory_failure_blueprint.traps[{index}].expected_task_wiki_success",
            ),
        }
        traps.append(normalized_trap)
    if not traps:
        raise ValidationError("memory_failure_blueprint.traps must not be empty")
    for failure_mode in selected_failure_modes:
        if not any(trap["failure_mode"] == failure_mode for trap in traps):
            raise ValidationError(f"memory_failure_blueprint.traps must include at least one trap for {failure_mode}")
    return {
        "case_id": case_id,
        "task_id": task_id,
        "comparison_target": comparison_target,
        "selected_failure_modes": selected_failure_modes,
        "primary_failure_mode": primary_failure_mode,
        "traps": traps,
    }


def validate_task_actor_layout(payload: dict[str, Any]) -> dict[str, Any]:
    target_task = _require_dict(payload.get("target_task"), "task_actor_layout.target_task")
    distractor_tasks = []
    for item in _require_list(payload.get("distractor_tasks"), "task_actor_layout.distractor_tasks"):
        obj = _require_dict(item, "task_actor_layout.distractor_tasks[]")
        distractor_tasks.append(
            {
                "task_id": _require_string(obj.get("task_id"), "task_actor_layout.distractor_tasks.task_id"),
                "title": _require_chinese_string(obj.get("title"), "task_actor_layout.distractor_tasks.title"),
                "relationship_to_target": _require_chinese_string(
                    obj.get("relationship_to_target"),
                    "task_actor_layout.distractor_tasks.relationship_to_target",
                ),
            }
        )
    shared_actor_slots = []
    for item in _require_list(payload.get("shared_actor_slots"), "task_actor_layout.shared_actor_slots"):
        obj = _require_dict(item, "task_actor_layout.shared_actor_slots[]")
        shared_actor_slots.append(
            {
                "actor_slot_id": _require_string(obj.get("actor_slot_id"), "task_actor_layout.shared_actor_slots.actor_slot_id"),
                "department": _require_chinese_string(obj.get("department"), "task_actor_layout.shared_actor_slots.department"),
                "role_label": _require_chinese_string(obj.get("role_label"), "task_actor_layout.shared_actor_slots.role_label"),
                "task_ids": _require_unique_strings(obj.get("task_ids"), "task_actor_layout.shared_actor_slots.task_ids"),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "task_actor_layout.case_id"),
        "task_id": _require_string(payload.get("task_id"), "task_actor_layout.task_id"),
        "target_task": {
            "task_id": _require_string(target_task.get("task_id"), "task_actor_layout.target_task.task_id"),
            "title": _require_chinese_string(target_task.get("title"), "task_actor_layout.target_task.title"),
            "task_scope": _require_chinese_string(target_task.get("task_scope"), "task_actor_layout.target_task.task_scope"),
        },
        "distractor_tasks": distractor_tasks,
        "shared_actor_slots": shared_actor_slots,
        "pollution_dimensions": _require_unique_strings(
            payload.get("pollution_dimensions"),
            "task_actor_layout.pollution_dimensions",
        ),
        "task_actor_overlap": _require_list(payload.get("task_actor_overlap"), "task_actor_layout.task_actor_overlap"),
    }


def validate_case_world_v3(payload: dict[str, Any]) -> dict[str, Any]:
    case_generation_goal = _require_dict(payload.get("case_generation_goal"), "case_world.case_generation_goal")
    memory_failure_profile = _require_dict(payload.get("memory_failure_profile"), "case_world.memory_failure_profile")
    source_sessions = []
    for item in _require_list(payload.get("source_sessions"), "case_world.source_sessions"):
        obj = _require_dict(item, "case_world.source_sessions[]")
        source_sessions.append(
            {
                "session_id": _require_string(obj.get("session_id"), "case_world.source_sessions.session_id"),
                "source_type": _require_string(obj.get("source_type"), "case_world.source_sessions.source_type"),
                "source_ref": _require_string(obj.get("source_ref"), "case_world.source_sessions.source_ref"),
                "chat_ref": _require_string(obj.get("chat_ref"), "case_world.source_sessions.chat_ref"),
                "title": _require_chinese_string(obj.get("title"), "case_world.source_sessions.title"),
                "session_purpose": _require_chinese_string(
                    obj.get("session_purpose"),
                    "case_world.source_sessions.session_purpose",
                ),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "case_world.case_id"),
        "task_id": _require_string(payload.get("task_id"), "case_world.task_id"),
        "title": _require_chinese_string(payload.get("title"), "case_world.title"),
        "company_type": _require_chinese_string(payload.get("company_type"), "case_world.company_type"),
        "business_context": _require_chinese_string(payload.get("business_context"), "case_world.business_context"),
        "case_generation_goal": {
            "baseline": _require_string(case_generation_goal.get("baseline"), "case_world.case_generation_goal.baseline"),
            "goal": _require_chinese_string(case_generation_goal.get("goal"), "case_world.case_generation_goal.goal"),
        },
        "memory_failure_profile": {
            "selected_failure_modes": _require_failure_modes(
                memory_failure_profile.get("selected_failure_modes"),
                "case_world.memory_failure_profile.selected_failure_modes",
            ),
            "primary_failure_mode": _require_string(
                memory_failure_profile.get("primary_failure_mode"),
                "case_world.memory_failure_profile.primary_failure_mode",
            ),
        },
        "task_and_actor_layout_summary": _require_chinese_string(
            payload.get("task_and_actor_layout_summary"),
            "case_world.task_and_actor_layout_summary",
        ),
        "distractor_memory_context": [
            _require_chinese_string(item, "case_world.distractor_memory_context[]")
            for item in _require_list(payload.get("distractor_memory_context"), "case_world.distractor_memory_context")
        ],
        "discussion_reasons": [
            _require_chinese_string(item, "case_world.discussion_reasons[]")
            for item in _require_list(payload.get("discussion_reasons"), "case_world.discussion_reasons")
        ],
        "info_distribution_reason": _require_chinese_string(
            payload.get("info_distribution_reason"),
            "case_world.info_distribution_reason",
        ),
        "ambiguity_reason": _require_chinese_string(payload.get("ambiguity_reason"), "case_world.ambiguity_reason"),
        "revision_reason": _require_chinese_string(payload.get("revision_reason"), "case_world.revision_reason"),
        "source_sessions": source_sessions,
    }


def validate_case_world(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_case_world_v3(payload)


def validate_characters(payload: dict[str, Any]) -> dict[str, Any]:
    characters = []
    seen_ids: set[str] = set()
    for item in _require_list(payload.get("characters"), "characters.characters"):
        obj = _require_dict(item, "characters.characters[]")
        person_id = _require_string(obj.get("person_id"), "characters.characters.person_id")
        if person_id in seen_ids:
            raise ValidationError(f"duplicate characters.person_id: {person_id}")
        seen_ids.add(person_id)
        simulated_open_id = _require_string(obj.get("simulated_open_id"), "characters.characters.simulated_open_id")
        expected_open_id = _default_simulated_open_id(person_id)
        if simulated_open_id != expected_open_id:
            raise ValidationError(f"characters.characters.simulated_open_id must equal {expected_open_id}")
        characters.append(
            {
                "person_id": person_id,
                "actor_slot_id": _require_string(obj.get("actor_slot_id"), "characters.characters.actor_slot_id"),
                "simulated_open_id": simulated_open_id,
                "name": _require_chinese_string(obj.get("name"), "characters.characters.name"),
                "department": _require_chinese_string(obj.get("department"), "characters.characters.department"),
                "role": _require_chinese_string(obj.get("role"), "characters.characters.role"),
                "task_ids": _require_unique_strings(obj.get("task_ids"), "characters.characters.task_ids"),
                "default_channels": _require_unique_strings(obj.get("default_channels"), "characters.characters.default_channels"),
                "profile": _require_chinese_string(obj.get("profile"), "characters.characters.profile"),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "characters.case_id"),
        "characters": characters,
    }


def validate_actor_registry(payload: dict[str, Any]) -> dict[str, Any]:
    actors = []
    for item in _require_list(payload.get("actors"), "actor_registry.actors"):
        obj = _require_dict(item, "actor_registry.actors[]")
        actors.append(
            {
                "person_id": _require_string(obj.get("person_id"), "actor_registry.actors.person_id"),
                "simulated_open_id": _require_string(
                    obj.get("simulated_open_id"),
                    "actor_registry.actors.simulated_open_id",
                ),
                "name": _require_chinese_string(obj.get("name"), "actor_registry.actors.name"),
                "department": _require_chinese_string(obj.get("department"), "actor_registry.actors.department"),
                "role": _require_chinese_string(obj.get("role"), "actor_registry.actors.role"),
                "default_channels": _require_unique_strings(
                    obj.get("default_channels"),
                    "actor_registry.actors.default_channels",
                ),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "actor_registry.case_id"),
        "actors": actors,
    }


def validate_state_trajectory(payload: dict[str, Any]) -> dict[str, Any]:
    transitions = []
    for item in _require_list(payload.get("transitions"), "state_trajectory.transitions"):
        obj = _require_dict(item, "state_trajectory.transitions[]")
        transitions.append(
            {
                "transition_id": _require_string(obj.get("transition_id"), "state_trajectory.transitions.transition_id"),
                "trap_id": _require_string(obj.get("trap_id"), "state_trajectory.transitions.trap_id"),
                "failure_mode": _require_string(obj.get("failure_mode"), "state_trajectory.transitions.failure_mode"),
                "state_field": _require_string(obj.get("state_field"), "state_trajectory.transitions.state_field"),
                "from_value": _optional_string(obj.get("from_value")),
                "to_value": _optional_string(obj.get("to_value")),
                "creates_stale_state": _optional_string(
                    obj.get("creates_stale_state"),
                ),
                "supersedes_transition_id": _optional_string(obj.get("supersedes_transition_id")),
                "is_final_current_state": _require_bool(
                    obj.get("is_final_current_state"),
                    "state_trajectory.transitions.is_final_current_state",
                ),
                "source_session_ref": _require_string(
                    obj.get("source_session_ref"),
                    "state_trajectory.transitions.source_session_ref",
                ),
                "evidence_requirement": _require_chinese_string(
                    obj.get("evidence_requirement"),
                    "state_trajectory.transitions.evidence_requirement",
                ),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "state_trajectory.case_id"),
        "task_id": _require_string(payload.get("task_id"), "state_trajectory.task_id"),
        "transitions": transitions,
        "final_current_state": _require_dict(payload.get("final_current_state"), "state_trajectory.final_current_state"),
    }


def validate_coverage_spec(payload: dict[str, Any]) -> dict[str, Any]:
    trap_coverage = _require_dict(payload.get("trap_coverage"), "coverage_spec.trap_coverage")
    return {
        "case_id": _require_string(payload.get("case_id"), "coverage_spec.case_id"),
        "required_failure_modes": _require_failure_modes(
            payload.get("required_failure_modes"),
            "coverage_spec.required_failure_modes",
        ),
        "required_benchmark_roles": _require_benchmark_roles(
            payload.get("required_benchmark_roles"),
            "coverage_spec.required_benchmark_roles",
        ),
        "required_query_types": _require_unique_strings(
            payload.get("required_query_types"),
            "coverage_spec.required_query_types",
        ),
        "required_state_fields": _require_unique_strings(
            payload.get("required_state_fields"),
            "coverage_spec.required_state_fields",
        ),
        "trap_coverage": {
            "required_traps": _require_list(trap_coverage.get("required_traps"), "coverage_spec.trap_coverage.required_traps"),
        },
        "hard_gates": _require_dict(payload.get("hard_gates"), "coverage_spec.hard_gates"),
    }


def validate_story_beats(payload: dict[str, Any]) -> dict[str, Any]:
    beats = []
    for item in _require_list(payload.get("beats"), "story_beats.beats"):
        obj = _require_dict(item, "story_beats.beats[]")
        beats.append(
            {
                "beat_id": _require_string(obj.get("beat_id"), "story_beats.beats.beat_id"),
                "trap_id": _require_string(obj.get("trap_id"), "story_beats.beats.trap_id"),
                "failure_mode": _require_string(obj.get("failure_mode"), "story_beats.beats.failure_mode"),
                "beat_type": _require_string(obj.get("beat_type"), "story_beats.beats.beat_type"),
                "benchmark_role": _require_string(obj.get("benchmark_role"), "story_beats.beats.benchmark_role"),
                "description": _require_chinese_string(obj.get("description"), "story_beats.beats.description"),
                "target_session_id": _require_string(
                    obj.get("target_session_id"),
                    "story_beats.beats.target_session_id",
                ),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "story_beats.case_id"),
        "beats": beats,
    }


def validate_conversation_plan_v3(payload: dict[str, Any], *, allowed_actor_refs: set[str] | None = None) -> dict[str, Any]:
    sessions = []
    session_ids: set[str] = set()
    for item in _require_list(payload.get("sessions"), "conversation_plan.sessions"):
        obj = _require_dict(item, "conversation_plan.sessions[]")
        session_id = _require_string(obj.get("session_id"), "conversation_plan.sessions.session_id")
        session_ids.add(session_id)
        sessions.append(
            {
                "session_id": session_id,
                "source_type": _require_string(obj.get("source_type"), "conversation_plan.sessions.source_type"),
                "source_ref": _require_string(obj.get("source_ref"), "conversation_plan.sessions.source_ref"),
                "chat_ref": _require_string(obj.get("chat_ref"), "conversation_plan.sessions.chat_ref"),
                "title": _require_chinese_string(obj.get("title"), "conversation_plan.sessions.title"),
                "session_purpose": _require_chinese_string(
                    obj.get("session_purpose"),
                    "conversation_plan.sessions.session_purpose",
                ),
                "root_turn_id": _optional_string(obj.get("root_turn_id")) or None,
            }
        )
    turns = []
    seen_turn_ids: set[str] = set()
    for item in _require_list(payload.get("turns"), "conversation_plan.turns"):
        obj = _require_dict(item, "conversation_plan.turns[]")
        turn_id = _require_string(obj.get("turn_id"), "conversation_plan.turns.turn_id")
        if turn_id in seen_turn_ids:
            raise ValidationError(f"duplicate conversation_plan.turn_id: {turn_id}")
        seen_turn_ids.add(turn_id)
        session_id = _require_string(obj.get("session_id"), "conversation_plan.turns.session_id")
        if session_id not in session_ids:
            raise ValidationError(f"conversation_plan.turn.session_id not found: {session_id}")
        speaker_ref = _require_string(obj.get("speaker_ref"), "conversation_plan.turns.speaker_ref")
        if allowed_actor_refs is not None and speaker_ref not in allowed_actor_refs:
            raise ValidationError(f"conversation_plan.turn speaker_ref not found in characters: {speaker_ref}")
        benchmark_role = _require_string(obj.get("benchmark_role"), "conversation_plan.turns.benchmark_role")
        if benchmark_role not in _BENCHMARK_ROLES:
            raise ValidationError(f"conversation_plan.turn benchmark_role is unknown: {benchmark_role}")
        turns.append(
            {
                "turn_id": turn_id,
                "sequence_no": _require_int(obj.get("sequence_no"), "conversation_plan.turns.sequence_no", minimum=1),
                "session_id": session_id,
                "speaker_ref": speaker_ref,
                "topic_key": _require_string(obj.get("topic_key"), "conversation_plan.turns.topic_key"),
                "turn_purpose": _require_chinese_string(obj.get("turn_purpose"), "conversation_plan.turns.turn_purpose"),
                "references_previous_turns": _require_unique_strings(
                    obj.get("references_previous_turns") or [],
                    "conversation_plan.turns.references_previous_turns",
                ),
                "semantic_payload": _require_chinese_string(
                    obj.get("semantic_payload"),
                    "conversation_plan.turns.semantic_payload",
                ),
                "planned_message_text": _require_chinese_string(
                    obj.get("planned_message_text"),
                    "conversation_plan.turns.planned_message_text",
                ),
                "benchmark_role": benchmark_role,
                "memory_failure_mode": _require_string(
                    obj.get("memory_failure_mode"),
                    "conversation_plan.turns.memory_failure_mode",
                ),
                "memory_trap": _require_string(obj.get("memory_trap"), "conversation_plan.turns.memory_trap"),
                "expected_openclaw_memory_risk": _require_chinese_string(
                    obj.get("expected_openclaw_memory_risk"),
                    "conversation_plan.turns.expected_openclaw_memory_risk",
                ),
                "task_wiki_expected_handling": _require_chinese_string(
                    obj.get("task_wiki_expected_handling"),
                    "conversation_plan.turns.task_wiki_expected_handling",
                ),
                "state_field_hints": _require_unique_strings(
                    obj.get("state_field_hints") or [],
                    "conversation_plan.turns.state_field_hints",
                ),
                "probe_query_hints": _validate_probe_queries(
                    obj.get("probe_query_hints") or [],
                    "conversation_plan.turns.probe_query_hints",
                ),
            }
        )
    turns.sort(key=lambda row: (row["sequence_no"], row["turn_id"]))
    return {
        "case_id": _require_string(payload.get("case_id"), "conversation_plan.case_id"),
        "task_id": _require_string(payload.get("task_id"), "conversation_plan.task_id"),
        "sessions": sessions,
        "turns": turns,
    }


def validate_conversation_plan(payload: dict[str, Any], *, allowed_actor_refs: set[str] | None = None) -> dict[str, Any]:
    return validate_conversation_plan_v3(payload, allowed_actor_refs=allowed_actor_refs)


def validate_command_plan_v3(rows: list[dict[str, Any]], *, allowed_actor_refs: set[str] | None = None) -> list[dict[str, Any]]:
    normalized = []
    seen_step_ids: set[str] = set()
    for item in rows:
        obj = _require_dict(item, "command_plan[]")
        step_id = _require_string(obj.get("step_id"), "command_plan.step_id")
        if step_id in seen_step_ids:
            raise ValidationError(f"duplicate command_plan.step_id: {step_id}")
        seen_step_ids.add(step_id)
        action_type = _require_string(obj.get("action_type"), "command_plan.action_type")
        if action_type not in _ACTION_TYPES:
            raise ValidationError(f"command_plan.action_type is unsupported: {action_type}")
        speaker_ref = _optional_string(obj.get("speaker_ref"))
        if speaker_ref and allowed_actor_refs is not None and speaker_ref not in allowed_actor_refs:
            raise ValidationError(f"command_plan.speaker_ref not found in characters: {speaker_ref}")
        params = _require_dict(obj.get("params"), "command_plan.params")
        normalized.append(
            {
                "case_id": _require_string(obj.get("case_id"), "command_plan.case_id"),
                "step_id": step_id,
                "sequence_no": _require_int(obj.get("sequence_no"), "command_plan.sequence_no", minimum=1),
                "action_type": action_type,
                "session_id": _require_string(obj.get("session_id"), "command_plan.session_id"),
                "source_type": _require_string(obj.get("source_type"), "command_plan.source_type"),
                "source_ref": _require_string(obj.get("source_ref"), "command_plan.source_ref"),
                "chat_ref": _require_string(obj.get("chat_ref"), "command_plan.chat_ref"),
                "topic_key": _require_string(obj.get("topic_key"), "command_plan.topic_key"),
                "turn_id": _optional_string(obj.get("turn_id")) or None,
                "turn_purpose": _require_chinese_string(obj.get("turn_purpose"), "command_plan.turn_purpose"),
                "speaker_role": _optional_chinese_string(obj.get("speaker_role"), "command_plan.speaker_role"),
                "speaker_ref": speaker_ref,
                "depends_on_step_ids": _require_unique_strings(
                    obj.get("depends_on_step_ids") or [],
                    "command_plan.depends_on_step_ids",
                ),
                "benchmark_role": _optional_string(obj.get("benchmark_role")),
                "memory_failure_mode": _optional_string(obj.get("memory_failure_mode")),
                "memory_trap": _optional_string(obj.get("memory_trap")),
                "expected_openclaw_memory_risk": _optional_chinese_string(
                    obj.get("expected_openclaw_memory_risk"),
                    "command_plan.expected_openclaw_memory_risk",
                ),
                "task_wiki_expected_handling": _optional_chinese_string(
                    obj.get("task_wiki_expected_handling"),
                    "command_plan.task_wiki_expected_handling",
                ),
                "state_field_hints": _require_unique_strings(
                    obj.get("state_field_hints") or [],
                    "command_plan.state_field_hints",
                ),
                "semantic_payload": _optional_chinese_string(obj.get("semantic_payload"), "command_plan.semantic_payload"),
                "planned_message_text": _optional_chinese_string(
                    obj.get("planned_message_text"),
                    "command_plan.planned_message_text",
                ),
                "output_ref": _optional_string(obj.get("output_ref")) or None,
                "params": params,
                "lark_cli_command": _optional_string(obj.get("lark_cli_command")),
            }
        )
    normalized.sort(key=lambda row: (row["sequence_no"], row["step_id"]))
    return normalized


def validate_command_plan(rows: list[dict[str, Any]], *, allowed_actor_refs: set[str] | None = None) -> list[dict[str, Any]]:
    return validate_command_plan_v3(rows, allowed_actor_refs=allowed_actor_refs)


def validate_execution_plan(payload: dict[str, Any], *, allowed_sender_refs: set[str] | None = None) -> dict[str, Any]:
    actions = []
    seen_action_ids: set[str] = set()
    for item in _require_list(payload.get("actions"), "execution_plan.actions"):
        obj = _require_dict(item, "execution_plan.actions[]")
        action_id = _require_string(obj.get("action_id"), "execution_plan.actions.action_id")
        if action_id in seen_action_ids:
            raise ValidationError(f"duplicate execution_plan.action_id: {action_id}")
        seen_action_ids.add(action_id)
        action_type = _require_string(obj.get("action_type"), "execution_plan.actions.action_type")
        if action_type not in _ACTION_TYPES:
            raise ValidationError(f"execution_plan.actions.action_type is unsupported: {action_type}")
        params = _require_dict(obj.get("params"), "execution_plan.actions.params")
        sender_ref = _optional_string(params.get("sender_ref"))
        if sender_ref and allowed_sender_refs is not None and sender_ref not in allowed_sender_refs:
            raise ValidationError(f"execution_plan.actions.params.sender_ref not found in characters: {sender_ref}")
        actions.append(
            {
                "action_id": action_id,
                "action_type": action_type,
                "depends_on": _require_unique_strings(
                    obj.get("depends_on") or [],
                    "execution_plan.actions.depends_on",
                ),
                "params": params,
                "output_ref": _optional_string(obj.get("output_ref")) or None,
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "execution_plan.case_id"),
        "operator_identity": _require_string(
            payload.get("operator_identity") or "user",
            "execution_plan.operator_identity",
        ),
        "delivery_mode": _require_string(
            payload.get("delivery_mode") or "prefixed_single_operator",
            "execution_plan.delivery_mode",
        ),
        "actions": actions,
    }


def validate_execution_result(payload: dict[str, Any]) -> dict[str, Any]:
    action_status = []
    for item in _require_list(payload.get("action_status") or [], "execution_result.action_status"):
        obj = _require_dict(item, "execution_result.action_status[]")
        action_status.append(
            {
                "action_id": _require_string(obj.get("action_id"), "execution_result.action_status.action_id"),
                "status": _require_string(obj.get("status"), "execution_result.action_status.status"),
                "command": list(obj.get("command") or []),
                "stdout": obj.get("stdout", {}),
                "stderr": _optional_string(obj.get("stderr")),
                "returncode": int(obj.get("returncode") or 0),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "execution_result.case_id"),
        "status": _require_string(payload.get("status"), "execution_result.status"),
        "operator_identity": _require_string(
            payload.get("operator_identity") or "user",
            "execution_result.operator_identity",
        ),
        "delivery_mode": _require_string(
            payload.get("delivery_mode") or "prefixed_single_operator",
            "execution_result.delivery_mode",
        ),
        "created_resources": _require_dict(payload.get("created_resources") or {}, "execution_result.created_resources"),
        "thread_id_to_chat_id": _require_dict(
            payload.get("thread_id_to_chat_id") or {},
            "execution_result.thread_id_to_chat_id",
        ),
        "action_status": action_status,
        "preflight": _require_dict(payload.get("preflight") or {}, "execution_result.preflight"),
    }


def validate_collected_messages_v3(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for item in rows:
        obj = _require_dict(item, "collected_messages[]")
        normalized.append(
            {
                "turn_id": _require_string(obj.get("turn_id"), "collected_messages.turn_id"),
                "sequence_no": _require_int(obj.get("sequence_no"), "collected_messages.sequence_no", minimum=1),
                "session_id": _require_string(obj.get("session_id"), "collected_messages.session_id"),
                "source_type": _require_string(obj.get("source_type"), "collected_messages.source_type"),
                "source_ref": _require_string(obj.get("source_ref"), "collected_messages.source_ref"),
                "chat_ref": _require_string(obj.get("chat_ref"), "collected_messages.chat_ref"),
                "speaker_ref": _require_string(obj.get("speaker_ref"), "collected_messages.speaker_ref"),
                "topic_key": _require_string(obj.get("topic_key"), "collected_messages.topic_key"),
                "turn_purpose": _require_chinese_string(obj.get("turn_purpose"), "collected_messages.turn_purpose"),
                "semantic_payload": _optional_chinese_string(
                    obj.get("semantic_payload"),
                    "collected_messages.semantic_payload",
                ),
                "content_text": _require_chinese_string(obj.get("content_text"), "collected_messages.content_text"),
                "message_id": _require_string(obj.get("message_id"), "collected_messages.message_id"),
                "collect_source": _require_string(obj.get("collect_source"), "collected_messages.collect_source"),
                "benchmark_role": _require_string(obj.get("benchmark_role"), "collected_messages.benchmark_role"),
                "memory_failure_mode": _require_string(
                    obj.get("memory_failure_mode"),
                    "collected_messages.memory_failure_mode",
                ),
                "memory_trap": _require_string(obj.get("memory_trap"), "collected_messages.memory_trap"),
                "state_field_hints": _require_unique_strings(
                    obj.get("state_field_hints") or [],
                    "collected_messages.state_field_hints",
                ),
                "probe_query_hints": _validate_probe_queries(
                    obj.get("probe_query_hints") or [],
                    "collected_messages.probe_query_hints",
                ),
                "actual_sender": _require_dict(obj.get("actual_sender") or {}, "collected_messages.actual_sender"),
                "simulated_speaker": _require_dict(
                    obj.get("simulated_speaker") or {},
                    "collected_messages.simulated_speaker",
                ),
                "normalized_actor_id": _require_string(
                    obj.get("normalized_actor_id"),
                    "collected_messages.normalized_actor_id",
                ),
                "speaker_resolution_mode": _require_string(
                    obj.get("speaker_resolution_mode"),
                    "collected_messages.speaker_resolution_mode",
                ),
                "prefix_speaker_hint": _require_dict(
                    obj.get("prefix_speaker_hint") or {},
                    "collected_messages.prefix_speaker_hint",
                ),
            }
        )
    normalized.sort(key=lambda row: (row["sequence_no"], row["turn_id"]))
    return normalized


def validate_collected_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return validate_collected_messages_v3(rows)


def validate_openclaw_message_ingress(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for item in rows:
        obj = _require_dict(item, "openclaw_message_ingress[]")
        normalized.append(
            {
                "ingress_id": _require_string(obj.get("ingress_id"), "openclaw_message_ingress.ingress_id"),
                "case_id": _require_string(obj.get("case_id"), "openclaw_message_ingress.case_id"),
                "message_id": _require_string(obj.get("message_id"), "openclaw_message_ingress.message_id"),
                "session_id": _require_string(obj.get("session_id"), "openclaw_message_ingress.session_id"),
                "source_session_ref": _require_string(
                    obj.get("source_session_ref"),
                    "openclaw_message_ingress.source_session_ref",
                ),
                "content_text": _require_chinese_string(obj.get("content_text"), "openclaw_message_ingress.content_text"),
                "normalized_actor_id": _require_string(
                    obj.get("normalized_actor_id"),
                    "openclaw_message_ingress.normalized_actor_id",
                ),
                "benchmark_role": _require_string(obj.get("benchmark_role"), "openclaw_message_ingress.benchmark_role"),
                "memory_failure_mode": _require_string(
                    obj.get("memory_failure_mode"),
                    "openclaw_message_ingress.memory_failure_mode",
                ),
                "memory_trap": _require_string(obj.get("memory_trap"), "openclaw_message_ingress.memory_trap"),
                "captured_at": _require_string(obj.get("captured_at"), "openclaw_message_ingress.captured_at"),
            }
        )
    return normalized


def validate_pre_annotation_validation_report(payload: dict[str, Any]) -> dict[str, Any]:
    traps = []
    for item in _require_list(payload.get("traps"), "pre_annotation_validation_report.traps"):
        obj = _require_dict(item, "pre_annotation_validation_report.traps[]")
        traps.append(
            {
                "trap_id": _require_string(obj.get("trap_id"), "pre_annotation_validation_report.traps.trap_id"),
                "failure_mode": _require_string(
                    obj.get("failure_mode"),
                    "pre_annotation_validation_report.traps.failure_mode",
                ),
                "landed": _require_bool(obj.get("landed"), "pre_annotation_validation_report.traps.landed"),
                "matched_roles": _require_unique_strings(
                    obj.get("matched_roles") or [],
                    "pre_annotation_validation_report.traps.matched_roles",
                ),
                "missing_roles": _require_unique_strings(
                    obj.get("missing_roles") or [],
                    "pre_annotation_validation_report.traps.missing_roles",
                ),
                "evidence_messages_count": _require_int(
                    obj.get("evidence_messages_count"),
                    "pre_annotation_validation_report.traps.evidence_messages_count",
                    minimum=0,
                ),
                "required_state_fields": _require_unique_strings(
                    obj.get("required_state_fields") or [],
                    "pre_annotation_validation_report.traps.required_state_fields",
                ),
                "observed_state_fields": _require_unique_strings(
                    obj.get("observed_state_fields") or [],
                    "pre_annotation_validation_report.traps.observed_state_fields",
                ),
                "missing_state_fields": _require_unique_strings(
                    obj.get("missing_state_fields") or [],
                    "pre_annotation_validation_report.traps.missing_state_fields",
                ),
                "probe_query_ready": _require_bool(
                    obj.get("probe_query_ready"),
                    "pre_annotation_validation_report.traps.probe_query_ready",
                ),
                "notes": _require_unique_strings(
                    obj.get("notes") or [],
                    "pre_annotation_validation_report.traps.notes",
                ),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "pre_annotation_validation_report.case_id"),
        "status": _require_string(payload.get("status"), "pre_annotation_validation_report.status"),
        "required_failure_modes_observed": _require_failure_modes(
            payload.get("required_failure_modes_observed"),
            "pre_annotation_validation_report.required_failure_modes_observed",
        ),
        "missing_failure_modes": _require_failure_modes(
            payload.get("missing_failure_modes") or [],
            "pre_annotation_validation_report.missing_failure_modes",
        ),
        "traps": traps,
    }


_ANNOTATION_KINDS = {"positive_event", "negative_no_event", "review_event"}
_EXPECTED_VERDICTS = {"verified", "needs_review", "rejected", "no_event"}
_ALIGNMENT_TYPES = {"exact", "partial", "unmatched", "over_split", "over_merged"}
_PHASE_NAMES = {
    "spec-generation",
    "memory-failure-blueprint",
    "task-actor-layout",
    "case-world",
    "characters",
    "state-trajectory",
    "coverage-spec",
    "story-beats",
    "conversation-plan",
    "command-plan",
    "execute",
    "collect",
    "pre-annotation-validate",
    "annotation-gold",
    "build-checks",
    "gold-validate",
    "replay-runtime",
    "replay-eval",
    "memory-md-baseline",
    "value-eval",
    "report",
}


def _require_choice(value: Any, field: str, *, choices: set[str]) -> str:
    item = _require_string(value, field)
    if item not in choices:
        raise ValidationError(f"{field} must be one of: {', '.join(sorted(choices))}")
    return item


def _require_score(value: Any, field: str) -> float:
    return _require_float(value, field, minimum=0.0)


def _validate_metric_bundle(payload: Any, field: str) -> dict[str, Any]:
    obj = _require_dict(payload, field)
    overall = _require_dict(obj.get("overall"), f"{field}.overall")
    by_failure_mode_raw = _require_dict(obj.get("by_failure_mode"), f"{field}.by_failure_mode")
    by_failure_mode = {
        _require_string(mode, f"{field}.by_failure_mode.key"): _require_dict(
            metrics,
            f"{field}.by_failure_mode[{mode}]",
        )
        for mode, metrics in by_failure_mode_raw.items()
    }
    bundle = {
        "case_id": _require_string(obj.get("case_id"), f"{field}.case_id"),
        "overall": overall,
        "by_failure_mode": by_failure_mode,
    }
    if "by_query_family" in obj:
        query_family = _require_dict(obj.get("by_query_family"), f"{field}.by_query_family")
        bundle["by_query_family"] = {
            _require_string(key, f"{field}.by_query_family.key"): _require_dict(
                value,
                f"{field}.by_query_family[{key}]",
            )
            for key, value in query_family.items()
        }
    return bundle


def validate_case_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    completed_stages = _require_unique_strings(payload.get("completed_stages") or [], "case_manifest.completed_stages")
    for stage in completed_stages:
        if stage not in _PHASE_NAMES:
            raise ValidationError(f"case_manifest.completed_stages contains unknown stage: {stage}")
    artifacts_raw = _require_dict(payload.get("artifacts") or {}, "case_manifest.artifacts")
    artifacts = {
        _require_string(key, "case_manifest.artifacts.key"): _require_string(
            value,
            f"case_manifest.artifacts[{key}]",
        )
        for key, value in artifacts_raw.items()
    }
    return {
        "case_id": _require_string(payload.get("case_id"), "case_manifest.case_id"),
        "dataset_version": _require_string(payload.get("dataset_version"), "case_manifest.dataset_version"),
        "builder_version": _require_string(payload.get("builder_version"), "case_manifest.builder_version"),
        "case_dir": _require_string(payload.get("case_dir"), "case_manifest.case_dir"),
        "completed_stages": completed_stages,
        "artifacts": artifacts,
        "updated_at": _require_string(payload.get("updated_at"), "case_manifest.updated_at"),
    }


def validate_event_annotations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    seen_ids: set[str] = set()
    for item in rows:
        obj = _require_dict(item, "event_annotations[]")
        annotation_id = _require_string(obj.get("annotation_id"), "event_annotations.annotation_id")
        if annotation_id in seen_ids:
            raise ValidationError(f"duplicate event_annotations.annotation_id: {annotation_id}")
        seen_ids.add(annotation_id)
        annotation_kind = _require_choice(
            obj.get("annotation_kind"),
            "event_annotations.annotation_kind",
            choices=_ANNOTATION_KINDS,
        )
        expected_verdict = _require_choice(
            obj.get("expected_verdict"),
            "event_annotations.expected_verdict",
            choices=_EXPECTED_VERDICTS,
        )
        normalized.append(
            {
                "annotation_id": annotation_id,
                "annotation_kind": annotation_kind,
                "expected_verdict": expected_verdict,
                "failure_mode": _require_string(obj.get("failure_mode"), "event_annotations.failure_mode"),
                "source_trap_id": _require_string(obj.get("source_trap_id"), "event_annotations.source_trap_id"),
                "benchmark_role": _require_string(obj.get("benchmark_role"), "event_annotations.benchmark_role"),
                "topic_key": _require_string(obj.get("topic_key"), "event_annotations.topic_key"),
                "evidence_message_id": _require_string(
                    obj.get("evidence_message_id"),
                    "event_annotations.evidence_message_id",
                ),
                "evidence_turn_id": _require_string(obj.get("evidence_turn_id"), "event_annotations.evidence_turn_id"),
                "evidence_quote": _require_chinese_string(obj.get("evidence_quote"), "event_annotations.evidence_quote"),
                "claim_text": _require_chinese_string(obj.get("claim_text"), "event_annotations.claim_text"),
                "event_type_hint": _require_string(obj.get("event_type_hint"), "event_annotations.event_type_hint"),
                "state_field": _optional_string(obj.get("state_field")),
                "task_scope": _require_string(obj.get("task_scope") or "target_task", "event_annotations.task_scope"),
                "forbidden_for_current_task": _require_bool(
                    obj.get("forbidden_for_current_task") if "forbidden_for_current_task" in obj else False,
                    "event_annotations.forbidden_for_current_task",
                ),
            }
        )
    return normalized


def validate_block_annotations(payload: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for item in _require_list(payload.get("blocks"), "block_annotations.blocks"):
        obj = _require_dict(item, "block_annotations.blocks[]")
        current_state = []
        for raw_state in _require_list(obj.get("current_state") or [], "block_annotations.blocks.current_state"):
            state_obj = _require_dict(raw_state, "block_annotations.blocks.current_state[]")
            current_state.append(
                {
                    "state_field": _require_string(state_obj.get("state_field"), "block_annotations.current_state.state_field"),
                    "value": _require_string(state_obj.get("value"), "block_annotations.current_state.value"),
                    "supporting_event_annotation_ids": _require_unique_strings(
                        state_obj.get("supporting_event_annotation_ids") or [],
                        "block_annotations.current_state.supporting_event_annotation_ids",
                    ),
                    "stale_event_annotation_ids": _require_unique_strings(
                        state_obj.get("stale_event_annotation_ids") or [],
                        "block_annotations.current_state.stale_event_annotation_ids",
                    ),
                }
            )
        blocks.append(
            {
                "block_annotation_id": _require_string(
                    obj.get("block_annotation_id"),
                    "block_annotations.blocks.block_annotation_id",
                ),
                "source_trap_id": _require_string(obj.get("source_trap_id"), "block_annotations.blocks.source_trap_id"),
                "failure_mode": _require_string(obj.get("failure_mode"), "block_annotations.blocks.failure_mode"),
                "topic_key": _require_string(obj.get("topic_key"), "block_annotations.blocks.topic_key"),
                "topic_title": _require_chinese_string(obj.get("topic_title"), "block_annotations.blocks.topic_title"),
                "gold_event_annotation_ids": _require_unique_strings(
                    obj.get("gold_event_annotation_ids"),
                    "block_annotations.blocks.gold_event_annotation_ids",
                ),
                "current_state": current_state,
                "distinguishes_historical_from_current": _require_bool(
                    obj.get("distinguishes_historical_from_current"),
                    "block_annotations.blocks.distinguishes_historical_from_current",
                ),
                "expected_projector_focus": _require_string(
                    obj.get("expected_projector_focus"),
                    "block_annotations.blocks.expected_projector_focus",
                ),
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "block_annotations.case_id"),
        "task_id": _require_string(payload.get("task_id"), "block_annotations.task_id"),
        "blocks": blocks,
    }


def validate_query_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    queries = []
    for item in _require_list(payload.get("queries"), "query_benchmark.queries"):
        obj = _require_dict(item, "query_benchmark.queries[]")
        expected_current_state = []
        for raw_state in _require_list(
            obj.get("expected_current_state") or [],
            "query_benchmark.queries.expected_current_state",
        ):
            state_obj = _require_dict(raw_state, "query_benchmark.queries.expected_current_state[]")
            expected_current_state.append(
                {
                    "state_field": _require_string(
                        state_obj.get("state_field"),
                        "query_benchmark.expected_current_state.state_field",
                    ),
                    "value": _require_string(
                        state_obj.get("value"),
                        "query_benchmark.expected_current_state.value",
                    ),
                }
            )
        citation_expectation = _require_dict(
            obj.get("citation_expectation") or {},
            "query_benchmark.queries.citation_expectation",
        )
        queries.append(
            {
                "query_id": _require_string(obj.get("query_id"), "query_benchmark.queries.query_id"),
                "query_family": _require_string(obj.get("query_family"), "query_benchmark.queries.query_family"),
                "query_text": _require_chinese_string(obj.get("query_text"), "query_benchmark.queries.query_text"),
                "source_trap_id": _require_string(obj.get("source_trap_id"), "query_benchmark.queries.source_trap_id"),
                "failure_mode": _require_string(obj.get("failure_mode"), "query_benchmark.queries.failure_mode"),
                "expected_openclaw_failure": _require_chinese_string(
                    obj.get("expected_openclaw_failure"),
                    "query_benchmark.queries.expected_openclaw_failure",
                ),
                "expected_answer_points": [
                    _require_chinese_string(point, "query_benchmark.queries.expected_answer_points[]")
                    for point in _require_list(
                        obj.get("expected_answer_points"),
                        "query_benchmark.queries.expected_answer_points",
                    )
                ],
                "forbidden_claims": [
                    _require_chinese_string(point, "query_benchmark.queries.forbidden_claims[]")
                    for point in _require_list(
                        obj.get("forbidden_claims") or [],
                        "query_benchmark.queries.forbidden_claims",
                    )
                ],
                "required_event_annotation_ids": _require_unique_strings(
                    obj.get("required_event_annotation_ids") or [],
                    "query_benchmark.queries.required_event_annotation_ids",
                ),
                "required_block_topics": _require_unique_strings(
                    obj.get("required_block_topics") or [],
                    "query_benchmark.queries.required_block_topics",
                ),
                "expected_current_state": expected_current_state,
                "stale_values": _require_unique_strings(
                    obj.get("stale_values") or [],
                    "query_benchmark.queries.stale_values",
                ),
                "citation_expectation": {
                    "min_citations": _require_int(
                        citation_expectation.get("min_citations") or 0,
                        "query_benchmark.queries.citation_expectation.min_citations",
                        minimum=0,
                    ),
                    "must_cite_message_ids": _require_unique_strings(
                        citation_expectation.get("must_cite_message_ids") or [],
                        "query_benchmark.queries.citation_expectation.must_cite_message_ids",
                    ),
                },
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "query_benchmark.case_id"),
        "task_id": _require_string(payload.get("task_id"), "query_benchmark.task_id"),
        "queries": queries,
    }


def validate_event_alignment(payload: dict[str, Any]) -> dict[str, Any]:
    alignments = []
    for item in _require_list(payload.get("alignments"), "event_alignment.alignments"):
        obj = _require_dict(item, "event_alignment.alignments[]")
        alignments.append(
            {
                "annotation_id": _require_string(obj.get("annotation_id"), "event_alignment.alignments.annotation_id"),
                "prediction_event_id": _optional_string(obj.get("prediction_event_id")) or None,
                "alignment_type": _require_choice(
                    obj.get("alignment_type"),
                    "event_alignment.alignments.alignment_type",
                    choices=_ALIGNMENT_TYPES,
                ),
                "score": _require_score(obj.get("score") or 0.0, "event_alignment.alignments.score"),
                "failure_mode": _require_string(obj.get("failure_mode"), "event_alignment.alignments.failure_mode"),
                "expected_verdict": _require_choice(
                    obj.get("expected_verdict"),
                    "event_alignment.alignments.expected_verdict",
                    choices=_EXPECTED_VERDICTS,
                ),
                "prediction_verdict": _optional_string(obj.get("prediction_verdict")) or None,
            }
        )
    return {
        "case_id": _require_string(payload.get("case_id"), "event_alignment.case_id"),
        "target_prediction_source": _require_string(
            payload.get("target_prediction_source"),
            "event_alignment.target_prediction_source",
        ),
        "alignments": alignments,
        "summary": _require_dict(payload.get("summary"), "event_alignment.summary"),
    }


def validate_event_eval(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_metric_bundle(payload, "event_eval")


def validate_block_eval(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = _validate_metric_bundle(payload, "block_eval")
    bundle["block_eval_on_all_gold_events"] = _require_dict(
        payload.get("block_eval_on_all_gold_events"),
        "block_eval.block_eval_on_all_gold_events",
    )
    bundle["block_eval_on_aligned_events_only"] = _require_dict(
        payload.get("block_eval_on_aligned_events_only"),
        "block_eval.block_eval_on_aligned_events_only",
    )
    return bundle


def validate_qa_eval(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = _validate_metric_bundle(payload, "qa_eval")
    bundle["queries"] = _require_list(payload.get("queries"), "qa_eval.queries")
    bundle["judge_mode"] = _require_string(payload.get("judge_mode"), "qa_eval.judge_mode")
    return bundle


def validate_value_eval(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = _validate_metric_bundle(payload, "value_eval")
    bundle["systems"] = _require_dict(payload.get("systems"), "value_eval.systems")
    bundle["baseline_mode"] = _require_string(payload.get("baseline_mode"), "value_eval.baseline_mode")
    return bundle


def validate_overall_eval(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": _require_string(payload.get("case_id"), "overall_eval.case_id"),
        "remembered_assessment": _require_dict(
            payload.get("remembered_assessment"),
            "overall_eval.remembered_assessment",
        ),
        "value_assessment": _require_dict(payload.get("value_assessment"), "overall_eval.value_assessment"),
        "artifacts": _require_dict(payload.get("artifacts"), "overall_eval.artifacts"),
    }
