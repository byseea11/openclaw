"""Helpers for upgrading CrossDeptMem samples into Feishu-like raw messages.

This keeps the existing semantic `history` / `queries` gold data intact while
adding a more realistic chat/message layer for adapters to feed into OpenClaw.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


def _slug(value: str) -> str:
    lowered = value.lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_") or "item"


def _display_name(actor: str) -> str:
    local_part = actor.split("@", 1)[0].strip()
    return local_part[:1].upper() + local_part[1:] if local_part else actor


def _open_id(actor: str) -> str:
    return f"ou_{_slug(actor)}"


def _department_from_actor(actor: str) -> str:
    suffix = actor.split("@", 1)[1].strip().lower() if "@" in actor else ""
    return {
        "pm": "product",
        "dev": "dev",
        "ops": "ops",
        "security": "security",
        "marketing": "marketing",
        "dba": "dba",
        "finance": "finance",
    }.get(suffix, suffix or "unknown")


def _primary_ref(item: dict[str, Any]) -> str:
    entities = item.get("entities") or []
    if isinstance(entities, list):
        for value in entities:
            if isinstance(value, str) and value:
                return value
    events = item.get("events") or []
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                subject = event.get("subject")
                if isinstance(subject, str) and subject:
                    return subject
    return "chat"


def _message_type(item: dict[str, Any]) -> str:
    events = item.get("events") or []
    event_types = {
        event.get("type")
        for event in events
        if isinstance(event, dict) and isinstance(event.get("type"), str)
    }
    if "approval_status_updated" in event_types:
        return "interactive"
    if "task_created" in event_types or "approval_created" in event_types:
        return "post"
    return "text"


def _content_json(content_text: str, message_type: str) -> dict[str, Any]:
    if message_type == "interactive":
        return {
            "card_type": "approval_update",
            "summary": content_text,
        }
    if message_type == "post":
        return {
            "title": "协作更新",
            "body": content_text,
        }
    return {"text": content_text}


def _actor_directory(sample: dict[str, Any]) -> dict[str, dict[str, str]]:
    actors = list(sample.get("actors") or [])
    directory: dict[str, dict[str, str]] = {}
    for actor in actors:
        if isinstance(actor, str) and actor:
            directory[actor] = {
                "open_id": _open_id(actor),
                "display_name": _display_name(actor),
                "department": _department_from_actor(actor),
            }
    return directory


def _pick_actor_by_department(
    actor_directory: dict[str, dict[str, str]],
    department: str,
    exclude_actor: str,
) -> str | None:
    for actor, info in actor_directory.items():
        if actor == exclude_actor:
            continue
        if info.get("department") == department:
            return actor
    return None


def _mention_token(actor: str, actor_directory: dict[str, dict[str, str]]) -> str:
    info = actor_directory.get(actor)
    return f"@{info['display_name']}" if info else f"@{_display_name(actor)}"


def _entity_with_prefix(item: dict[str, Any], prefix: str) -> str | None:
    entities = item.get("entities") or []
    if isinstance(entities, list):
        for value in entities:
            if isinstance(value, str) and value.startswith(prefix):
                return value
    return None


def _task_subject_from_events(item: dict[str, Any]) -> str | None:
    events = item.get("events") or []
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                subject = event.get("subject")
                if isinstance(subject, str) and subject.startswith("task:"):
                    return subject
    return _entity_with_prefix(item, "task:")


def _task_subject_for_event_type(item: dict[str, Any], event_type: str) -> str | None:
    events = item.get("events") or []
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and event.get("type") == event_type:
                subject = event.get("subject")
                if isinstance(subject, str) and subject.startswith("task:"):
                    return subject
    return None


def _event_types(item: dict[str, Any]) -> set[str]:
    events = item.get("events") or []
    return {
        event.get("type")
        for event in events
        if isinstance(event, dict) and isinstance(event.get("type"), str)
    }


def _mention_actors(
    sender_actor: str,
    actor_directory: dict[str, dict[str, str]],
    event_types: set[str],
) -> list[str]:
    mention_candidates: list[str] = []
    if "task_created" in event_types:
        candidate = _pick_actor_by_department(actor_directory, "dev", sender_actor)
        if candidate:
            mention_candidates.append(candidate)
    if "approval_created" in event_types:
        candidate = _pick_actor_by_department(actor_directory, "ops", sender_actor) or _pick_actor_by_department(
            actor_directory,
            "security",
            sender_actor,
        )
        if candidate:
            mention_candidates.append(candidate)
    if "blocked" in event_types:
        candidate = (
            _pick_actor_by_department(actor_directory, "ops", sender_actor)
            or _pick_actor_by_department(actor_directory, "security", sender_actor)
            or _pick_actor_by_department(actor_directory, "dev", sender_actor)
        )
        if candidate:
            mention_candidates.append(candidate)
    if "unblocked" in event_types or "approval_status_updated" in event_types:
        candidate = _pick_actor_by_department(actor_directory, "dev", sender_actor)
        if candidate:
            mention_candidates.append(candidate)
    seen: set[str] = set()
    result: list[str] = []
    for candidate in mention_candidates:
        if candidate != sender_actor and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def _render_content_text(
    item: dict[str, Any],
    message_type: str,
    sender_actor: str,
    actor_directory: dict[str, dict[str, str]],
) -> str:
    original = str(item.get("content") or "").strip()
    event_types = _event_types(item)
    task_ref = (
        _task_subject_for_event_type(item, "unblocked")
        or _task_subject_for_event_type(item, "blocked")
        or _task_subject_for_event_type(item, "owner_changed")
        or _task_subject_for_event_type(item, "next_action_set")
        or _task_subject_for_event_type(item, "task_created")
        or _task_subject_for_event_type(item, "stage_changed")
        or _task_subject_from_events(item)
    )
    task_name = task_ref.split(":", 1)[1] if task_ref and ":" in task_ref else None
    approval_ref = _entity_with_prefix(item, "approval:")
    blocker_ref = _entity_with_prefix(item, "blocker:")
    completed_task_ref = _task_subject_for_event_type(item, "stage_changed")
    dependency_task_ref = None
    entities = item.get("entities") or []
    if isinstance(entities, list):
        for entity in entities:
            if (
                isinstance(entity, str)
                and entity.startswith("task:")
                and entity != task_ref
            ):
                dependency_task_ref = entity
                break
    mentions = _mention_actors(sender_actor, actor_directory, event_types)
    mention_prefix = " ".join(_mention_token(actor, actor_directory) for actor in mentions)
    prefix = f"{mention_prefix} " if mention_prefix else ""

    if "task_created" in event_types and task_name:
        return (
            f"{prefix}先拉个线程，{task_name} 这个需求我先建单了。"
            "这周想推进上线，麻烦帮忙评估一下工作量。"
        )
    if "approval_created" in event_types and approval_ref:
        approval_name = approval_ref.split(":", 1)[1]
        return f"{prefix}{approval_name} 这个审批我先提了，大家有空帮忙看下，别卡太久。"
    if "approval_status_updated" in event_types and approval_ref:
        approval_name = approval_ref.split(":", 1)[1]
        tail = ""
        if dependency_task_ref:
            tail = f" 不过还得先把 {dependency_task_ref.split(':', 1)[1]} 处理掉。"
        return f"{prefix}审批卡片更新：{approval_name} 已通过。{tail}".strip()
    if "blocked" in event_types and task_name and approval_ref:
        approval_name = approval_ref.split(":", 1)[1]
        return (
            f"{prefix}{task_name} 我这边先评完了，当前还是卡在 {approval_name}。"
            "审批过了我再继续往下推。"
        )
    if "blocked" in event_types and task_name and dependency_task_ref:
        dependency_name = dependency_task_ref.split(":", 1)[1]
        return (
            f"{prefix}{task_name} 这边先别往下发了，现在还依赖 {dependency_name}。"
            "那边处理完我再同步进度。"
        )
    if "blocked" in event_types and task_name and blocker_ref:
        blocker_name = blocker_ref.split(":", 1)[1]
        return f"{prefix}{task_name} 暂时先卡住，缺 {blocker_name} 这块补充。"
    if "unblocked" in event_types and task_name:
        done_prefix = ""
        if completed_task_ref and completed_task_ref != task_ref:
            dependency_name = completed_task_ref.split(":", 1)[1]
            done_prefix = f"{dependency_name} 这边已经 done 了，"
        elif dependency_task_ref:
            dependency_name = dependency_task_ref.split(":", 1)[1]
            done_prefix = f"{dependency_name} 这边已经 done 了，"
        return f"{prefix}{done_prefix}{task_name} 可以继续推进了。"
    if "stage_changed" in event_types and task_name:
        return f"{prefix}{task_name} 状态我先更新了，大家按最新进度往下走。"
    if "owner_changed" in event_types and task_name:
        return f"{prefix}{task_name} 我先接着跟一下，这个线程后面我来推进。"
    if "next_action_set" in event_types and task_name:
        return f"{prefix}{task_name} 我先记个 next step，避免后面断线。"
    if message_type == "interactive":
        return f"{prefix}{original}".strip()
    if message_type == "post":
        return f"{prefix}{original}".strip()
    return f"{prefix}{original}".strip()


def build_feishu_messages(sample: dict[str, Any]) -> list[dict[str, Any]]:
    history = list(sample.get("history") or [])
    sample_id = str(sample.get("sample_id") or "sample")
    actor_directory = _actor_directory(sample)
    thread_roots: dict[str, str] = {}
    thread_last_message: dict[str, str] = {}
    messages: list[dict[str, Any]] = []

    for index, item in enumerate(history, start=1):
        actor = str(item.get("actor") or "unknown")
        department = str(item.get("department") or "unknown")
        content_text = str(item.get("content") or "").strip()
        if not content_text:
            continue

        primary_ref = _primary_ref(item)
        thread_key = _slug(primary_ref)
        thread_id = f"omt_{_slug(sample_id)}_{thread_key}"
        message_id = f"om_{_slug(sample_id)}_{index:03d}"
        root_id = thread_roots.get(thread_id)
        if root_id is None:
            thread_roots[thread_id] = message_id
            root_id = message_id
        parent_id = thread_last_message.get(thread_id)
        thread_last_message[thread_id] = message_id
        message_type = _message_type(item)
        mention_actors = _mention_actors(actor, actor_directory, _event_types(item))
        content_text = _render_content_text(item, message_type, actor, actor_directory)

        messages.append(
            {
                "message_id": message_id,
                "chat_id": f"oc_{_slug(sample_id)}",
                "chat_type": "group",
                "thread_id": thread_id,
                "root_id": root_id,
                "parent_id": None if parent_id == message_id else parent_id,
                "created_at": item.get("timestamp"),
                "message_type": message_type,
                "sender": {
                    "open_id": _open_id(actor),
                    "display_name": _display_name(actor),
                    "department": department,
                    "actor_ref": actor,
                },
                "mentions": [
                    {
                        "open_id": actor_directory[target]["open_id"],
                        "display_name": actor_directory[target]["display_name"],
                        "actor_ref": target,
                    }
                    for target in mention_actors
                    if target in actor_directory
                ],
                "content_text": content_text,
                "content_json": _content_json(content_text, message_type),
                "semantic_refs": {
                    "entities": item.get("entities", []),
                    "events": item.get("events", []),
                    "history_index": index - 1,
                },
            }
        )

    return messages


def enrich_cross_dept_sample(sample: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(sample)
    sample_id = str(sample.get("sample_id") or "sample")
    enriched["platform"] = "feishu"
    enriched["chat"] = {
        "chat_id": f"oc_{_slug(sample_id)}",
        "chat_type": "group",
        "chat_name": str(sample.get("scenario") or sample_id),
    }
    enriched["messages"] = build_feishu_messages(enriched)
    return enriched


def enrich_cross_dept_dataset(data: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(data)
    samples = list(enriched.get("samples") or [])
    enriched["samples"] = [
        enrich_cross_dept_sample(sample)
        for sample in samples
        if isinstance(sample, dict)
    ]
    return enriched
