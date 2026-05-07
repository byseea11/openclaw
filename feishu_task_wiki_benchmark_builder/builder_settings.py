from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import BUILDER_SETTINGS_PATH, FORMAL_FAMILY_IDS
from .io import read_text


class BuilderSettingsError(ValueError):
    """Raised when builder settings are missing or malformed."""


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuilderSettingsError(f"{path} must be an object")
    return value


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int):
        raise BuilderSettingsError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise BuilderSettingsError(f"{path} must be >= {minimum}")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuilderSettingsError(f"{path} must be a non-empty string")
    return value


def _validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    default_difficulty = _require_string(
        payload.get("default_difficulty"),
        "builder_settings.default_difficulty",
    )
    difficulty_profiles = _require_dict(
        payload.get("difficulty_profiles"),
        "builder_settings.difficulty_profiles",
    )
    family_constraints = _require_dict(
        payload.get("family_constraints"),
        "builder_settings.family_constraints",
    )

    for difficulty, profile in difficulty_profiles.items():
        profile_obj = _require_dict(profile, f"builder_settings.difficulty_profiles.{difficulty}")
        _require_int(
            profile_obj.get("department_count"),
            f"builder_settings.difficulty_profiles.{difficulty}.department_count",
            minimum=1,
        )
        _require_int(
            profile_obj.get("character_count_min"),
            f"builder_settings.difficulty_profiles.{difficulty}.character_count_min",
            minimum=1,
        )
        _require_int(
            profile_obj.get("character_count_max"),
            f"builder_settings.difficulty_profiles.{difficulty}.character_count_max",
            minimum=1,
        )
        _require_int(
            profile_obj.get("recommended_actor_count"),
            f"builder_settings.difficulty_profiles.{difficulty}.recommended_actor_count",
            minimum=1,
        )
        _require_int(
            profile_obj.get("recommended_department_count"),
            f"builder_settings.difficulty_profiles.{difficulty}.recommended_department_count",
            minimum=1,
        )
        _require_int(
            profile_obj.get("recommended_session_count"),
            f"builder_settings.difficulty_profiles.{difficulty}.recommended_session_count",
            minimum=1,
        )
        total_turn_count_min = _require_int(
            profile_obj.get("total_turn_count_min"),
            f"builder_settings.difficulty_profiles.{difficulty}.total_turn_count_min",
            minimum=1,
        )
        total_turn_count_max = _require_int(
            profile_obj.get("total_turn_count_max"),
            f"builder_settings.difficulty_profiles.{difficulty}.total_turn_count_max",
            minimum=total_turn_count_min,
        )
        event_bearing_turn_count_min = _require_int(
            profile_obj.get("event_bearing_turn_count_min"),
            f"builder_settings.difficulty_profiles.{difficulty}.event_bearing_turn_count_min",
            minimum=1,
        )
        _require_int(
            profile_obj.get("event_bearing_turn_count_max"),
            f"builder_settings.difficulty_profiles.{difficulty}.event_bearing_turn_count_max",
            minimum=event_bearing_turn_count_min,
        )
        _require_int(
            profile_obj.get("context_noise_ack_turn_count_min"),
            f"builder_settings.difficulty_profiles.{difficulty}.context_noise_ack_turn_count_min",
            minimum=0,
        )
        if event_bearing_turn_count_min > total_turn_count_max:
            raise BuilderSettingsError(
                f"builder_settings.difficulty_profiles.{difficulty}.event_bearing_turn_count_min must be <= total_turn_count_max"
            )
        require_cross_source_revision = profile_obj.get("require_cross_source_revision")
        if not isinstance(require_cross_source_revision, bool):
            raise BuilderSettingsError(
                f"builder_settings.difficulty_profiles.{difficulty}.require_cross_source_revision must be a boolean"
            )

    if default_difficulty not in difficulty_profiles:
        raise BuilderSettingsError(
            "builder_settings.default_difficulty must reference an existing difficulty profile"
        )

    for family_id in FORMAL_FAMILY_IDS:
        constraint = _require_dict(
            family_constraints.get(family_id),
            f"builder_settings.family_constraints.{family_id}",
        )
        if family_id == "anti_interference":
            _require_int(
                constraint.get("min_interference_context_blocks"),
                "builder_settings.family_constraints.anti_interference.min_interference_context_blocks",
                minimum=1,
            )
            _require_int(
                constraint.get("min_shared_actors"),
                "builder_settings.family_constraints.anti_interference.min_shared_actors",
                minimum=1,
            )
        elif family_id == "contradiction_update":
            _require_int(
                constraint.get("min_state_tracks"),
                "builder_settings.family_constraints.contradiction_update.min_state_tracks",
                minimum=1,
            )
            _require_int(
                constraint.get("min_stale_states"),
                "builder_settings.family_constraints.contradiction_update.min_stale_states",
                minimum=1,
            )
        elif family_id == "evidence_dependency_reasoning":
            _require_int(
                constraint.get("min_dependency_hops"),
                "builder_settings.family_constraints.evidence_dependency_reasoning.min_dependency_hops",
                minimum=1,
            )
            _require_int(
                constraint.get("min_cross_source_updates"),
                "builder_settings.family_constraints.evidence_dependency_reasoning.min_cross_source_updates",
                minimum=0,
            )
        elif family_id == "private_info_in_official_file":
            _require_int(
                constraint.get("min_private_info_items"),
                "builder_settings.family_constraints.private_info_in_official_file.min_private_info_items",
                minimum=1,
            )
            _require_int(
                constraint.get("min_official_file_refs"),
                "builder_settings.family_constraints.private_info_in_official_file.min_official_file_refs",
                minimum=1,
            )
            _require_int(
                constraint.get("min_task_relevance_boundaries"),
                "builder_settings.family_constraints.private_info_in_official_file.min_task_relevance_boundaries",
                minimum=1,
            )

    return payload


