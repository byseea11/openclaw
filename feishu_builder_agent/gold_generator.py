from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .llm_client import JsonLLMClient
from .schemas import (
    ValidationError,
    validate_collected_messages,
    validate_conversation_plan,
    validate_expected_current_state,
    validate_expected_events,
    validate_expected_memory_blocks,
    validate_target_state,
)


EVENT_FIELD_REQUIREMENTS = {
    "conclusion_event": ["conclusion", "target"],
    "rationale_event": ["reason"],
    "objection_event": ["objection", "objector", "target"],
    "constraint_event": ["constraint", "target"],
    "commitment_event": ["owner", "action"],
    "status_event": ["status", "target"],
    "time_event": ["time_target", "time_value", "certainty"],
    "scope_event": ["scope_target"],
}

TIME_RE = re.compile(r"(\d{1,2}\s*月\s*\d{1,2}\s*日|今天|明天|后天|本周|下周|周[一二三四五六日天]|月底)")
PREFIX_RE = re.compile(r"^【[^/】]+/[^】]+】\s*")


def _normalize_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _strip_prefix(text: Any) -> str:
    return PREFIX_RE.sub("", _normalize_text(text), count=1).strip()


def _create_event_id(task_ref: str, source_session_id: str, ingest_version: int, event_type: str, core_entry_id: str, claim: str) -> str:
    digest = hashlib.sha1(
        f"{task_ref}|{source_session_id}|{ingest_version}|{event_type}|{core_entry_id}|{claim}".encode("utf-8")
    ).hexdigest()[:16]
    return f"evt_{digest}"


