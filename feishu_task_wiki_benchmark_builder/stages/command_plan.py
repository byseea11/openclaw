from __future__ import annotations

from typing import Any

from ..schemas import validate_command_plan


def build_command_plan(*, story_plan: dict[str, Any]) -> list[dict[str, Any]]:
    actor_lookup = {actor["display_name"]: actor["actor_id"] for actor in story_plan["actors"]}
    rows = []
    for index, beat in enumerate(story_plan["message_beats"], start=1):
        rows.append(
            {
                "command_id": f"cmd_{index:03d}",
                "beat_id": beat["beat_id"],
                "actor_id": actor_lookup[beat["speaker"]],
                "session_id": beat["session_id"],
                "message_text": beat["message_intent"],
            }
        )
    return validate_command_plan(rows)
