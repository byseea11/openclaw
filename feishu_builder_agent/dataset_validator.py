from __future__ import annotations

from typing import Any

from .schemas import (
    validate_case_seed,
    validate_case_world,
    validate_characters,
    validate_complexity_report,
    validate_conversation_plan,
    validate_dataset_validation_report,
    validate_expected_current_state,
    validate_expected_events,
    validate_expected_memory_blocks,
    validate_realized_messages,
    validate_utterance_plan,
)


def build_dataset_validation_report(
    *,
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
    conversation_plan: dict[str, Any],
    utterance_plan: list[dict[str, Any]],
    realized_messages: list[dict[str, Any]],
    complexity_report: dict[str, Any],
    expected_events: list[dict[str, Any]],
    expected_memory_blocks: dict[str, Any],
    expected_current_state: dict[str, Any],
) -> dict[str, Any]:
    seed = validate_case_seed(case_seed)
    validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    allowed_refs = {item["person_id"] for item in validated_characters["characters"]}
    plan = validate_conversation_plan(conversation_plan, allowed_actor_refs=allowed_refs)
    utterances = validate_utterance_plan(utterance_plan, allowed_actor_refs=allowed_refs)
    messages = validate_realized_messages(realized_messages, allowed_actor_refs=allowed_refs)
    complexity = validate_complexity_report(complexity_report)
    events = validate_expected_events(expected_events)
    blocks = validate_expected_memory_blocks(expected_memory_blocks)
    current_state = validate_expected_current_state(expected_current_state)
    message_turn_ids = {row["turn_id"] for row in messages}
    errors: list[str] = []
    if len(utterances) != len(messages):
        errors.append("utterance_plan and realized_messages must contain the same number of rows")
    if not complexity["passed"]:
        errors.append("conversation complexity gate did not pass")
    for event in events:
        if event["evidence_turn_id"] not in message_turn_ids:
            errors.append(f"gold event {event['event_id']} references missing evidence_turn_id {event['evidence_turn_id']}")
    block_event_ids = {event_id for block in blocks["blocks"] for event_id in block["supporting_event_ids"]}
    known_event_ids = {event["event_id"] for event in events}
    if not block_event_ids.issubset(known_event_ids):
        errors.append("expected_memory_blocks contains supporting_event_ids missing from expected_events")
    current_event_ids = {item["event_id"] for item in current_state["current_items"]}
    if not current_event_ids.issubset(known_event_ids):
        errors.append("expected_current_state references event_ids missing from expected_events")
    checks = {
        "characters_count": len(validated_characters["characters"]),
        "planned_sessions": len(plan["sessions"]),
        "planned_turns": len(plan["turns"]),
        "realized_messages": len(messages),
        "gold_events": len(events),
        "memory_blocks": len(blocks["blocks"]),
        "current_state_items": len(current_state["current_items"]),
    }
    return validate_dataset_validation_report(
        {
            "case_id": seed["case_id"],
            "passed": not errors,
            "errors": errors,
            "checks": checks,
        }
    )