@lru_cache(maxsize=1)
def load_builder_settings(path: str | Path | None = None) -> dict[str, Any]:
    settings_path = Path(path) if path is not None else BUILDER_SETTINGS_PATH
    payload = json.loads(read_text(settings_path))
    if not isinstance(payload, dict):
        raise BuilderSettingsError("builder_settings root must be an object")
    return _validate_settings(payload)


def resolve_default_difficulty() -> str:
    settings = load_builder_settings()
    return _require_string(
        settings.get("default_difficulty"),
        "builder_settings.default_difficulty",
    )


def resolve_difficulty_settings(difficulty: str) -> dict[str, Any]:
    settings = load_builder_settings()
    difficulty_profiles = settings["difficulty_profiles"]
    if difficulty not in difficulty_profiles:
        raise BuilderSettingsError(f"Unknown difficulty profile: {difficulty}")
    return _require_dict(
        difficulty_profiles[difficulty],
        f"builder_settings.difficulty_profiles.{difficulty}",
    )


def resolve_family_constraints(family_id: str) -> dict[str, Any]:
    settings = load_builder_settings()
    if family_id not in FORMAL_FAMILY_IDS:
        raise BuilderSettingsError(f"Unknown formal family_id: {family_id}")
    return _require_dict(
        settings["family_constraints"][family_id],
        f"builder_settings.family_constraints.{family_id}",
    )


