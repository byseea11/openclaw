from __future__ import annotations

import json
import re
import shlex
from datetime import datetime, timezone
from typing import Any

from .schemas import validate_case_spec, validate_collected_messages, validate_execution_result


_PREFIX_RE = re.compile(r"^【[^/】]+/[^】]+】\s*")


def _to_epoch_ms_string(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        if len(text) >= 13:
            return text
        return str(int(text) * 1000)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, fmt)
            parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return str(int(parsed.timestamp() * 1000))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return str(int(parsed.timestamp() * 1000))
    except ValueError:
        return ""


def _parse_time_ms(value: Any) -> int:
    text = _to_epoch_ms_string(value)
    return int(text or "0")


def _build_message_id_to_chat_id(created_resources: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for resource in created_resources.values():
        if not isinstance(resource, dict):
            continue
        message_id = str(resource.get("message_id") or "").strip()
        chat_id = str(resource.get("chat_id") or "").strip()
        if message_id and chat_id:
            output[message_id] = chat_id
    return output


def _command_flag_value(command: Any, flag: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text)
    except ValueError:
        return ""
    for index, part in enumerate(parts[:-1]):
        if part == flag:
            return str(parts[index + 1]).strip()
    return ""


def _collected_message_map(collected_messages: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not collected_messages:
        return {}
    rows = validate_collected_messages(collected_messages)
    return {str(row.get("message_id") or "").strip(): row for row in rows if str(row.get("message_id") or "").strip()}


def _strip_prefixed_speaker(text: Any) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    return _PREFIX_RE.sub("", content, count=1).strip()


def adapt_fetch_records(
    case_spec: dict[str, Any],
    execution_result: dict[str, Any],
    fetch_records: list[dict[str, Any]],
    collected_messages: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = validate_case_spec(case_spec)
    result = validate_execution_result(execution_result)
    thread_id_to_chat_id: dict[str, str] = {
        str(key): str(value) for key, value in (result.get("thread_id_to_chat_id") or {}).items()
    }
    message_id_to_chat_id = _build_message_id_to_chat_id(result.get("created_resources") or {})
    collected_by_message_id = _collected_message_map(collected_messages)
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    filled_fields: list[dict[str, str]] = []
    skipped_messages = 0
    input_messages = 0
    simulated_sender_applied = 0
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
        command_chat_id = _command_flag_value(record.get("command"), "--chat-id")
        source_thread_id = str(data.get("thread_id") or "").strip()
        for message in messages:
            if not isinstance(message, dict):
                continue
            input_messages += 1
            if message.get("deleted"):
                skipped_messages += 1
                continue
            if str(message.get("msg_type") or "").strip() != "text":
                skipped_messages += 1
                continue
            chat_id = str(message.get("chat_id") or "").strip()
            message_id = str(message.get("message_id") or "").strip()
            thread_id = str(message.get("thread_id") or "").strip()
            root_id = str(message.get("root_id") or "").strip()
            if not thread_id and source_thread_id:
                root_id = root_id or source_thread_id
            if not chat_id:
                if message_id and message_id in message_id_to_chat_id:
                    chat_id = message_id_to_chat_id[message_id]
                    filled_fields.append({"field": "message.chat_id", "source": "execution_result.created_resources"})
            if not chat_id and command_chat_id:
                chat_id = command_chat_id
                filled_fields.append({"field": "message.chat_id", "source": "fetch_record.command"})
            if not chat_id:
                lookup_key = thread_id or root_id or source_thread_id
                if lookup_key and lookup_key in thread_id_to_chat_id:
                    chat_id = thread_id_to_chat_id[lookup_key]
                    filled_fields.append({"field": "message.chat_id", "source": "execution_result.thread_id_to_chat_id"})
            if not chat_id:
                skipped_messages += 1
                warnings.append(f"skipped message {message.get('message_id')} because chat_id could not be resolved")
                continue
            raw_content_text = str(message.get("content") or "").strip()
            collected_row = collected_by_message_id.get(message_id, {})
            content_text = _strip_prefixed_speaker(
                collected_row.get("content_text") if collected_row else raw_content_text
            ) or _strip_prefixed_speaker(raw_content_text) or raw_content_text
            sender = (message.get("sender") or {}) if isinstance(message.get("sender"), dict) else {}
            actual_sender = {
                "open_id": str(sender.get("id") or "").strip(),
                "name": str(sender.get("name") or "").strip(),
                "sender_type": str(sender.get("sender_type") or "user").strip() or "user",
            }
            normalized_actor_id = ""
            simulated_speaker: dict[str, Any] = {}
            synthetic_sender_open_id = ""
            if collected_row:
                normalized_actor_id = str(collected_row.get("normalized_actor_id") or "").strip()
                simulated_speaker = dict(collected_row.get("simulated_speaker") or {})
                synthetic_sender_open_id = str(simulated_speaker.get("open_id") or "").strip()
                if synthetic_sender_open_id:
                    simulated_sender_applied += 1
            event = {
                "case_id": spec["case_id"],
                "task_id": spec["task_id"],
                "event_type": "im.message.receive_v1",
                "sender": {
                    "sender_id": {"open_id": synthetic_sender_open_id or actual_sender["open_id"]},
                    "sender_type": actual_sender["sender_type"],
                },
                "message": {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "chat_type": str(message.get("chat_type") or "group"),
                    "thread_id": thread_id or None,
                    "root_id": root_id or None,
                    "parent_id": None,
                    "message_type": "text",
                    "content": json.dumps({"text": content_text}, ensure_ascii=False, separators=(",", ":")),
                    "create_time": _to_epoch_ms_string(message.get("create_time")),
                    "mentions": [],
                },
            }
            events.append(event)
    events.sort(key=lambda item: (_parse_time_ms(item["message"]["create_time"]), item["message"]["message_id"]))
    report = {
        "case_id": spec["case_id"],
        "input_fetch_records": len(fetch_records),
        "input_messages": input_messages,
        "output_events": len(events),
        "skipped_messages": skipped_messages,
        "simulated_sender_applied": simulated_sender_applied,
        "filled_fields": filled_fields,
        "warnings": warnings,
    }
    return events, report
