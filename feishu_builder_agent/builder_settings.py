from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SETTINGS_PATH = Path(__file__).resolve().parent / "builder_settings.yml"


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    number = int(value)
    if number < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return number


def _require_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be a non-empty string")
    return text


@lru_cache(maxsize=1)
def load_builder_settings() -> dict[str, Any]:
    payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    root = _require_dict(payload, "builder_settings")
    difficulty_profiles = _require_dict(root.get("difficulty_profiles"), "builder_settings.difficulty_profiles")
    normalized_profiles: dict[str, Any] = {}
    for difficulty, raw_profile in difficulty_profiles.items():
        profile = _require_dict(raw_profile, f"builder_settings.difficulty_profiles.{difficulty}")
        normalized_profiles[str(difficulty)] = {
            "department_count": _require_int(profile.get("department_count"), f"{difficulty}.department_count", minimum=3),
            "topic_count": _require_int(profile.get("topic_count"), f"{difficulty}.topic_count", minimum=3),
            "character_count_min": _require_int(profile.get("character_count_min"), f"{difficulty}.character_count_min", minimum=4),
            "character_count_max": _require_int(profile.get("character_count_max"), f"{difficulty}.character_count_max", minimum=4),
            "session_blueprint": [str(item).strip() for item in _require_list(profile.get("session_blueprint"), f"{difficulty}.session_blueprint")],
            "complexity_profile": _require_dict(profile.get("complexity_profile"), f"{difficulty}.complexity_profile"),
        }
    defaults = _require_dict(root.get("defaults"), "builder_settings.defaults")
    default_difficulty = _require_string(
        defaults.get("default_difficulty") or "medium",
        "builder_settings.defaults.default_difficulty",
    )
    if default_difficulty not in normalized_profiles:
        raise ValueError(
            f"builder_settings.defaults.default_difficulty must be one of: {', '.join(sorted(normalized_profiles))}"
        )
    return {
        "defaults": {
            "default_difficulty": default_difficulty,
            "department_pool": [str(item).strip() for item in _require_list(defaults.get("department_pool"), "builder_settings.defaults.department_pool")],
        },
        "difficulty_profiles": normalized_profiles,
    }


def resolve_difficulty_settings(difficulty: str) -> dict[str, Any]:
    settings = load_builder_settings()
    profiles = settings["difficulty_profiles"]
    resolved = str(difficulty or "").strip() or settings["defaults"]["default_difficulty"]
    if resolved not in profiles:
        raise ValueError(f"unknown difficulty: {resolved}. expected one of: {', '.join(sorted(profiles))}")
    return dict(profiles[resolved])


def resolve_default_difficulty() -> str:
    settings = load_builder_settings()
    return str(settings["defaults"]["default_difficulty"])
