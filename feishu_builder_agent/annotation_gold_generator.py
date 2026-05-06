from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas import (
    validate_block_annotations,
    validate_case_spec,
    validate_coverage_spec,
    validate_event_annotations,
    validate_memory_failure_blueprint,
    validate_query_benchmark,
    validate_state_trajectory,
    validate_story_beats,
    validate_conversation_plan_v3,
    validate_collected_messages_v3,
)


POSITIVE_ROLES = {
    "target_fact_turn",
    "evidence_anchor_turn",
    "stale_state_turn",
    "supersession_turn",
    "final_current_state_turn",
    "current_state_disambiguation_turn",
    "dependency_link_turn",
    "dependency_update_turn",
}
REVIEW_ROLES = {"ambiguous_claim_turn", "hearsay_turn", "weak_commitment_turn"}
REJECT_ROLES = {"shared_actor_turn", "memory_pollution_turn", "distractor_task_turn"}
NO_EVENT_ROLES = {"ordinary_ack_turn", "context_only_turn", "probe_setup_turn"}


def _normalize(text: Any) -> str:
    return str(text or "").strip()


def _quote_supported(row: dict[str, Any], quote: str) -> bool:
    return _normalize(quote) and _normalize(quote) in _normalize(row.get("content_text"))


def _event_type_hint(role: str, state_field_hints: list[str]) -> str:
    if role in {"stale_state_turn", "supersession_turn", "final_current_state_turn"}:
        return "status_event"
    if role in {"dependency_link_turn", "dependency_update_turn"}:
        return "rationale_event"
    if state_field_hints and any(field in {"owner", "负责人"} for field in state_field_hints):
        return "commitment_event"
    if state_field_hints and any(field in {"date", "timeline", "发布时间", "目标时间"} for field in state_field_hints):
        return "time_event"
    return "conclusion_event"


def _looks_like_no_event_text(text: str) -> bool:
    normalized = _normalize(text)
    if any(token in normalized for token in ["负责人", "当前", "最终", "改成", "定为", "FEISHU-"]):
        return False
    return (
        len(normalized) <= 16
        or any(token in normalized for token in ["收到", "好的", "了解", "同步下", "看到了", "嗯", "ok", "OK"])
    )


def _looks_like_review_text(text: str) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in ["可能", "猜测", "听说", "据说", "大概", "也许", "估计"])


def _looks_like_distractor_text(text: str) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in ["FEISHU-999", "无关任务", "别的任务", "另一个任务"])


def _expected_verdict_for_row(row: dict[str, Any]) -> tuple[str, str]:
    role = row["benchmark_role"]
    text = _normalize(row.get("content_text"))
    if role in POSITIVE_ROLES:
        return "positive_event", "verified"
    if role in REVIEW_ROLES:
        return ("review_event", "needs_review") if _looks_like_review_text(text) else ("positive_event", "verified")
    if role in REJECT_ROLES:
        return ("review_event", "rejected") if _looks_like_distractor_text(text) else ("positive_event", "verified")
    if role in NO_EVENT_ROLES:
        return ("negative_no_event", "no_event") if _looks_like_no_event_text(text) else ("positive_event", "verified")
    return "positive_event", "verified"


def _claim_text(row: dict[str, Any], kind: str, verdict: str) -> str:
    text = _normalize(row.get("content_text"))
    if kind == "negative_no_event":
        return f"该消息不应生成 target-task verified event：{text}"
    if verdict == "rejected":
        return f"该消息属于 distractor 或 memory pollution，不应进入 target-task verified state：{text}"
    if verdict == "needs_review":
        return f"该消息只形成待审查 claim，不能直接当 verified current state：{text}"
    return text


