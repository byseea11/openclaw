from __future__ import annotations

import re
from typing import Any

from .llm_client import DisabledLLMClient, build_llm_client_from_env


_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,24}")
_MARKDOWN_LINK_RE = re.compile(r"\[\[[^|]+\|([^\]]+)\]\]")
_SEMANTIC_JUDGE_DISABLED_REASON: str | None = None


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\r\n", "\n")).strip()


def keyword_set(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(normalize_text(text))}


def lexical_overlap(left: str, right: str) -> float:
    left_set = keyword_set(left)
    right_set = keyword_set(right)
    if not left_set or not right_set:
        return 0.0
    intersect = left_set & right_set
    union = left_set | right_set
    return len(intersect) / max(1, len(union))


def markdown_link_targets(text: str) -> list[str]:
    return [match.group(1) for match in _MARKDOWN_LINK_RE.finditer(str(text or ""))]


def load_active_llm_client():
    global _SEMANTIC_JUDGE_DISABLED_REASON
    if _SEMANTIC_JUDGE_DISABLED_REASON is not None:
        return None
    client = build_llm_client_from_env()
    return None if isinstance(client, DisabledLLMClient) else client


def _fallback_semantic_judge(query: dict[str, Any], answer_text: str, citations: list[str]) -> dict[str, Any]:
    expected_points = [normalize_text(item) for item in query.get("expected_answer_points") or [] if normalize_text(item)]
    forbidden = [normalize_text(item) for item in query.get("forbidden_claims") or [] if normalize_text(item)]
    normalized_answer = normalize_text(answer_text)
    covered = [point for point in expected_points if point and point in normalized_answer]
    forbidden_hits = [item for item in forbidden if item and item in normalized_answer]
    stale_hits = [item for item in (query.get("stale_values") or []) if normalize_text(item) and normalize_text(item) in normalized_answer]
    score = 0.0
    if expected_points:
        score = len(covered) / len(expected_points)
    if forbidden_hits or stale_hits:
      score = max(0.0, score - 0.5)
    return {
        "judge_mode": "heuristic_fallback",
        "answer_point_coverage": round(score, 4),
        "faithfulness": 0.0 if forbidden_hits else min(1.0, round(score + (0.2 if citations else 0.0), 4)),
        "unsupported_claims": forbidden_hits,
        "stale_answer": bool(stale_hits),
        "cross_source_reasoning": len(citations) >= 2,
        "notes": [
            *([f"missing:{point}" for point in expected_points if point not in covered]),
            *([f"forbidden:{item}" for item in forbidden_hits]),
            *([f"stale:{item}" for item in stale_hits]),
        ],
    }


def semantic_judge(query: dict[str, Any], answer_text: str, citations: list[str]) -> dict[str, Any]:
    global _SEMANTIC_JUDGE_DISABLED_REASON
    llm_client = load_active_llm_client()
    if llm_client is None:
        return _fallback_semantic_judge(query, answer_text, citations)
    try:
        return llm_client.generate_json(
            system_prompt=(
                "You are a strict benchmark evaluator for task-memory QA. "
                "Return one JSON object only. "
                "Judge answer point coverage, faithfulness, unsupported claims, stale answer, and cross-source reasoning."
            ),
            user_prompt=str(
                {
                    "query": query.get("query_text"),
                    "expected_answer_points": query.get("expected_answer_points") or [],
                    "forbidden_claims": query.get("forbidden_claims") or [],
                    "expected_current_state": query.get("expected_current_state") or [],
                    "stale_values": query.get("stale_values") or [],
                    "answer_text": answer_text,
                    "citations": citations,
                    "output_schema": {
                        "judge_mode": "llm_semantic",
                        "answer_point_coverage": "0-1 float",
                        "faithfulness": "0-1 float",
                        "unsupported_claims": ["list of strings"],
                        "stale_answer": "boolean",
                        "cross_source_reasoning": "boolean",
                        "notes": ["list of short strings"],
                    },
                }
            ),
        )
    except Exception:
        _SEMANTIC_JUDGE_DISABLED_REASON = "semantic_judge_live_failed"
        return _fallback_semantic_judge(query, answer_text, citations)


