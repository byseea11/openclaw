from __future__ import annotations

from typing import Any

from .schemas import (
    validate_actor_registry,
    validate_case_seed,
    validate_case_world,
    validate_characters,
    validate_collected_messages,
    validate_complexity_report,
    validate_conversation_plan,
    validate_dataset_validation_report,
    validate_expected_current_state,
    validate_expected_events,
    validate_expected_memory_blocks,
    validate_target_state,
    validate_command_plan,
)


def build_dataset_validation_report(
    *,
    case_seed: dict[str, Any],
    case_world: dict[str, Any],
    characters: dict[str, Any],
    actor_registry: dict[str, Any],
    conversation_plan: dict[str, Any],
    target_state: dict[str, Any],
    command_plan: list[dict[str, Any]],
    collected_messages: list[dict[str, Any]],
    complexity_report: dict[str, Any],
    expected_events: list[dict[str, Any]],
    expected_memory_blocks: dict[str, Any],
    expected_current_state: dict[str, Any],
) -> dict[str, Any]:
    seed = validate_case_seed(case_seed)
    validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    validated_actor_registry = validate_actor_registry(actor_registry)
    allowed_refs = {item["person_id"] for item in validated_characters["characters"]}
    character_by_ref = {item["person_id"]: item for item in validated_characters["characters"]}
    actor_by_ref = {item["person_id"]: item for item in validated_actor_registry["actors"]}
    plan = validate_conversation_plan(conversation_plan, allowed_actor_refs=allowed_refs)
    target = validate_target_state(target_state)
    commands = validate_command_plan(command_plan, allowed_actor_refs=allowed_refs)
    messages = validate_collected_messages(collected_messages, allowed_actor_refs=allowed_refs)
    complexity = validate_complexity_report(complexity_report)
    events = validate_expected_events(expected_events)
    blocks = validate_expected_memory_blocks(expected_memory_blocks)
    current_state = validate_expected_current_state(expected_current_state)
    command_step_ids = {row["step_id"] for row in commands}
    message_turn_ids = {row["turn_id"] for row in messages}
    message_ids = {row["message_id"] for row in messages}
    errors: list[str] = []
    message_commands = [row for row in commands if row["action_type"] in {"send_message", "reply_in_thread"}]
    if len(message_commands) != len(messages):
        errors.append("command_plan message actions and collected_messages must contain the same number of rows")
    if not complexity["passed"]:
        errors.append("conversation complexity gate did not pass")
    topic_keys = {topic["topic_key"] for topic in plan["topic_registry"]}
    if set(target["expected_topics"]) != topic_keys:
        errors.append("target_state.expected_topics must match conversation_plan.topic_registry")
    if not any(row["action_type"] == "fetch_thread_messages" for row in commands):
        errors.append("command_plan must contain at least one fetch_thread_messages action")
    command_by_step_id = {row["step_id"]: row for row in commands}
    for message in messages:
        command_row = command_by_step_id.get(message["turn_id"])
        if not command_row:
            errors.append(f"collected_message {message['turn_id']} does not map to any command_plan step")
            continue
        if message["normalized_actor_id"] != command_row["speaker_ref"]:
            errors.append(f"collected_message {message['turn_id']} normalized_actor_id must match command_plan.speaker_ref")
        if message["simulated_speaker"]["speaker_ref"] != command_row["speaker_ref"]:
            errors.append(f"collected_message {message['turn_id']} simulated_speaker.speaker_ref must match command_plan.speaker_ref")
        character = character_by_ref.get(command_row["speaker_ref"])
        if character and message["simulated_speaker"]["open_id"] != character["simulated_open_id"]:
            errors.append(
                f"collected_message {message['turn_id']} simulated_speaker.open_id must match characters.json simulated_open_id"
            )
        actor = actor_by_ref.get(command_row["speaker_ref"])
        if actor and message["simulated_speaker"]["open_id"] != actor["simulated_open_id"]:
            errors.append(
                f"collected_message {message['turn_id']} simulated_speaker.open_id must match actor_registry simulated_open_id"
            )
        if message["speaker_resolution_mode"] == "conflict_prefix_vs_command_plan":
            errors.append(f"collected_message {message['turn_id']} has a prefix/command_plan speaker conflict")
    for event in events:
        gold_meta = event["gold_meta"]
        if gold_meta["turn_id"] not in message_turn_ids:
            errors.append(f"gold event {event['event_id']} references missing turn_id {gold_meta['turn_id']}")
        if gold_meta["evidence_turn_id"] not in message_ids:
            errors.append(f"gold event {event['event_id']} references missing evidence_turn_id {gold_meta['evidence_turn_id']}")
        matching_message = next((item for item in messages if item["turn_id"] == gold_meta["turn_id"]), None)
        if matching_message and gold_meta["normalized_actor_id"] != matching_message["normalized_actor_id"]:
            errors.append(f"gold event {event['event_id']} normalized_actor_id must match collected_messages")
        if matching_message and event["core_entry_id"] != matching_message["message_id"]:
            errors.append(f"gold event {event['event_id']} core_entry_id must match collected_messages.message_id")
    block_event_ids = {event_id for block in blocks["blocks"] for event_id in block["supporting_event_ids"]}
    known_event_ids = {event["event_id"] for event in events}
    if not block_event_ids.issubset(known_event_ids):
        errors.append("expected_memory_blocks contains supporting_event_ids missing from expected_events")
    current_event_ids = {item["event_id"] for item in current_state["current_items"]}
    if not current_event_ids.issubset(known_event_ids):
        errors.append("expected_current_state references event_ids missing from expected_events")
    for item in messages:
        if item["normalized_actor_id"] not in character_by_ref:
            errors.append(f"collected_message {item['turn_id']} normalized_actor_id is missing from characters.json")
    checks = {
        "characters_count": len(validated_characters["characters"]),
        "planned_sessions": len(plan["sessions"]),
        "planned_turns": len(plan["turns"]),
        "command_steps": len(commands),
        "collected_messages": len(messages),
        "gold_events": len(events),
        "memory_blocks": len(blocks["blocks"]),
        "current_state_items": len(current_state["current_items"]),
        "target_current_state_items": len(target["expected_current_state_targets"]),
        "command_step_ids": len(command_step_ids),
        "unique_actual_senders": len({item["actual_sender"]["open_id"] for item in messages if item["actual_sender"]["open_id"]}),
        "unique_normalized_actors": len({item["normalized_actor_id"] for item in messages}),
    }
    ingress_open_ids = {
        item["simulated_open_id"]
        for item in validated_characters["characters"]
    }
    checks["simulated_open_ids"] = len(ingress_open_ids)
    checks["actor_registry_size"] = len(validated_actor_registry["actors"])
    return validate_dataset_validation_report(
        {
            "case_id": seed["case_id"],
            "passed": not errors,
            "errors": errors,
            "checks": checks,
        }
    )
