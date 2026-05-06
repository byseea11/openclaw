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


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise BuilderSettingsError(f"{path} must be a list")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuilderSettingsError(f"{path} must be a non-empty string")
    return value


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int):
        raise BuilderSettingsError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise BuilderSettingsError(f"{path} must be >= {minimum}")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise BuilderSettingsError(f"{path} must be a boolean")
    return value


def _validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = _require_dict(payload.get("defaults"), "builder_settings.defaults")
    difficulty_profiles = _require_dict(
        payload.get("difficulty_profiles"),
        "builder_settings.difficulty_profiles",
    )
    family_constraints = _require_dict(
        payload.get("family_constraints"),
        "builder_settings.family_constraints",
    )
    topology_defaults = _require_dict(
        payload.get("topology_defaults"),
        "builder_settings.topology_defaults",
    )

    _require_string(defaults.get("default_difficulty"), "builder_settings.defaults.default_difficulty")
    _require_string(
        defaults.get("comparison_target_default"),
        "builder_settings.defaults.comparison_target_default",
    )
    for index, item in enumerate(
        _require_list(defaults.get("department_pool"), "builder_settings.defaults.department_pool"),
        start=1,
    ):
        _require_string(item, f"builder_settings.defaults.department_pool[{index}]")

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
        _require_bool(
            profile_obj.get("require_cross_source_revision"),
            f"builder_settings.difficulty_profiles.{difficulty}.require_cross_source_revision",
        )
        for index, session in enumerate(
            _require_list(
                profile_obj.get("session_blueprint"),
                f"builder_settings.difficulty_profiles.{difficulty}.session_blueprint",
            ),
            start=1,
        ):
            _require_string(
                session,
                f"builder_settings.difficulty_profiles.{difficulty}.session_blueprint[{index}]",
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
            for index, item in enumerate(
                _require_list(
                    constraint.get("required_noise_types"),
                    "builder_settings.family_constraints.anti_interference.required_noise_types",
                ),
                start=1,
            ):
                _require_string(
                    item,
                    f"builder_settings.family_constraints.anti_interference.required_noise_types[{index}]",
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
            for index, item in enumerate(
                _require_list(
                    constraint.get("required_supersession_clues"),
                    "builder_settings.family_constraints.contradiction_update.required_supersession_clues",
                ),
                start=1,
            ):
                _require_string(
                    item,
                    f"builder_settings.family_constraints.contradiction_update.required_supersession_clues[{index}]",
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
            for index, item in enumerate(
                _require_list(
                    constraint.get("required_evidence_roles"),
                    "builder_settings.family_constraints.evidence_dependency_reasoning.required_evidence_roles",
                ),
                start=1,
            ):
                _require_string(
                    item,
                    f"builder_settings.family_constraints.evidence_dependency_reasoning.required_evidence_roles[{index}]",
                )

    for key in ("shared_actor_slot_suggestions", "external_context_types", "lateral_session_types"):
        for index, item in enumerate(
            _require_list(topology_defaults.get(key), f"builder_settings.topology_defaults.{key}"),
            start=1,
        ):
            _require_string(item, f"builder_settings.topology_defaults.{key}[{index}]")

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


def resolve_default_difficulty() -> str:
    settings = load_builder_settings()
    defaults = _require_dict(settings["defaults"], "builder_settings.defaults")
    difficulty = _require_string(
        defaults.get("default_difficulty"),
        "builder_settings.defaults.default_difficulty",
    )
    resolve_difficulty_settings(difficulty)
    return difficulty


def resolve_family_constraints(family_id: str) -> dict[str, Any]:
    settings = load_builder_settings()
    if family_id not in FORMAL_FAMILY_IDS:
        raise BuilderSettingsError(f"Unknown formal family_id: {family_id}")
    return _require_dict(
        settings["family_constraints"][family_id],
        f"builder_settings.family_constraints.{family_id}",
    )


def resolve_topology_defaults() -> dict[str, Any]:
    settings = load_builder_settings()
    return _require_dict(settings["topology_defaults"], "builder_settings.topology_defaults")