def deterministic_answer_checks(
    query: dict[str, Any],
    answer_text: str,
    citations: list[str],
    *,
    citation_message_ids: list[str] | None = None,
) -> dict[str, Any]:
    normalized_answer = normalize_text(answer_text)
    required_topics = [normalize_text(item) for item in query.get("required_block_topics") or [] if normalize_text(item)]
    expected_points = [normalize_text(item) for item in query.get("expected_answer_points") or [] if normalize_text(item)]
    forbidden = [normalize_text(item) for item in query.get("forbidden_claims") or [] if normalize_text(item)]
    stale_values = [normalize_text(item) for item in query.get("stale_values") or [] if normalize_text(item)]
    required_hits = [item for item in required_topics if item in normalized_answer]
    forbidden_hits = [item for item in forbidden if item in normalized_answer]
    stale_hits = [item for item in stale_values if item in normalized_answer]
    citation_expectation = query.get("citation_expectation") or {}
    min_citations = int(citation_expectation.get("min_citations") or 0)
    must_cite_ids = [str(item) for item in citation_expectation.get("must_cite_message_ids") or [] if str(item).strip()]
    actual_ids = citation_message_ids or []
    must_cite_hits = [item for item in must_cite_ids if item in actual_ids]
    return {
        "required_block_hit": len(required_hits) >= max(1, len(required_topics)) if required_topics else True,
        "expected_point_hit_count": sum(1 for item in expected_points if item in normalized_answer),
        "citation_traceability": len(citations) >= min_citations and all(item in actual_ids for item in must_cite_ids),
        "forbidden_claim_hit": forbidden_hits,
        "stale_current_state_misuse": stale_hits,
        "unknown_or_no_event_hallucination": bool(not citations and expected_points),
        "must_cite_hits": must_cite_hits,
    }


def select_relevant_messages(collected_messages: list[dict[str, Any]], query_text: str, *, limit: int = 5) -> list[dict[str, Any]]:
    scored = []
    for row in collected_messages:
        text = normalize_text(row.get("content_text"))
        if not text:
            continue
        score = lexical_overlap(query_text, text)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1].get("sequence_no", 0)))
    return [row for _, row in scored[:limit]]


def build_raw_rag_answer(collected_messages: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    query_text = normalize_text(query.get("query_text"))
    rows = select_relevant_messages(collected_messages, query_text)
    answer_lines = [normalize_text(row.get("content_text")) for row in rows]
    citations = [str(row.get("message_id")) for row in rows if str(row.get("message_id") or "").strip()]
    return {
        "answer_text": "；".join(answer_lines[:3]) if answer_lines else "未检索到足够相关的原始消息。",
        "citations": citations,
        "retrieved_messages": [row.get("message_id") for row in rows],
    }


def build_task_wiki_answer(
    task_wiki_state: dict[str, Any],
    session_events: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    query_text = normalize_text(query.get("query_text"))
    sections = task_wiki_state.get("sections") if isinstance(task_wiki_state, dict) else {}
    related_blocks = task_wiki_state.get("related_blocks") if isinstance(task_wiki_state, dict) else []
    candidates: list[dict[str, Any]] = []
    if isinstance(sections, dict):
        for items in sections.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    candidates.append(item)
    if isinstance(related_blocks, list):
        for item in related_blocks:
            if isinstance(item, dict):
                candidates.append(item)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in candidates:
        text = normalize_text(item.get("claim") or item.get("summary") or item.get("topic_title"))
        score = lexical_overlap(query_text, text)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda entry: -entry[0])
    selected = [item for _, item in scored[:4]]
    answer_lines = [
        normalize_text(item.get("claim") or item.get("summary") or item.get("topic_title"))
        for item in selected
        if normalize_text(item.get("claim") or item.get("summary") or item.get("topic_title"))
    ]
    citations = []
    citation_message_ids = []
    for item in selected:
        ref = normalize_text(item.get("event_ref") or item.get("event_path") or item.get("block_link"))
        if ref:
            citations.extend(markdown_link_targets(ref) or [ref])
        event_id = normalize_text(item.get("event_id"))
        if event_id:
            for event in session_events:
                if normalize_text(event.get("event_id")) == event_id:
                    message_id = normalize_text(event.get("core_entry_id"))
                    if message_id:
                        citation_message_ids.append(message_id)
                    break
    if not answer_lines and isinstance(task_wiki_state, dict):
        summary = normalize_text(task_wiki_state.get("current_summary"))
        if summary:
            answer_lines = [summary]
    return {
        "answer_text": "；".join(answer_lines[:3]) if answer_lines else "当前 Task Wiki 未给出足够确定的答案。",
        "citations": citations,
        "citation_message_ids": citation_message_ids,
    }
