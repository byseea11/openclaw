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


def _validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
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
        require_cross_source_revision = profile_obj.get("require_cross_source_revision")
        if not isinstance(require_cross_source_revision, bool):
            raise BuilderSettingsError(
                f"builder_settings.difficulty_profiles.{difficulty}.require_cross_source_revision must be a boolean"
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

    return payload


@lru_cache(maxsize=1)
def load_builder_settings(path: str | Path | None = None) -> dict[str, Any]:
    settings_path = Path(path) if path is not None else BUILDER_SETTINGS_PATH
    payload = json.loads(read_text(settings_path))
    if not isinstance(payload, dict):
        raise BuilderSettingsError("builder_settings root must be an object")
    return _validate_settings(payload)


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
    if stage == "case-context":
        return {
            "must_reflect_output_fields": [
                "organization",
                "team",
                "scenario_summary",
                "required_case_structure",
            ],
            "must_reflect_department_topology": True,
            "recommended_session_count": difficulty_slots["recommended_session_count"],
            "session_semantics_from_skills": True,
            "family_semantics_from_skills": True,
        }
    if stage == "story-plan":
        return {
            "must_reflect_output_fields": [
                "actors",
                "task_actor_layout",
                "state_changes",
                "message_beats",
                "planned_probe_queries",
            ],
            "enforce_actor_count_range": True,
            "enforce_session_count_target": True,
            "enforce_family_numeric_minima": True,
            "recommended_session_count": difficulty_slots["recommended_session_count"],
            "session_semantics_from_skills": True,
            "family_semantics_from_skills": True,
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
        },
    }
    if family_id is not None:
        resolved["family_numeric_slots"] = _build_family_numeric_slots(family_id)
    elif stage == "case-context":
        resolved["family_numeric_slots_by_family"] = {
            item: _build_family_numeric_slots(item) for item in FORMAL_FAMILY_IDS
        }
    return resolved