def generate_annotation_gold(
    *,
    case_spec: dict[str, Any],
    memory_failure_blueprint: dict[str, Any],
    state_trajectory: dict[str, Any],
    coverage_spec: dict[str, Any],
    story_beats: dict[str, Any],
    conversation_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    case_spec = validate_case_spec(case_spec)
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    trajectory = validate_state_trajectory(state_trajectory)
    validate_coverage_spec(coverage_spec)
    validate_story_beats(story_beats)
    validate_conversation_plan_v3(conversation_plan)
    messages = validate_collected_messages_v3(collected_messages)

    trap_by_id = {trap["trap_id"]: trap for trap in blueprint["traps"]}
    transitions_by_trap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transition in trajectory["transitions"]:
        transitions_by_trap[transition["trap_id"]].append(transition)

    event_annotations: list[dict[str, Any]] = []
    annotations_by_trap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(messages, start=1):
        annotation_kind, expected_verdict = _expected_verdict_for_row(row)
        evidence_quote = _normalize(row["content_text"])
        if not _quote_supported(row, evidence_quote):
            raise ValueError(f"collected_messages content is not self-supporting for evidence: {row['message_id']}")
        annotation = {
            "annotation_id": f"ann_{index:03d}",
            "annotation_kind": annotation_kind,
            "expected_verdict": expected_verdict,
            "failure_mode": row["memory_failure_mode"],
            "source_trap_id": row["memory_trap"],
            "benchmark_role": row["benchmark_role"],
            "topic_key": row["topic_key"],
            "evidence_message_id": row["message_id"],
            "evidence_turn_id": row["turn_id"],
            "evidence_quote": evidence_quote,
            "claim_text": _claim_text(row, annotation_kind, expected_verdict),
            "event_type_hint": _event_type_hint(row["benchmark_role"], row.get("state_field_hints") or []),
            "state_field": (row.get("state_field_hints") or [""])[0] if row.get("state_field_hints") else "",
            "task_scope": "target_task" if expected_verdict in {"verified", "needs_review"} else "distractor",
            "forbidden_for_current_task": expected_verdict in {"rejected", "no_event"},
        }
        event_annotations.append(annotation)
        annotations_by_trap[row["memory_trap"]].append(annotation)
    event_annotations = validate_event_annotations(event_annotations)

    blocks: list[dict[str, Any]] = []
    for trap in blueprint["traps"]:
        trap_annotations = annotations_by_trap.get(trap["trap_id"], [])
        verified_ids = [item["annotation_id"] for item in trap_annotations if item["expected_verdict"] == "verified"]
        if not verified_ids:
            continue
        current_state = []
        for transition in transitions_by_trap.get(trap["trap_id"], []):
            if transition["is_final_current_state"]:
                supporting = [
                    item["annotation_id"]
                    for item in trap_annotations
                    if item["state_field"] == transition["state_field"] and item["expected_verdict"] == "verified"
                ]
                stale = [
                    item["annotation_id"]
                    for item in trap_annotations
                    if item["state_field"] == transition["state_field"] and item["annotation_id"] not in supporting
                ]
                if supporting:
                    current_state.append(
                        {
                            "state_field": transition["state_field"],
                            "value": transition["to_value"] or transition["creates_stale_state"] or "已更新",
                            "supporting_event_annotation_ids": supporting,
                            "stale_event_annotation_ids": stale,
                        }
                    )
        blocks.append(
            {
                "block_annotation_id": f"block_ann_{len(blocks)+1:03d}",
                "source_trap_id": trap["trap_id"],
                "failure_mode": trap["failure_mode"],
                "topic_key": trap_annotations[0]["topic_key"],
                "topic_title": trap["trap_mechanism"],
                "gold_event_annotation_ids": verified_ids,
                "current_state": current_state,
                "distinguishes_historical_from_current": bool(current_state),
                "expected_projector_focus": "current_state" if current_state else "evidence_grouping",
            }
        )
    block_annotations = validate_block_annotations(
        {
            "case_id": case_spec["case_id"],
            "task_id": case_spec["task_id"],
            "blocks": blocks,
        }
    )

    queries: list[dict[str, Any]] = []
    for trap in blueprint["traps"]:
        trap_annotations = annotations_by_trap.get(trap["trap_id"], [])
        required_event_ids = [
            item["annotation_id"]
            for item in trap_annotations
            if item["expected_verdict"] in {"verified", "needs_review"}
        ]
        must_cite_message_ids = [
            item["evidence_message_id"]
            for item in trap_annotations
            if item["expected_verdict"] == "verified"
        ][:2]
        expected_current_state = []
        stale_values: list[str] = []
        typed_payload = trap["typed_payload"]
        if typed_payload.get("payload_type") == "static_memory_stale_state_payload":
            track = typed_payload["required_state_track"]
            expected_current_state.append({"state_field": track["field"], "value": track["final_current_state"]})
            stale_values = list(track["stale_states"])
        if typed_payload.get("payload_type") == "dependency_propagation_failure_payload":
            expected_current_state.append(
                {
                    "state_field": typed_payload["impacted_field"],
                    "value": typed_payload["expected_missed_update"],
                }
            )
        expected_points = [trap["expected_task_wiki_success"]]
        if typed_payload.get("payload_type") == "static_memory_stale_state_payload":
            expected_points.append(f"最终 current state 是 {typed_payload['required_state_track']['final_current_state']}")
        if typed_payload.get("payload_type") == "unverifiable_summary_claim_payload":
            expected_points.append(f"需要区分 claim 是否 verified：{typed_payload['target_claim']}")
        if typed_payload.get("payload_type") == "personal_memory_pollution_payload":
            expected_points.append("需要隔离 distractor task 和记忆污染，不把无关任务写进当前任务答案")
        if typed_payload.get("payload_type") == "dependency_propagation_failure_payload":
            expected_points.append(f"需要说明依赖链如何影响 {typed_payload['impacted_field']}")
        forbidden_claims = [trap["expected_openclaw_failure"]]
        for query_index, query_text in enumerate(trap["common"]["probe_queries"], start=1):
            queries.append(
                {
                    "query_id": f"q_{len(queries)+1:03d}",
                    "query_family": trap["failure_mode"],
                    "query_text": query_text,
                    "source_trap_id": trap["trap_id"],
                    "failure_mode": trap["failure_mode"],
                    "expected_openclaw_failure": trap["expected_openclaw_failure"],
                    "expected_answer_points": expected_points,
                    "forbidden_claims": forbidden_claims,
                    "required_event_annotation_ids": required_event_ids,
                    "required_block_topics": list(
                        {
                            block["topic_key"]
                            for block in blocks
                            if block["source_trap_id"] == trap["trap_id"]
                        }
                    ),
                    "expected_current_state": expected_current_state,
                    "stale_values": stale_values,
                    "citation_expectation": {
                        "min_citations": 1,
                        "must_cite_message_ids": must_cite_message_ids[: max(1, query_index)],
                    },
                }
            )
    query_benchmark = validate_query_benchmark(
        {
            "case_id": case_spec["case_id"],
            "task_id": case_spec["task_id"],
            "queries": queries,
        }
    )
    return {
        "event_annotations": event_annotations,
        "block_annotations": block_annotations,
        "query_benchmark": query_benchmark,
    }
