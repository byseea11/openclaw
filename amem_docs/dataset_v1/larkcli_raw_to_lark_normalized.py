#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path


DATASET_DIR = Path("amem_docs/dataset_v1")
INPUT_FILES = [
    DATASET_DIR / "raw_feishu_fetches_2026-04-26.jsonl",
    DATASET_DIR / "raw_feishu_fetches_2026-04-26-sync.jsonl",
]
FALLBACK_FILES = [
    DATASET_DIR / "raw_channel_im_v0.jsonl",
    DATASET_DIR / "raw_dataset_v0.jsonl",
]
OUTPUT_FILE = DATASET_DIR / "lark_normalized_im_v0.jsonl"
REPORT_FILE = DATASET_DIR / "lark_normalized_im_report_v0.json"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def normalize_mentions(mentions: list[dict] | None) -> list[dict]:
    if not mentions:
        return []
    out: list[dict] = []
    for mention in mentions:
        out.append(
            {
                "id": mention.get("id"),
                "key": mention.get("key"),
                "name": mention.get("name"),
            }
        )
    return out


def normalize_message(
    *,
    source_file: str,
    source_record_id: str,
    source_command: str,
    source_scope: str,
    chat_id: str,
    message: dict,
    parent_message_id: str | None,
) -> dict:
    sender = message.get("sender") or {}
    return {
        "source_platform": "feishu",
        "source_file": source_file,
        "source_record_id": source_record_id,
        "source_command": source_command,
        "chat_id": chat_id,
        "chat_type": "group" if chat_id.startswith("oc_") else "unknown",
        "message_scope": source_scope,
        "message_id": message.get("message_id"),
        "root_id": parent_message_id or message.get("message_id"),
        "parent_id": parent_message_id,
        "thread_id": message.get("thread_id"),
        "message_type": message.get("msg_type"),
        "content_text": message.get("content"),
        "sender_open_id": sender.get("id"),
        "sender_id_type": sender.get("id_type"),
        "sender_type": sender.get("sender_type"),
        "sender_name": sender.get("name"),
        "tenant_key": sender.get("tenant_key"),
        "mentions": normalize_mentions(message.get("mentions")),
        "create_time": message.get("create_time"),
        "deleted": bool(message.get("deleted", False)),
        "updated": bool(message.get("updated", False)),
    }


def main() -> None:
    normalized_rows: list[dict] = []
    skipped: list[dict] = []
    used_files: list[Path] = [path for path in INPUT_FILES if path.exists()]
    fallback_mode = False

    if not used_files:
        used_files = [path for path in FALLBACK_FILES if path.exists()]
        fallback_mode = True

    for input_path in used_files:
        rows = load_jsonl(input_path)
        for row in rows:
            if "raw_message" in row:
                normalized_rows.append(
                    {
                        "source_platform": row.get("source_platform", "feishu"),
                        "source_file": input_path.name,
                        "source_record_id": None,
                        "source_command": None,
                        "chat_id": row.get("chat_id"),
                        "chat_type": "group" if str(row.get("chat_id", "")).startswith("oc_") else "unknown",
                        "message_scope": row.get("message_scope"),
                        "message_id": row["raw_message"].get("message_id"),
                        "root_id": row.get("parent_message_id") or row["raw_message"].get("message_id"),
                        "parent_id": row.get("parent_message_id"),
                        "thread_id": row["raw_message"].get("thread_id"),
                        "message_type": row["raw_message"].get("msg_type"),
                        "content_text": row["raw_message"].get("content"),
                        "sender_open_id": (row["raw_message"].get("sender") or {}).get("id"),
                        "sender_id_type": (row["raw_message"].get("sender") or {}).get("id_type"),
                        "sender_type": (row["raw_message"].get("sender") or {}).get("sender_type"),
                        "sender_name": (row["raw_message"].get("sender") or {}).get("name"),
                        "tenant_key": (row["raw_message"].get("sender") or {}).get("tenant_key"),
                        "mentions": normalize_mentions(row["raw_message"].get("mentions")),
                        "create_time": row["raw_message"].get("create_time"),
                        "deleted": bool(row["raw_message"].get("deleted", False)),
                        "updated": bool(row["raw_message"].get("updated", False)),
                    }
                )
                continue

            if row.get("domain") != "im":
                continue
            if row.get("kind") not in {"chat_messages_fetch", "thread_messages_fetch"}:
                continue

            response = row.get("response") or {}
            data = response.get("data") or {}
            chat_id = ""
            messages = data.get("messages") or []

            if row.get("kind") == "chat_messages_fetch":
                chat_id = row.get("command", "")
                if isinstance(data, dict):
                    chat_id = data.get("chat_id") or ""
                if not chat_id:
                    command = row.get("command", "")
                    marker = '--chat-id "'
                    if marker in command:
                        chat_id = command.split(marker, 1)[1].split('"', 1)[0]

                for message in messages:
                    normalized_rows.append(
                        normalize_message(
                            source_file=input_path.name,
                            source_record_id=row.get("record_id", ""),
                            source_command=row.get("command", ""),
                            source_scope="main_chat",
                            chat_id=chat_id,
                            message=message,
                            parent_message_id=None,
                        )
                    )
                    thread_replies = message.get("thread_replies") or []
                    for reply in thread_replies:
                        normalized_rows.append(
                            normalize_message(
                                source_file=input_path.name,
                                source_record_id=row.get("record_id", ""),
                                source_command=row.get("command", ""),
                                source_scope="thread_reply",
                                chat_id=chat_id,
                                message=reply,
                                parent_message_id=message.get("message_id"),
                            )
                        )
            elif row.get("kind") == "thread_messages_fetch":
                thread_id = data.get("thread_id")
                if not thread_id:
                    skipped.append(
                        {
                            "source_file": input_path.name,
                            "record_id": row.get("record_id"),
                            "reason": "thread fetch missing thread_id",
                        }
                    )
                    continue

    normalized_rows.sort(
        key=lambda item: (
            item.get("create_time") or "",
            item.get("message_id") or "",
            item.get("message_scope") or "",
        )
    )

    # de-duplicate by message_id + scope, keeping first sorted occurrence
    seen: set[tuple[str, str]] = set()
    deduped_rows: list[dict] = []
    for row in normalized_rows:
        key = (row.get("message_id") or "", row.get("message_scope") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped_rows.append(row)

    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        for row in deduped_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "input_files": [path.name for path in used_files],
        "fallback_mode": fallback_mode,
        "output_file": OUTPUT_FILE.name,
        "normalized_rows": len(deduped_rows),
        "skipped": skipped,
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
