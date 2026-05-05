from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas import validate_case_seed, validate_collected_messages, validate_complexity_report, validate_conversation_plan

SUPERSESSION_KEYWORDS = ("更新为", "改为", "修正为", "收紧为", "supersede")


def build_complexity_report(
    case_seed: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    seed = validate_case_seed(case_seed)
    plan = validate_conversation_plan(conversation_plan)
    messages = validate_collected_messages(collected_messages)
    thresholds = {
        "session_count": seed["complexity_profile"]["session_count_target"],
        "source_session_count": seed["complexity_profile"]["source_session_count_target"],
        "message_count": seed["complexity_profile"]["message_count_target"],
        "topic_count": seed["complexity_profile"]["topic_count_target"],
        "thread_reply_depth": seed["complexity_profile"]["thread_reply_depth_target"],
        "state_transition_count": seed["complexity_profile"]["state_transition_target"],
        "supersession_count": seed["complexity_profile"]["supersession_target"],
        "cross_source_revision_count": seed["complexity_profile"]["cross_source_revision_target"],
        "event_family_coverage": seed["complexity_profile"]["event_family_target"],
    }
    source_refs = {session["source_ref"] for session in plan["sessions"]}
    topic_counts: defaultdict[str, int] = defaultdict(int)
    event_types: set[str] = set()
    session_topic_sources: defaultdict[str, set[str]] = defaultdict(set)
    state_transition_count = 0
    supersession_count = 0
    thread_reply_depth = 0
    thread_counts: defaultdict[str, int] = defaultdict(int)
    for row in messages:
        topic_counts[row["topic_key"]] += 1
        session_topic_sources[row["topic_key"]].add(row["source_ref"])
        event_types.update(row["supports_event_types"])
        if row["state_transition"]:
            state_transition_count += 1
        if row.get("is_supersession") is True or str(row.get("supersedes_turn_id") or "").strip():
            supersession_count += 1
        elif any(keyword in str(row.get("state_transition") or "") for keyword in SUPERSESSION_KEYWORDS):
            supersession_count += 1
        elif any(keyword in str(row.get("semantic_payload") or "") for keyword in SUPERSESSION_KEYWORDS):
            supersession_count += 1
        if row["source_type"] == "thread":
            thread_counts[row["source_ref"]] += 1
    if thread_counts:
        thread_reply_depth = max(thread_counts.values())
    cross_source_revision_count = sum(1 for sources in session_topic_sources.values() if len(sources) >= 2)
    metrics = {
        "session_count": len(plan["sessions"]),
        "source_session_count": len(source_refs),
        "message_count": len(messages),
        "topic_count": len(plan["topic_registry"]),
        "avg_turns_per_topic": int(sum(topic_counts.values()) / max(len(topic_counts), 1)),
        "thread_reply_depth": thread_reply_depth,
        "state_transition_count": state_transition_count,
        "supersession_count": supersession_count,
        "cross_source_revision_count": cross_source_revision_count,
        "event_family_coverage": len(event_types),
    }
    failed_checks = [key for key, threshold in thresholds.items() if metrics.get(key, 0) < threshold]
    return validate_complexity_report(
        {
            "case_id": seed["case_id"],
            "passed": not failed_checks,
            "failed_checks": failed_checks,
            "metrics": metrics,
            "thresholds": thresholds,
        }
    )
