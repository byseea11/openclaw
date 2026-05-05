from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas import (
    validate_collected_messages,
    validate_target_state,
    validate_conversation_plan,
    validate_expected_current_state,
    validate_expected_events,
    validate_expected_memory_blocks,
)


def _session_source_map(conversation_plan: dict[str, Any]) -> dict[str, str]:
    return {session["session_id"]: f"{session['source_type']}:{session['source_ref']}" for session in conversation_plan["sessions"]}


def generate_gold_artifacts(
    target_state: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    target = validate_target_state(target_state)
    plan = validate_conversation_plan(conversation_plan)
    messages = validate_collected_messages(collected_messages)
    source_session_map = _session_source_map(plan)
    expected_events: list[dict[str, Any]] = []
    block_rows: defaultdict[str, list[str]] = defaultdict(list)
    slot_map: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    latest_by_topic_slot: dict[tuple[str, str], dict[str, Any]] = {}
    for message in messages:
        for event_type in message["supports_event_types"]:
            event_id = f"gold_event_{message['turn_id']}_{event_type}"
            expected_events.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "topic_key": message["topic_key"],
                    "turn_id": message["turn_id"],
                    "source_session_id": source_session_map[message["session_id"]],
                    "normalized_actor_id": message["normalized_actor_id"],
                    "claim": message["semantic_payload"],
                    "evidence_turn_id": message["message_id"],
                    "expected_lifecycle": "active",
                }
            )
            block_rows[message["topic_key"]].append(event_id)
            slot_name = event_type.replace("_event", "")
            slot_map[message["topic_key"]][slot_name].append(event_id)
            latest_by_topic_slot[(message["topic_key"], slot_name)] = {
                "topic_key": message["topic_key"],
                "slot": slot_name,
                "event_id": event_id,
                "claim": message["semantic_payload"],
                "source_session_id": source_session_map[message["session_id"]],
            }
    validated_events = validate_expected_events(expected_events)
    block_title_map = {item["topic_key"]: item["topic_title"] for item in target["expected_block_targets"]}
    expected_memory_blocks = validate_expected_memory_blocks(
        {
            "case_id": plan["case_id"],
            "blocks": [
                {
                    "block_id": f"block:{item['topic_key']}",
                    "topic_key": item["topic_key"],
                    "topic_title": item["topic_title"],
                    "supporting_event_ids": block_rows[item["topic_key"]],
                    "slot_event_map": {
                        slot: slot_map[item["topic_key"]].get(slot, [])
                        for slot in item["slots"]
                    },
                }
                for item in target["expected_block_targets"]
            ],
        }
    )
    expected_current_state = validate_expected_current_state(
        {
            "case_id": plan["case_id"],
            "current_items": [
                latest_by_topic_slot[(item["topic_key"], item["slot"])]
                for item in target["expected_current_state_targets"]
                if (item["topic_key"], item["slot"]) in latest_by_topic_slot
            ],
        }
    )
    return {
        "target_state": target,
        "expected_events": validated_events,
        "expected_memory_blocks": expected_memory_blocks,
        "expected_current_state": expected_current_state,
    }
