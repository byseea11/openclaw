from __future__ import annotations

from typing import Any

from .schemas import validate_conversation_plan, validate_target_state


def generate_target_state(conversation_plan: dict[str, Any]) -> dict[str, Any]:
    plan = validate_conversation_plan(conversation_plan)
    latest_claim_by_topic_slot: dict[tuple[str, str], str] = {}
    for turn in plan["turns"]:
        for event_type in turn["supports_event_types"]:
            slot = event_type.replace("_event", "")
            latest_claim_by_topic_slot[(turn["topic_key"], slot)] = turn["semantic_payload"]

    expected_topics = [topic["topic_key"] for topic in plan["topic_registry"]]
    expected_block_targets = [
        {
            "topic_key": topic["topic_key"],
            "topic_title": topic["topic_title"],
            "slots": sorted({event_type.replace("_event", "") for event_type in topic["desired_event_types"]}),
        }
        for topic in plan["topic_registry"]
    ]
    expected_current_state_targets = [
        {
            "topic_key": topic["topic_key"],
            "slot": slot,
            "claim_hint": latest_claim_by_topic_slot.get((topic["topic_key"], slot), topic["topic_title"]),
        }
        for topic in plan["topic_registry"]
        for slot in sorted({event_type.replace("_event", "") for event_type in topic["desired_event_types"]})
        if (topic["topic_key"], slot) in latest_claim_by_topic_slot
    ]
    required_event_coverage = sorted({event_type for topic in plan["topic_registry"] for event_type in topic["desired_event_types"]})
    required_state_transitions = [
        transition for topic in plan["topic_registry"] for transition in topic["state_transitions"]
    ]
    topic_sources: dict[str, set[str]] = {}
    for session in plan["sessions"]:
        for topic_key in session["topic_keys"]:
            topic_sources.setdefault(topic_key, set()).add(session["source_ref"])
    required_cross_source_revisions = sorted(topic_key for topic_key, sources in topic_sources.items() if len(sources) >= 2)
    return validate_target_state(
        {
            "case_id": plan["case_id"],
            "expected_topics": expected_topics,
            "expected_block_targets": expected_block_targets,
            "expected_current_state_targets": expected_current_state_targets,
            "required_event_coverage": required_event_coverage,
            "required_state_transitions": required_state_transitions,
            "required_cross_source_revisions": required_cross_source_revisions,
        }
    )
