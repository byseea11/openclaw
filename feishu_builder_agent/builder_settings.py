from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SETTINGS_PATH = Path(__file__).resolve().parent / "builder_settings.yml"
FAILURE_MODES = [
    "personal_memory_pollution",
    "unverifiable_summary_claim",
    "static_memory_stale_state",
    "dependency_propagation_failure",
]


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _require_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be a non-empty string")
    return text


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if number < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return number


def _require_float(value: Any, field: str, *, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if number < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return number


def _require_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean")


def _require_failure_mode_list(value: Any, field: str) -> list[str]:
    items = []
    for raw in _require_list(value, field):
        item = _require_string(raw, f"{field}[]")
        if item not in FAILURE_MODES:
            raise ValueError(f"{field}[] contains unknown failure mode: {item}")
        if item not in items:
            items.append(item)
    return items


@lru_cache(maxsize=1)
def load_builder_settings() -> dict[str, Any]:
    payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    root = _require_dict(payload, "builder_settings")
    defaults_raw = _require_dict(root.get("defaults"), "builder_settings.defaults")
    difficulty_profiles_raw = _require_dict(root.get("difficulty_profiles"), "builder_settings.difficulty_profiles")
    v3_blueprint_raw = _require_dict(root.get("v3_blueprint"), "builder_settings.v3_blueprint")
    failure_mode_mix_raw = _require_dict(root.get("failure_mode_mix"), "builder_settings.failure_mode_mix")
    failure_mode_constraints_raw = _require_dict(
        root.get("failure_mode_constraints"),
        "builder_settings.failure_mode_constraints",
    )

    difficulty_profiles: dict[str, Any] = {}
    for difficulty, raw_profile in difficulty_profiles_raw.items():
        field = f"builder_settings.difficulty_profiles.{difficulty}"
        profile = _require_dict(raw_profile, field)
        difficulty_profiles[str(difficulty)] = {
            "department_count": _require_int(profile.get("department_count"), f"{field}.department_count", minimum=3),
            "character_count_min": _require_int(profile.get("character_count_min"), f"{field}.character_count_min", minimum=4),
            "character_count_max": _require_int(profile.get("character_count_max"), f"{field}.character_count_max", minimum=4),
            "selected_failure_modes_min": _require_int(
                profile.get("selected_failure_modes_min"),
                f"{field}.selected_failure_modes_min",
                minimum=1,
            ),
            "min_traps_per_case": _require_int(profile.get("min_traps_per_case"), f"{field}.min_traps_per_case", minimum=1),
            "require_cross_source_revision": _require_bool(
                profile.get("require_cross_source_revision"),
                f"{field}.require_cross_source_revision",
            ),
            "session_blueprint": [
                _require_string(item, f"{field}.session_blueprint[]")
                for item in _require_list(profile.get("session_blueprint"), f"{field}.session_blueprint")
            ],
        }

    default_difficulty = _require_string(
        defaults_raw.get("default_difficulty"),
        "builder_settings.defaults.default_difficulty",
    )
    if default_difficulty not in difficulty_profiles:
        raise ValueError(
            f"builder_settings.defaults.default_difficulty must be one of: {', '.join(sorted(difficulty_profiles))}"
        )

    failure_mode_mix: dict[str, float] = {}
    for failure_mode in FAILURE_MODES:
        failure_mode_mix[failure_mode] = _require_float(
            failure_mode_mix_raw.get(failure_mode),
            f"builder_settings.failure_mode_mix.{failure_mode}",
            minimum=0.0,
        )

    failure_mode_constraints: dict[str, Any] = {}
    for failure_mode in FAILURE_MODES:
        field = f"builder_settings.failure_mode_constraints.{failure_mode}"
        raw_constraint = _require_dict(failure_mode_constraints_raw.get(failure_mode), field)
        failure_mode_constraints[failure_mode] = {
            key: value for key, value in raw_constraint.items() if key != "required_benchmark_roles"
        }
        failure_mode_constraints[failure_mode]["required_benchmark_roles"] = [
            _require_string(item, f"{field}.required_benchmark_roles[]")
            for item in _require_list(raw_constraint.get("required_benchmark_roles"), f"{field}.required_benchmark_roles")
        ]

    normalized = {
        "defaults": {
            "default_difficulty": default_difficulty,
            "department_pool": [
                _require_string(item, "builder_settings.defaults.department_pool[]")
                for item in _require_list(defaults_raw.get("department_pool"), "builder_settings.defaults.department_pool")
            ],
            "comparison_target_default": _require_string(
                defaults_raw.get("comparison_target_default"),
                "builder_settings.defaults.comparison_target_default",
            ),
        },
        "v3_blueprint": {
            "comparison_target_default": _require_string(
                v3_blueprint_raw.get("comparison_target_default"),
                "builder_settings.v3_blueprint.comparison_target_default",
            ),
            "min_traps_per_case": _require_int(
                v3_blueprint_raw.get("min_traps_per_case"),
                "builder_settings.v3_blueprint.min_traps_per_case",
                minimum=1,
            ),
            "max_traps_per_case": _require_int(
                v3_blueprint_raw.get("max_traps_per_case"),
                "builder_settings.v3_blueprint.max_traps_per_case",
                minimum=1,
            ),
            "min_probe_queries_per_trap": _require_int(
                v3_blueprint_raw.get("min_probe_queries_per_trap"),
                "builder_settings.v3_blueprint.min_probe_queries_per_trap",
                minimum=1,
            ),
            "primary_failure_mode_required": _require_bool(
                v3_blueprint_raw.get("primary_failure_mode_required"),
                "builder_settings.v3_blueprint.primary_failure_mode_required",
            ),
        },
        "failure_mode_mix": failure_mode_mix,
        "failure_mode_constraints": failure_mode_constraints,
        "difficulty_profiles": difficulty_profiles,
    }
    if normalized["v3_blueprint"]["max_traps_per_case"] < normalized["v3_blueprint"]["min_traps_per_case"]:
        raise ValueError("builder_settings.v3_blueprint.max_traps_per_case must be >= min_traps_per_case")
    return normalized


def resolve_difficulty_settings(difficulty: str) -> dict[str, Any]:
    settings = load_builder_settings()
    profiles = settings["difficulty_profiles"]
    resolved = str(difficulty or "").strip() or settings["defaults"]["default_difficulty"]
    if resolved not in profiles:
        raise ValueError(f"unknown difficulty: {resolved}. expected one of: {', '.join(sorted(profiles))}")
    return dict(profiles[resolved])


def resolve_default_difficulty() -> str:
    return str(load_builder_settings()["defaults"]["default_difficulty"])
