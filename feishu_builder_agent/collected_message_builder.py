from __future__ import annotations

import re
from typing import Any

from .schemas import (
    validate_actor_registry,
    validate_characters,
    validate_collected_messages_v3,
    validate_command_plan_v3,
    validate_execution_plan,
    validate_execution_result,
)


_PREFIX_RE = re.compile(r"^【(?P<department>[^/】]+)/(?P<name>[^】]+)】")


def _messages_from_fetch_records(fetch_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_message_id: dict[str, dict[str, Any]] = {}
    for record in fetch_records:
        response = record.get("response")
        if not isinstance(response, dict):
            continue
        data = response.get("data")
        if not isinstance(data, dict):
            continue
        for message in data.get("messages") or []:
            if not isinstance(message, dict):
                continue
            message_id = str(message.get("message_id") or "").strip()
            if message_id:
                by_message_id[message_id] = message
    return by_message_id


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["person_id"]: item for item in validate_characters(characters)["characters"]}


def _actor_registry_map(actor_registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not actor_registry:
        return {}
    return {item["person_id"]: item for item in validate_actor_registry(actor_registry)["actors"]}


def _prefix_hint(content_text: str, roster: dict[str, dict[str, Any]]) -> dict[str, str]:
    match = _PREFIX_RE.match(content_text.strip())
    if not match:
        return {"speaker_ref": "", "name": "", "department": ""}
    department = str(match.group("department") or "").strip()
    name = str(match.group("name") or "").strip()
    speaker_ref = ""
    for person_id, character in roster.items():
        if character["name"] == name and character["department"] == department:
            speaker_ref = person_id
            break
    return {"speaker_ref": speaker_ref, "name": name, "department": department}


def build_collected_messages(
    characters: dict[str, Any],
    command_plan: list[dict[str, Any]],
    execution_plan: dict[str, Any],
    execution_result: dict[str, Any],
    fetch_records: list[dict[str, Any]],
    *,
    actor_registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    roster = _character_map(characters)
    registry = _actor_registry_map(actor_registry)
    command_rows = validate_command_plan_v3(command_plan)
    plan = validate_execution_plan(execution_plan)
    result = validate_execution_result(execution_result)
    action_map = {action["action_id"]: action for action in plan["actions"]}
    fetch_message_map = _messages_from_fetch_records(fetch_records)
    created_resources = result["created_resources"]
    rows = []
    for row in command_rows:
        if row["action_type"] not in {"send_message", "reply_in_thread"}:
            continue
        action = action_map.get(row["step_id"])
        if not action:
            continue
        output_ref = str(action.get("output_ref") or row.get("output_ref") or "").strip()
        created = created_resources.get(output_ref, {}) if output_ref else {}
        message_id = str(created.get("message_id") or output_ref or row["step_id"]).strip()
        fetched = fetch_message_map.get(message_id, {})
        content_text = str(fetched.get("content") or row["params"]["content_text"]).strip()
        prefix_hint = _prefix_hint(content_text, roster)
        character = roster[row["speaker_ref"]]
        simulated_open_id = registry.get(row["speaker_ref"], {}).get("simulated_open_id") or character["simulated_open_id"]
        sender = fetched.get("sender") if isinstance(fetched.get("sender"), dict) else {}
        rows.append(
            {
                "turn_id": row["step_id"],
                "sequence_no": row["sequence_no"],
                "session_id": row["session_id"],
                "source_type": row["source_type"],
                "source_ref": row["source_ref"],
                "chat_ref": row["chat_ref"],
                "speaker_ref": row["speaker_ref"],
                "topic_key": row["topic_key"],
                "turn_purpose": row["turn_purpose"],
                "semantic_payload": row["semantic_payload"],
                "content_text": content_text,
                "message_id": message_id,
                "collect_source": "fetch_records" if fetched else "simulated_observation",
                "benchmark_role": row["benchmark_role"],
                "memory_failure_mode": row["memory_failure_mode"],
                "memory_trap": row["memory_trap"],
                "state_field_hints": row["state_field_hints"],
                "probe_query_hints": [],
                "actual_sender": {
                    "open_id": str(sender.get("id") or "").strip(),
                    "name": str(sender.get("name") or "").strip(),
                    "sender_type": str(sender.get("sender_type") or "user").strip() or "user",
                },
                "simulated_speaker": {
                    "speaker_ref": row["speaker_ref"],
                    "open_id": simulated_open_id,
                    "name": character["name"],
                    "department": character["department"],
                    "role": character["role"],
                },
                "normalized_actor_id": row["speaker_ref"],
                "speaker_resolution_mode": "command_plan+prefix" if prefix_hint.get("speaker_ref") == row["speaker_ref"] else "command_plan_only",
                "prefix_speaker_hint": prefix_hint,
            }
        )
    return validate_collected_messages_v3(rows)
