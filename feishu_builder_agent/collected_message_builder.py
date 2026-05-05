from __future__ import annotations

import re
from typing import Any

from .schemas import (
    validate_characters,
    validate_collected_messages,
    validate_command_plan,
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
        messages = data.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            message_id = str(message.get("message_id") or "").strip()
            if not message_id:
                continue
            by_message_id[message_id] = message
    return by_message_id


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["person_id"]: item for item in validate_characters(characters)["characters"]}


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


def _build_simulated_speaker(
    expected_speaker_ref: str,
    roster: dict[str, dict[str, Any]],
    prefix_hint: dict[str, str],
) -> tuple[dict[str, str], str]:
    character = roster[expected_speaker_ref]
    hinted_ref = str(prefix_hint.get("speaker_ref") or "").strip()
    hinted_name = str(prefix_hint.get("name") or "").strip()
    hinted_department = str(prefix_hint.get("department") or "").strip()
    if hinted_ref and hinted_ref == expected_speaker_ref:
        resolution_mode = "command_plan+prefix"
    elif hinted_ref and hinted_ref != expected_speaker_ref:
        resolution_mode = "conflict_prefix_vs_command_plan"
    elif hinted_name and hinted_department:
        resolution_mode = "command_plan+unmatched_prefix"
    else:
        resolution_mode = "command_plan_only"
    return (
        {
            "speaker_ref": expected_speaker_ref,
            "open_id": character["simulated_open_id"],
            "name": character["name"],
            "department": character["department"],
            "role": character["role"],
            "stance": character["stance"],
        },
        resolution_mode,
    )


def build_collected_messages(
    characters: dict[str, Any],
    command_plan: list[dict[str, Any]],
    execution_plan: dict[str, Any],
    execution_result: dict[str, Any],
    fetch_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    roster = _character_map(characters)
    command_rows = validate_command_plan(command_plan)
    plan = validate_execution_plan(execution_plan)
    result = validate_execution_result(execution_result)
    action_map = {action["action_id"]: action for action in plan["actions"]}
    fetch_message_map = _messages_from_fetch_records(fetch_records)
    created_resources = result["created_resources"]
    output_rows: list[dict[str, Any]] = []
    for row in command_rows:
        if row["action_type"] not in {"send_message", "reply_in_thread"}:
            continue
        matching_action = action_map.get(row["step_id"])
        if not matching_action:
            continue
        output_ref = str(matching_action.get("output_ref") or row.get("output_ref") or "").strip()
        created = created_resources.get(output_ref, {}) if output_ref else {}
        message_id = str(created.get("message_id") or "").strip()
        fetched = fetch_message_map.get(message_id, {})
        content_text = str(fetched.get("content") or row["params"]["content_text"]).strip()
        prefix_hint = _prefix_hint(content_text, roster)
        simulated_speaker, speaker_resolution_mode = _build_simulated_speaker(
            row["speaker_ref"],
            roster,
            prefix_hint,
        )
        sender = fetched.get("sender") if isinstance(fetched.get("sender"), dict) else {}
        output_rows.append(
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
                "supports_event_types": row["supports_event_types"],
                "references_previous_turns": [],
                "state_transition": row["state_transition"],
                "semantic_payload": row["semantic_payload"],
                "root_turn_id": row.get("root_turn_id"),
                "content_text": content_text,
                "message_id": message_id or output_ref or row["step_id"],
                "collect_source": "fetch_records" if fetched else "execution_result",
                "actual_sender": {
                    "open_id": str(sender.get("id") or "").strip(),
                    "name": str(sender.get("name") or "").strip(),
                    "sender_type": str(sender.get("sender_type") or "user").strip() or "user",
                },
                "simulated_speaker": simulated_speaker,
                "normalized_actor_id": row["speaker_ref"],
                "speaker_resolution_mode": speaker_resolution_mode,
                "prefix_speaker_hint": prefix_hint,
            }
        )
    return validate_collected_messages(output_rows)
