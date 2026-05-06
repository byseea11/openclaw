from __future__ import annotations

from typing import Any

from ..schemas import validate_story_beats_artifact


def _benchmark_role_for(family_id: str, beat: dict[str, Any]) -> str:
    family_linkage = str(beat.get("family_linkage") or "")
    purpose = str(beat.get("purpose") or "")
    if family_id == "anti_interference":
        if "scope_boundary" in family_linkage:
            return "target_fact_turn"
        if "shared_actor_noise" in family_linkage:
            return "shared_actor_turn"
        return "memory_pollution_turn"
    if family_id == "contradiction_update":
        if "initial_state" in family_linkage:
            return "stale_state_turn"
        if "historical_state" in family_linkage:
            return "supersession_turn"
        return "final_current_state_turn"
    if family_id == "evidence_dependency_reasoning":
        if "verified" in family_linkage:
            return "evidence_anchor_turn"
        if "hearsay" in family_linkage:
            return "hearsay_turn"
        if "ambiguous" in family_linkage:
            return "ambiguous_claim_turn"
        if "impact" in family_linkage:
            return "dependency_update_turn"
        if "summary" in purpose or "summary" in family_linkage:
            return "current_state_disambiguation_turn"
    return "context_only_turn"


def build_story_beats_artifact(
    *,
    case_context: dict[str, Any],
    case_world_artifact: dict[str, Any],
    story_plan: dict[str, Any],
) -> dict[str, Any]:
    allowed_session_ids = {item["session_id"] for item in case_world_artifact["source_sessions"]}
    beats: list[dict[str, str]] = []
    for beat in story_plan["message_beats"]:
        session_id = str(beat["session_id"])
        if session_id not in allowed_session_ids:
            raise ValueError(f"story beat references unknown session_id: {session_id}")
        beats.append(
            {
                "beat_id": str(beat["beat_id"]),
                "target_session_id": session_id,
                "benchmark_role": _benchmark_role_for(str(case_context["family_id"]), beat),
                "description": str(beat["message_intent"]),
            }
        )
    return validate_story_beats_artifact(
        {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "task_id": case_context["task_id"],
            "beats": beats,
        }
    )
