from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .executor import Runner, _action_command, _safe_json, default_runner
from ..schemas import (
    validate_actor_registry,
    validate_characters,
    validate_command_plan,
    validate_execution_plan,
    validate_execution_result,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collect_fetch_records(
    execution_plan: dict[str, Any],
    execution_result: dict[str, Any],
    *,
    runner: Runner | None = None,
    lark_cli_bin: str = "lark-cli",
    fetch_identity: str = "user",
) -> list[dict[str, Any]]:
    plan = validate_execution_plan(execution_plan)
    result = validate_execution_result(execution_result)
    active_runner = runner or default_runner
    created_resources = result["created_resources"]
    rows: list[dict[str, Any]] = []
    for action in plan["actions"]:
        if action["action_type"] not in {"fetch_chat_messages", "fetch_thread_messages"}:
            continue
        command = _action_command(
            action,
            lark_cli_bin=lark_cli_bin,
            created_resources=created_resources,
            operator_identity=fetch_identity,
        )
        completed = active_runner(command)
        rows.append(
            {
                "record_id": f"fetch-{action['action_id']}",
                "domain": "im",
                "kind": "chat_messages_fetch" if action["action_type"] == "fetch_chat_messages" else "thread_messages_fetch",
                "captured_at": utc_now_iso(),
                "identity": fetch_identity,
                "command": " ".join(command),
                "response": _safe_json(completed.stdout),
                "stderr": completed.stderr.strip(),
                "returncode": completed.returncode,
            }
        )
    return rows


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
            message_id = str(message.get("message_id") or message.get("id") or "").strip()
            if message_id:
                by_message_id[message_id] = message
    return by_message_id


_PREFIX_RE = re.compile(r"^【(?P<department>[^/】]+)/(?P<name>[^】]+)】(?P<body>.*)$", re.DOTALL)


def _strip_speaker_prefix(text: str) -> str:
    match = _PREFIX_RE.match(text.strip())
    if not match:
        return text.strip()
    return match.group("body").strip()


def _prefix_hint(text: str, registry_by_name_department: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    match = _PREFIX_RE.match(text.strip())
    if not match:
        return None
    department = match.group("department").strip()
    name = match.group("name").strip()
    actor = registry_by_name_department.get((name, department))
    return {
        "department": department,
        "name": name,
        "resolved_person_id": actor.get("person_id") if actor else None,
    }


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validated = validate_characters(characters)
    return {item["person_id"]: item for item in validated["characters"]}


def _registry_map(actor_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validated = validate_actor_registry(actor_registry)
    return {item["person_id"]: item for item in validated["actors"]}


def _registry_by_name_department(actor_registry: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    validated = validate_actor_registry(actor_registry)
    return {(item["name"], item["department"]): item for item in validated["actors"]}


def _message_content_text(message: dict[str, Any], fallback: str) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()
        if isinstance(parsed, dict):
            text = parsed.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return fallback.strip()


def _sender_from_message(message: dict[str, Any]) -> dict[str, Any]:
    sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
    sender_id = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
    return {
        "open_id": str(sender_id.get("open_id") or sender.get("open_id") or sender.get("id") or ""),
        "name": str(sender.get("sender_name") or sender.get("name") or ""),
        "sender_type": str(sender.get("sender_type") or "user"),
        "raw": sender,
    }


def _message_timestamp_ms(message: dict[str, Any], fallback_iso: str) -> str:
    for key in ("create_time", "created_at", "update_time"):
        value = message.get(key)
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, str) and value.strip().isdigit():
            return value.strip()
    try:
        parsed = datetime.fromisoformat(fallback_iso.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return str(int(parsed.timestamp() * 1000))


def build_observed_messages(
    *,
    case_id: str,
    task_id: str,
    command_plan: list[dict[str, Any]],
    execution_result: dict[str, Any],
    fetch_records: list[dict[str, Any]],
    characters: dict[str, Any],
    actor_registry: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    commands = validate_command_plan(command_plan)
    result = validate_execution_result(execution_result)
    fetched_messages = _messages_from_fetch_records(fetch_records)
    characters_by_person = _character_map(characters)
    registry_by_person = _registry_map(actor_registry)
    registry_by_hint = _registry_by_name_department(actor_registry)
    collected: list[dict[str, Any]] = []
    ingress: list[dict[str, Any]] = []
    for row in commands:
        if row["action_type"] not in {"send_message", "reply_in_thread"}:
            continue
        if not row["beat_id"]:
            continue
        person_id = str(row["speaker_ref"] or row["actor_id"])
        character = characters_by_person.get(person_id)
        registry_actor = registry_by_person.get(person_id)
        if character is None or registry_actor is None:
            raise ValueError(f"command_plan references unknown person_id: {person_id}")
        output_ref = row["output_ref"]
        resource = result["created_resources"].get(output_ref, {})
        message_id = str(resource.get("message_id") or output_ref).strip()
        fetched = fetched_messages.get(message_id, {})
        fallback_content = str(row["params"].get("content_text") or row["planned_message_text"]).strip()
        content = _message_content_text(fetched, fallback_content)
        observed_at = utc_now_iso()
        actual_sender = _sender_from_message(fetched) if fetched else {}
        hint = _prefix_hint(content, registry_by_hint)
        resolution_mode = (
            "command_plan+prefix"
            if hint and hint.get("resolved_person_id") == person_id
            else "command_plan_only"
        )
        simulated_speaker = {
            "speaker_ref": person_id,
            "open_id": registry_actor["simulated_open_id"],
            "name": registry_actor["name"],
            "department": registry_actor["department"],
            "role": registry_actor["role"],
        }
        chat_id = str(resource.get("chat_id") or row["chat_ref"])
        thread_id = str(resource.get("thread_id") or "")
        root_id = thread_id if row["source_type"] == "thread" else ""
        stripped_content = _strip_speaker_prefix(content)
        collected_row = {
            "case_id": case_id,
            "task_id": task_id,
            "message_id": message_id,
            "beat_id": row["beat_id"],
            "actor_id": row["actor_id"],
            "speaker_ref": person_id,
            "normalized_actor_id": person_id,
            "session_id": row["session_id"],
            "message_text": content,
            "content_text": content,
            "observed_text_without_prefix": stripped_content,
            "observed_at": observed_at,
            "collect_source": "fetch_records" if fetched else "execution_result",
            "source_type": row["source_type"],
            "source_ref": row["source_ref"],
            "benchmark_role": row["benchmark_role"],
            "actual_sender": actual_sender,
            "simulated_speaker": simulated_speaker,
            "speaker_resolution_mode": resolution_mode,
            "prefix_speaker_hint": hint,
        }
        ingress_row = {
            "case_id": case_id,
            "task_id": task_id,
            "event_type": "im.message.receive_v1",
            "sender": {
                "sender_id": {"open_id": simulated_speaker["open_id"]},
                "sender_type": "user",
                "sender_name": simulated_speaker["name"],
            },
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "root_id": root_id,
                "parent_id": root_id,
                "message_type": "text",
                "chat_type": "group",
                "content": json.dumps({"text": stripped_content}, ensure_ascii=False),
                "create_time": _message_timestamp_ms(fetched, observed_at),
            },
            "benchmark_trace": {
                "source_session_id": row["session_id"],
                "source_type": row["source_type"],
                "source_ref": row["source_ref"],
                "beat_id": row["beat_id"],
                "normalized_actor_id": person_id,
            },
        }
        collected.append(collected_row)
        ingress.append(ingress_row)
    return collected, ingress
