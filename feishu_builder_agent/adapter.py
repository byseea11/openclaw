from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .schemas import validate_case_spec, validate_execution_result


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


def adapt_fetch_records(
    case_spec: dict[str, Any],
    execution_result: dict[str, Any],
    fetch_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = validate_case_spec(case_spec)
    result = validate_execution_result(execution_result)
    thread_id_to_chat_id: dict[str, str] = {
        str(key): str(value) for key, value in (result.get("thread_id_to_chat_id") or {}).items()
    }
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    filled_fields: list[dict[str, str]] = []
    skipped_messages = 0
    input_messages = 0
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
            thread_id = str(message.get("thread_id") or "").strip()
            root_id = str(message.get("root_id") or "").strip()
            if not thread_id and source_thread_id:
                root_id = root_id or source_thread_id
            if not chat_id:
                lookup_key = thread_id or root_id or source_thread_id
                if lookup_key and lookup_key in thread_id_to_chat_id:
                    chat_id = thread_id_to_chat_id[lookup_key]
                    filled_fields.append({"field": "message.chat_id", "source": "execution_result.thread_id_to_chat_id"})
            if not chat_id:
                skipped_messages += 1
                warnings.append(f"skipped message {message.get('message_id')} because chat_id could not be resolved")
                continue
            content_text = str(message.get("content") or "").strip()
            event = {
                "case_id": spec["case_id"],
                "task_id": spec["task_id"],
                "event_type": "im.message.receive_v1",
                "sender": {
                    "sender_id": {"open_id": str(((message.get("sender") or {}).get("id")) or "").strip()},
                    "sender_type": str(((message.get("sender") or {}).get("sender_type")) or "user"),
                },
                "message": {
                    "message_id": str(message.get("message_id") or "").strip(),
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
        "filled_fields": filled_fields,
        "warnings": warnings,
    }
    return events, report
