from __future__ import annotations

from typing import Any

from ..schemas import validate_conversation_plan_artifact


def build_conversation_plan_artifact(
    *,
    case_context: dict[str, Any],
    case_world_artifact: dict[str, Any],
    story_beats_artifact: dict[str, Any],
    story_plan: dict[str, Any],
) -> dict[str, Any]:
    beat_lookup = {beat["beat_id"]: beat for beat in story_beats_artifact["beats"]}
    turns: list[dict[str, Any]] = []
    for index, beat in enumerate(story_plan["message_beats"], start=1):
        beat_id = str(beat["beat_id"])
        if beat_id not in beat_lookup:
            raise ValueError(f"conversation turn references unknown beat_id: {beat_id}")
        turns.append(
            {
                "turn_id": f"turn_{index:03d}",
                "beat_id": beat_id,
                "sequence_no": index,
                "session_id": str(beat["session_id"]),
                "speaker_actor_id": str(beat["speaker_actor_id"]),
                "speaker": str(beat["speaker"]),
                "planned_message_text": str(beat["message_intent"]),
            }
        )
    return validate_conversation_plan_artifact(
        {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "task_id": case_context["task_id"],
            "sessions": list(case_world_artifact["source_sessions"]),
            "turns": turns,
        }
    )
