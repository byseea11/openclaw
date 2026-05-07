from __future__ import annotations

from typing import Any

from ..schemas import validate_query_benchmark


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _unique_ids(values: list[Any], *, limit: int = 8) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        message_id = _as_text(value)
        if not message_id or message_id in seen:
            continue
        output.append(message_id)
        seen.add(message_id)
        if len(output) >= limit:
            break
    return output


def _semantic_query_support(semantic_gold: dict[str, Any] | None) -> dict[str, list[str]]:
    support: dict[str, list[str]] = {}
    if not isinstance(semantic_gold, dict):
        return support
    for row in semantic_gold.get("expected_query_answers") or []:
        if not isinstance(row, dict):
            continue
        query_id = _as_text(row.get("query_id"))
        ids = _unique_ids(list(row.get("required_supporting_message_ids") or []))
        if query_id and ids:
            support[query_id] = ids
    return support


def _keywords(text: str) -> list[str]:
    lower = text.lower()
    candidates = [
        "升级窗口",
        "窗口",
        "正式",
        "纪要",
        "blocker",
        "network",
        "config",
        "drift",
        "回滚",
        "备份",
        "个人",
        "偏好",
        "carol",
        "frank",
        "jack",
    ]
    return [keyword for keyword in candidates if keyword.lower() in lower]


def _evidence_role(row: dict[str, Any], query_text: str) -> str:
    haystack = " ".join(
        _as_text(row.get(key))
        for key in (
            "purpose",
            "turn_kind",
            "evidence_text",
            "task_relevance_boundary",
            "official_file_ref",
            "private_info_ref",
        )
    )
    if _as_text(row.get("private_info_ref")) or "个人" in haystack or "偏好" in haystack:
        return "private_context" if "个人" in query_text or "偏好" in query_text or "是否影响" in query_text else "distractor"
    if _as_text(row.get("official_file_ref")) or "正式" in haystack or "纪要" in haystack:
        return "official_current"
    if "纠正" in haystack or "更正" in haystack or "以正式" in haystack:
        return "supporting_correction"
    if "旧" in haystack or "历史" in haystack or "过期" in haystack:
        return "stale_or_superseded"
    return "official_current"


def _fallback_query_support(
    *,
    probe: dict[str, Any],
    annotation_gold_rows: list[dict[str, Any]],
    limit: int = 8,
) -> tuple[list[str], dict[str, str]]:
    query_text = _as_text(probe.get("query"))
    expected_text = _as_text(probe.get("expected_good_behavior"))
    keywords = _keywords(f"{query_text} {expected_text}")
    scored: list[tuple[int, int, dict[str, Any], str]] = []
    for index, row in enumerate(annotation_gold_rows):
        evidence_text = _as_text(row.get("evidence_text") or row.get("message_text"))
        searchable = " ".join(
            [
                evidence_text,
                _as_text(row.get("purpose")),
                _as_text(row.get("task_relevance_boundary")),
                _as_text(row.get("turn_kind")),
            ]
        ).lower()
        role = _evidence_role(row, query_text)
        score = sum(2 for keyword in keywords if keyword.lower() in searchable)
        if role == "official_current":
            score += 3
        elif role == "supporting_correction":
            score += 2
        elif role == "private_context":
            score += 1
        elif role in {"distractor", "stale_or_superseded"}:
            score -= 4
        if score > 0:
            scored.append((score, -index, row, role))
    selected = sorted(scored, reverse=True)[:limit]
    ids = _unique_ids([row.get("message_id") for _, _, row, _ in selected], limit=limit)
    roles = {
        _as_text(row.get("message_id")): role
        for _, _, row, role in selected
        if _as_text(row.get("message_id")) in ids
    }
    return ids, roles


def build_query_benchmark(
    *,
    case_id: str,
    family_id: str,
    story_plan: dict[str, Any],
    annotation_gold_rows: list[dict[str, Any]],
    semantic_gold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic_support = _semantic_query_support(semantic_gold)
    queries: list[dict[str, Any]] = []
    for index, probe in enumerate(story_plan["planned_probe_queries"], start=1):
        query_id = f"{case_id}_query_{index:03d}"
        supporting_ids = semantic_support.get(query_id)
        roles: dict[str, str] = {}
        if supporting_ids:
            annotation_by_id = {
                _as_text(row.get("message_id")): row
                for row in annotation_gold_rows
                if _as_text(row.get("message_id"))
            }
            roles = {
                message_id: _evidence_role(annotation_by_id.get(message_id, {}), _as_text(probe["query"]))
                for message_id in supporting_ids
            }
        else:
            supporting_ids, roles = _fallback_query_support(
                probe=probe,
                annotation_gold_rows=annotation_gold_rows,
            )
        queries.append(
            {
                "query_id": query_id,
                "query": probe["query"],
                "expected_good_behavior": probe["expected_good_behavior"],
                "supporting_message_ids": supporting_ids,
                "evidence_roles": roles,
            }
        )
    payload = {
        "case_id": case_id,
        "family_id": family_id,
        "queries": queries,
    }
    return validate_query_benchmark(payload)