def _build_stage_slots(stage: str, difficulty_slots: dict[str, Any]) -> dict[str, Any]:
    common = {
        "recommended_actor_count": difficulty_slots["recommended_actor_count"],
        "recommended_department_count": difficulty_slots["recommended_department_count"],
        "recommended_session_count": difficulty_slots["recommended_session_count"],
        "total_turn_count_min": difficulty_slots["total_turn_count_min"],
        "total_turn_count_max": difficulty_slots["total_turn_count_max"],
        "event_bearing_turn_count_min": difficulty_slots["event_bearing_turn_count_min"],
        "event_bearing_turn_count_max": difficulty_slots["event_bearing_turn_count_max"],
        "context_noise_ack_turn_count_min": difficulty_slots["context_noise_ack_turn_count_min"],
        "require_cross_source_revision": difficulty_slots["require_cross_source_revision"],
        "family_semantics_from_skills": True,
    }
    if stage == "spec-generation":
        return {
            **common,
            "must_define_control_fields": [
                "case_id",
                "task_id",
                "family_id",
                "difficulty",
                "seed",
                "comparison_target",
            ],
            "must_not_define_story": True,
        }
    if stage == "task-actor-layout":
        return {
            **common,
            "enforce_actor_count_target": True,
            "enforce_department_topology": True,
            "enforce_family_numeric_minima": True,
            "must_define": [
                "actor_roster",
                "context_blocks",
                "shared_actors",
                "actor_context_roles",
            ],
        }
    if stage == "case-world":
        return {
            **common,
            "must_reflect_department_topology": True,
            "must_define_source_sessions": True,
            "session_semantics_from_skills": True,
            "cross_source_required": difficulty_slots["require_cross_source_revision"],
        }
    if stage == "characters":
        return {
            **common,
            "character_count_min": difficulty_slots["character_count_min"],
            "character_count_max": difficulty_slots["character_count_max"],
            "preserve_actor_identity": True,
            "must_emit_actor_registry": True,
        }
    if stage == "state-trajectory":
        return {
            **common,
            "enforce_family_numeric_minima": True,
            "must_define_current_state": True,
            "must_define_historical_or_context_boundary": True,
            "must_support_dependency_impact": True,
        }
    if stage == "coverage-spec":
        return {
            **common,
            "must_cover": [
                "evidence",
                "state",
                "beat",
                "probe",
            ],
            "observed_data_landing_audit": True,
            "enforce_family_numeric_minima": True,
        }
    if stage == "story-beats":
        return {
            **common,
            "must_cover_benchmark_roles": True,
            "enforce_session_distribution_target": True,
            "must_not_write_full_turns": True,
        }
    if stage == "conversation-plan":
        return {
            **common,
            "must_realize_turns": True,
            "live_llm_full_transcript_owner": True,
            "forbid_template_expansion_as_formal_path": True,
            "all_turns_enter_openclaw_ingress": True,
            "beat_id_required_only_for_annotation_targets": True,
            "preserve_speaker_actor_refs": True,
            "preserve_session_refs": True,
            "preserve_beat_refs": True,
            "official_file_trace_supported": True,
            "private_info_trace_supported": True,
        }
    if stage == "command-plan":
        return {
            **common,
            "required_action_types": [
                "create_chat",
                "send_message",
                "reply_in_thread",
                "fetch_chat_messages",
                "fetch_thread_messages",
            ],
            "require_dependency_edges": True,
            "require_output_refs": True,
            "require_lark_cli_command_preview": True,
        }
    if stage == "execute":
        return {
            **common,
            "require_auth_preflight": True,
            "execute_dependency_graph": True,
            "capture_resource_ids": [
                "chat_id",
                "message_id",
                "thread_id",
            ],
            "record_stdout_stderr_returncode": True,
        }
    if stage == "collect":
        return {
            **common,
            "real_fetch_only": True,
            "required_fetch_actions": [
                "fetch_chat_messages",
                "fetch_thread_messages",
            ],
            "preserve_observed_data_traceability": True,
            "openclaw_ingress_contains_all_sent_messages": True,
        }
    if stage == "pre-annotation-validate":
        return {
            **common,
            "observed_data_based_landing_audit": True,
            "must_check": [
                "family_trap",
                "state_changes",
                "evidence_chain",
                "probe_support",
            ],
        }
    if stage == "semantic-gold":
        return {
            **common,
            "observed_messages_only": True,
            "must_cite_message_ids": True,
            "must_not_use_planned_only_text": True,
            "expected_outputs": [
                "expected_task_facts",
                "expected_event_semantics",
                "expected_query_answers",
            ],
        }
    raise BuilderSettingsError(f"Unsupported stage for prompt slots: {stage}")


def _build_difficulty_slots(difficulty: str) -> dict[str, Any]:
    profile = resolve_difficulty_settings(difficulty)
    return {
        "difficulty": difficulty,
        "department_count": profile["department_count"],
        "character_count_min": profile["character_count_min"],
        "character_count_max": profile["character_count_max"],
        "recommended_actor_count": profile["recommended_actor_count"],
        "recommended_department_count": profile["recommended_department_count"],
        "recommended_session_count": profile["recommended_session_count"],
        "total_turn_count_min": profile["total_turn_count_min"],
        "total_turn_count_max": profile["total_turn_count_max"],
        "event_bearing_turn_count_min": profile["event_bearing_turn_count_min"],
        "event_bearing_turn_count_max": profile["event_bearing_turn_count_max"],
        "context_noise_ack_turn_count_min": profile["context_noise_ack_turn_count_min"],
        "require_cross_source_revision": profile["require_cross_source_revision"],
    }


def _build_family_numeric_slots(family_id: str) -> dict[str, Any]:
    family_numeric_slots = dict(resolve_family_constraints(family_id))
    family_numeric_slots["family_id"] = family_id
    return family_numeric_slots


def resolve_prompt_slots(
    *,
    stage: str,
    difficulty: str,
    family_id: str | None = None,
) -> dict[str, Any]:
    difficulty_slots = _build_difficulty_slots(difficulty)
    resolved: dict[str, Any] = {
        "difficulty_slots": difficulty_slots,
        "stage_slots": _build_stage_slots(stage, difficulty_slots),
        "example_targets": {
            "recommended_actor_count": difficulty_slots["recommended_actor_count"],
            "recommended_department_count": difficulty_slots["recommended_department_count"],
            "recommended_session_count": difficulty_slots["recommended_session_count"],
            "total_turn_count_min": difficulty_slots["total_turn_count_min"],
            "total_turn_count_max": difficulty_slots["total_turn_count_max"],
            "event_bearing_turn_count_min": difficulty_slots["event_bearing_turn_count_min"],
            "event_bearing_turn_count_max": difficulty_slots["event_bearing_turn_count_max"],
        },
    }
    if family_id is not None:
        resolved["family_numeric_slots"] = _build_family_numeric_slots(family_id)
    return resolved
