from __future__ import annotations

from typing import Any

from .schemas import validate_actor_registry, validate_characters


def build_actor_registry(characters: dict[str, Any]) -> dict[str, Any]:
    validated = validate_characters(characters)
    return validate_actor_registry(
        {
            "case_id": validated["case_id"],
            "actors": [
                {
                    "person_id": item["person_id"],
                    "simulated_open_id": item["simulated_open_id"],
                    "name": item["name"],
                    "department": item["department"],
                    "role": item["role"],
                    "default_channels": item["default_channels"],
                }
                for item in validated["characters"]
            ],
        }
    )