def _session_source_map(conversation_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    task_ref = f"task:{conversation_plan['task_id']}"
    output: dict[str, dict[str, Any]] = {}
    for session in conversation_plan["sessions"]:
        source_id = f"{session['source_type']}:{session['source_ref']}"
        output[session["session_id"]] = {
            "task_ref": task_ref,
            "source_session_id": f"{task_ref}::{source_id}",
            "source": {
                "source_type": session["source_type"],
                "source_id": source_id,
                "chat_id": session["chat_ref"],
                "thread_id": session["source_ref"] if session["source_type"] == "thread" else None,
                "root_id": session.get("root_turn_id"),
                "locator": session["source_ref"],
            },
        }
    return output


def _topic_title_map(target_state: dict[str, Any]) -> dict[str, str]:
    return {item["topic_key"]: item["topic_title"] for item in target_state["expected_block_targets"]}


def _extract_time_value(claim: str) -> str:
    match = TIME_RE.search(claim)
    return match.group(1) if match else "待定时间"


def _extract_certainty(claim: str) -> str:
    if re.search(r"暂定|目标|评估|窗口", claim):
        return "暂定"
    if re.search(r"确认|锁定|统一", claim):
        return "确认"
    return "已提及"


def _message_event_time(message: dict[str, Any]) -> str:
    raw = _normalize_text(message.get("message_create_time"))
    if raw.isdigit():
        try:
            stamp = int(raw)
            if len(raw) >= 13:
                stamp = stamp / 1000
            return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (ValueError, OSError):
            pass
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _deterministic_event_from_message(
    *,
    message: dict[str, Any],
    event_type: str,
    session_info: dict[str, Any],
    topic_title: str,
    ingest_version: int,
) -> dict[str, Any]:
    claim = _normalize_text(message["semantic_payload"])
    evidence_quote = _strip_prefix(message["content_text"]) or claim
    task_ref = session_info["task_ref"]
    event = {
        "task_ref": task_ref,
        "source_session_id": session_info["source_session_id"],
        "ingest_version": ingest_version,
        "event_type": event_type,
        "claim": claim,
        "core_entry_id": message["message_id"],
        "evidence_quote": evidence_quote,
        "context_quotes": [],
        "participants": [message["simulated_speaker"]["name"]],
        "event_time": _message_event_time(message),
        "source": session_info["source"],
        "confidence": 1.0,
        "verification": {
            "core_quote_found": True,
            "claim_supported_by_quote": True,
            "context_only_generation": False,
            "single_atomic_claim": True,
            "required_fields_complete": True,
            "no_unsupported_inference": True,
            "verdict": "gold",
        },
        "gold_meta": {
            "topic_key": message["topic_key"],
            "turn_id": message["turn_id"],
            "normalized_actor_id": message["normalized_actor_id"],
            "evidence_turn_id": message["message_id"],
            "expected_lifecycle": "active",
        },
    }
    if event_type == "conclusion_event":
        event["conclusion"] = claim
        event["target"] = topic_title
    elif event_type == "rationale_event":
        event["reason"] = claim
    elif event_type == "objection_event":
        event["objection"] = claim
        event["objector"] = message["simulated_speaker"]["name"]
        event["target"] = topic_title
    elif event_type == "constraint_event":
        event["constraint"] = claim
        event["target"] = topic_title
    elif event_type == "commitment_event":
        event["owner"] = message["simulated_speaker"]["name"]
        event["action"] = claim
    elif event_type == "status_event":
        event["status"] = claim
        event["target"] = topic_title
    elif event_type == "time_event":
        event["time_target"] = topic_title
        event["time_value"] = _extract_time_value(claim)
        event["certainty"] = _extract_certainty(claim)
    elif event_type == "scope_event":
        event["scope_target"] = topic_title
    event["event_id"] = _create_event_id(
        task_ref,
        session_info["source_session_id"],
        ingest_version,
        event_type,
        message["message_id"],
        claim,
    )
    return event


def _fallback_expected_events(
    target_state: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target = validate_target_state(target_state)
    plan = validate_conversation_plan(conversation_plan)
    messages = validate_collected_messages(collected_messages)
    session_map = _session_source_map(plan)
    topic_titles = _topic_title_map(target)
    events: list[dict[str, Any]] = []
    for ingest_version, message in enumerate(messages, start=1):
        session_info = session_map[message["session_id"]]
        topic_title = topic_titles.get(message["topic_key"], message["topic_key"])
        for event_type in message["supports_event_types"]:
            events.append(
                _deterministic_event_from_message(
                    message=message,
                    event_type=event_type,
                    session_info=session_info,
                    topic_title=topic_title,
                    ingest_version=ingest_version,
                )
            )
    return validate_expected_events(events)


def _build_llm_prompt_payload(
    target_state: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "target_state": target_state,
        "conversation_plan": {
            "case_id": conversation_plan["case_id"],
            "task_id": conversation_plan["task_id"],
            "topic_registry": conversation_plan["topic_registry"],
            "sessions": conversation_plan["sessions"],
        },
        "collected_messages": [
            {
                "turn_id": item["turn_id"],
                "session_id": item["session_id"],
                "topic_key": item["topic_key"],
                "speaker_ref": item["speaker_ref"],
                "normalized_actor_id": item["normalized_actor_id"],
                "message_id": item["message_id"],
                "content_text": _strip_prefix(item["content_text"]),
                "semantic_payload": item["semantic_payload"],
                "supports_event_types": item["supports_event_types"],
                "simulated_speaker": item["simulated_speaker"],
            }
            for item in collected_messages
        ],
    }


def _generate_expected_events_with_llm(
    target_state: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
    *,
    llm_client: JsonLLMClient,
) -> list[dict[str, Any]]:
    payload = _build_llm_prompt_payload(target_state, conversation_plan, collected_messages)
    system_prompt = (
        "You generate gold expected session_event records for a Feishu Task Wiki benchmark. "
        "Return one JSON object with key 'events'. Each event must match the Layer 2 session_event shape. "
        "Allowed event_type values are conclusion_event, rationale_event, objection_event, constraint_event, "
        "commitment_event, status_event, time_event, scope_event. "
        "Every event must contain event_id, task_ref, source_session_id, ingest_version, event_type, claim, "
        "core_entry_id, evidence_quote, context_quotes, participants, event_time, source, confidence, verification, gold_meta. "
        "Also include the required typed fields for each event_type. "
        "Use Simplified Chinese for natural-language fields. Do not invent facts beyond the provided collected_messages."
    )
    user_prompt = (
        "请把下面的 benchmark payload 转成 Layer 2 对齐的 gold expected_events。"
        "每条 event 必须能够回到 collected_messages 中对应的 turn/message 证据。"
        f"\n\nPayload:\n{payload}"
    )
    result = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
    return validate_expected_events(list(result.get("events") or []))


def _build_memory_blocks_and_current_state(
    target_state: dict[str, Any],
    conversation_plan: dict[str, Any],
    expected_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = validate_target_state(target_state)
    plan = validate_conversation_plan(conversation_plan)
    events = validate_expected_events(expected_events)
    block_rows: defaultdict[str, list[str]] = defaultdict(list)
    slot_map: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    latest_by_topic_slot: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        topic_key = event["gold_meta"]["topic_key"]
        slot_name = event["event_type"].replace("_event", "")
        block_rows[topic_key].append(event["event_id"])
        slot_map[topic_key][slot_name].append(event["event_id"])
        latest_by_topic_slot[(topic_key, slot_name)] = {
            "topic_key": topic_key,
            "slot": slot_name,
            "event_id": event["event_id"],
            "claim": event["claim"],
            "source_session_id": event["source_session_id"],
        }
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
    return expected_memory_blocks, expected_current_state


def generate_gold_artifacts(
    target_state: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    target = validate_target_state(target_state)
    plan = validate_conversation_plan(conversation_plan)
    messages = validate_collected_messages(collected_messages)
    if llm_client is None:
        expected_events = _fallback_expected_events(target, plan, messages)
        mode = "fallback"
    else:
        try:
            expected_events = _generate_expected_events_with_llm(target, plan, messages, llm_client=llm_client)
            mode = "live"
        except (Exception, ValidationError):
            expected_events = _fallback_expected_events(target, plan, messages)
            mode = "fallback"
    expected_memory_blocks, expected_current_state = _build_memory_blocks_and_current_state(target, plan, expected_events)
    return (
        {
            "target_state": target,
            "expected_events": expected_events,
            "expected_memory_blocks": expected_memory_blocks,
            "expected_current_state": expected_current_state,
        },
        mode,
    )
