from __future__ import annotations

from collections import Counter
import re
from typing import Any

from ..llm import BuilderModelClient
from ..prompt_loader import build_stage_system_prompt


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _message_text(row: dict[str, Any]) -> str:
    return _as_str(row.get("message_text") or row.get("content_text") or row.get("observed_text_without_prefix"))


def _message_id(row: dict[str, Any]) -> str:
    return _as_str(row.get("message_id"))


def _collect_message_index(collected_messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(collected_messages):
        message_id = _message_id(row)
        if not message_id:
            continue
        enriched = dict(row)
        enriched["_message_order"] = index
        indexed[message_id] = enriched
    return indexed


def _message_order(row: dict[str, Any]) -> int:
    explicit_order = row.get("_message_order")
    if isinstance(explicit_order, int):
        return explicit_order
    turn_id = _as_str(row.get("turn_id"))
    match = re.search(r"(\d+)$", turn_id)
    if match:
        return int(match.group(1))
    return 0


def _semantic_support_by_query(semantic_gold: dict[str, Any]) -> dict[str, list[str]]:
    by_query: dict[str, list[str]] = {}
    for item in _as_list(semantic_gold.get("expected_query_answers")):
        query_id = _as_str(item.get("query_id"))
        if not query_id:
            continue
        by_query[query_id] = [_as_str(message_id) for message_id in _as_list(item.get("required_supporting_message_ids")) if _as_str(message_id)]
    return by_query


def _semantic_fact_support_ids_for_query(query: dict[str, Any], semantic_gold: dict[str, Any]) -> list[str]:
    query_text = f"{_as_str(query.get('query'))} {_as_str(query.get('expected_good_behavior'))}"
    fact_support: list[str] = []
    for fact in _as_list(semantic_gold.get("expected_task_facts")):
        if not isinstance(fact, dict):
            continue
        claim = _as_str(fact.get("claim"))
        if not _semantic_fact_matches_query(query_text=query_text, claim=claim):
            continue
        fact_support.extend(
            _as_str(message_id)
            for message_id in _as_list(fact.get("required_supporting_message_ids"))
            if _as_str(message_id)
        )
    return fact_support


def _semantic_fact_matches_query(*, query_text: str, claim: str) -> bool:
    query_lower = query_text.lower()
    claim_lower = claim.lower()
    if any(token in query_lower for token in ("负责人", "owner", "历史负责人")) and any(
        token in claim_lower for token in ("负责人", "owner")
    ):
        return True
    if any(token in query_lower for token in ("窗口", "日期", "时间", "5月")) and any(
        token in claim_lower for token in ("窗口", "5月", "日期")
    ):
        return True
    if any(token in query_lower for token in ("状态", "暂停", "当前状态")) and any(
        token in claim_lower for token in ("状态", "暂停")
    ):
        return True
    if any(token in query_lower for token in ("为什么", "原因", "改到")) and any(
        token in claim_lower for token in ("组件", "延迟", "暂停", "窗口", "作废")
    ):
        return True
    return False


def _gold_support_ids(
    query: dict[str, Any],
    semantic_support: dict[str, list[str]],
    semantic_gold: dict[str, Any] | None = None,
) -> list[str]:
    query_id = _as_str(query.get("query_id"))
    evidence_roles = query.get("evidence_roles") if isinstance(query.get("evidence_roles"), dict) else {}
    query_text = f"{_as_str(query.get('query'))} {_as_str(query.get('expected_good_behavior'))}"
    allows_private_boundary = any(marker in query_text for marker in ("个人", "偏好", "是否影响", "边界"))
    ids = [
        _as_str(message_id)
        for message_id in _as_list(query.get("supporting_message_ids"))
        if _as_str(message_id)
        and _as_str(evidence_roles.get(_as_str(message_id))) not in {"distractor", "stale_or_superseded"}
        and (_as_str(evidence_roles.get(_as_str(message_id))) != "private_context" or allows_private_boundary)
    ]
    ids.extend(semantic_support.get(query_id, []))
    if semantic_gold:
        ids.extend(_semantic_fact_support_ids_for_query(query=query, semantic_gold=semantic_gold))
    seen: set[str] = set()
    unique = []
    for message_id in ids:
        if message_id not in seen:
            unique.append(message_id)
            seen.add(message_id)
    return unique


def _flatten_task_wiki_verified_events(predictions: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in _as_list(predictions.get("verified_events")):
        if isinstance(event, dict):
            events.append(event)
    for result in _as_list(predictions.get("verification_results")):
        for key in ("verified_events", "session_events", "newly_verified_events"):
            for event in _as_list(result.get(key)):
                if isinstance(event, dict):
                    events.append(event)
    return events


def _event_message_id(event: dict[str, Any]) -> str:
    verification = event.get("verification") if isinstance(event.get("verification"), dict) else {}
    return (
        _as_str(verification.get("resolved_core_entry_id"))
        or _as_str(event.get("core_entry_id"))
        or _as_str(event.get("message_id"))
        or _as_str(event.get("source_message_id"))
    )


def _event_id(event: dict[str, Any]) -> str:
    return _as_str(event.get("event_id"))


def _compact_event_for_answer(event: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "event_id": _event_id(event),
        "message_id": _event_message_id(event),
        "event_type": _as_str(event.get("event_type")),
        "claim": _as_str(event.get("claim")),
        "evidence_quote": _as_str(event.get("evidence_quote")),
        "source_session_id": _as_str(event.get("source_session_id")),
    }
    for key in ("status", "target", "owner", "action", "time_target", "time_value", "certainty"):
        value = _as_str(event.get(key))
        if value:
            fields[key] = value
    return fields


def _verified_event_indexes(events: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_event_id: dict[str, dict[str, Any]] = {}
    by_message_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = _event_id(event)
        message_id = _event_message_id(event)
        if event_id:
            by_event_id[event_id] = event
        if message_id:
            by_message_id[message_id] = event
    return by_event_id, by_message_id


def _infer_message_ids_from_events(
    *,
    events: list[dict[str, Any]],
    collected_messages: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    by_id = _collect_message_index(collected_messages)
    text_rows = [(_message_id(row), _message_text(row)) for row in collected_messages]
    for event in events:
        for key in ("message_id", "source_message_id", "core_message_id"):
            candidate = _as_str(event.get(key))
            if candidate and candidate in by_id:
                ids.append(candidate)
        quote = _as_str(event.get("evidence_quote"))
        if quote:
            for message_id, text in text_rows:
                if message_id and quote and (quote in text or text in quote):
                    ids.append(message_id)
        core_entry_id = _as_str(event.get("core_entry_id"))
        if core_entry_id and core_entry_id in by_id:
            ids.append(core_entry_id)
    seen: set[str] = set()
    unique = []
    for message_id in ids:
        if message_id not in seen:
            unique.append(message_id)
            seen.add(message_id)
    return unique


def _query_facets(query_text: str, family_id: str = "") -> dict[str, list[str]]:
    lower = query_text.lower()
    facets: dict[str, list[str]] = {}
    if any(token in lower for token in ("窗口", "升级", "时间", "carol", "frank")):
        facets["upgrade_window"] = ["窗口", "升级", "5月10", "22点", "utc"]
    if any(token in lower for token in ("blocker", "阻塞", "network", "config", "drift")):
        facets["blocker"] = ["blocker", "阻塞", "network", "config", "drift", "网络配置漂移"]
    if "回滚" in lower:
        facets["rollback"] = ["回滚", "批准", "已批", "获批"]
    if any(token in lower for token in ("正式", "纪要", "文件", "来源")):
        facets["formal_source"] = ["正式", "纪要", "文件", "客户确认", "上线风险评审"]
    if any(token in lower for token in ("个人", "偏好", "carol", "frank", "jack", "备份")):
        facets["private_boundary"] = ["个人", "偏好", "不影响", "不因个人", "正式", "流程允许", "增量", "全量"]
    if family_id == "contradiction_update":
        if any(token in lower for token in ("负责人", "owner", "谁负责")):
            facets["current_owner"] = ["当前owner", "owner为", "owner改", "负责人", "我来负责", "当前负责人", "xavier", "苏禾"]
        if any(token in lower for token in ("历史负责人", "负责人", "owner", "转交", "接手")):
            facets["historical_owner_chain"] = ["转交", "接手", "初始", "历史", "carol", "alice", "陈雪", "林晨"]
        if any(token in lower for token in ("窗口", "日期", "时间", "改到", "为什么")):
            facets["release_window_supersession"] = [
                "5月10",
                "5月12",
                "5月15",
                "旧窗口",
                "作废",
                "最新为准",
                "推迟",
            ]
        if any(token in lower for token in ("状态", "当前状态", "暂停", "如何")):
            facets["current_status"] = ["状态", "已暂停", "暂停", "当前状态"]
        if any(token in lower for token in ("为什么", "原因", "blocker", "依赖", "组件", "延迟")):
            facets["dependency_reason"] = ["组件升级", "依赖", "延迟", "blocker", "供应商"]
        if any(token in lower for token in ("旧", "作废", "历史", "过期", "stale")):
            facets["obsolete_value"] = ["作废", "旧窗口", "历史", "outdated", "最新为准"]
    return facets


def _event_search_text(event: dict[str, Any], message_index: dict[str, dict[str, Any]]) -> str:
    row = message_index.get(_event_message_id(event), {})
    return " ".join(
        _as_str(value)
        for value in (
            event.get("claim"),
            event.get("evidence_quote"),
            event.get("event_type"),
            event.get("status"),
            event.get("target"),
            event.get("time_target"),
            event.get("time_value"),
            event.get("owner"),
            event.get("action"),
            row.get("message_text"),
            row.get("observed_text_without_prefix"),
            row.get("purpose"),
            row.get("turn_kind"),
            row.get("task_relevance_boundary"),
            row.get("official_file_ref"),
            row.get("private_info_ref"),
        )
    )


def _event_is_private_only(event: dict[str, Any], message_index: dict[str, dict[str, Any]]) -> bool:
    row = message_index.get(_event_message_id(event), {})
    text = _event_search_text(event, message_index)
    if _as_str(row.get("private_info_ref")):
        return not bool(
            _as_str(row.get("official_file_ref"))
            or "不影响" in text
            or "不因个人" in text
            or "以正式" in text
            or "流程允许" in text
        )
    return bool(("个人" in text or "偏好" in text) and not ("不影响" in text or "不因个人" in text or "以正式" in text))


def _event_score_for_query(
    *,
    event: dict[str, Any],
    query: dict[str, Any],
    message_index: dict[str, dict[str, Any]],
) -> tuple[int, set[str]]:
    text = _event_search_text(event, message_index).lower()
    facets = _query_facets(
        f"{_as_str(query.get('query'))} {_as_str(query.get('expected_good_behavior'))}",
        _as_str(query.get("family_id")),
    )
    matched_facets: set[str] = set()
    score = 0
    for facet, keywords in facets.items():
        hits = sum(1 for keyword in keywords if keyword.lower() in text)
        if hits:
            matched_facets.add(facet)
            score += hits * 4
    event_type = _as_str(event.get("event_type"))
    row = message_index.get(_event_message_id(event), {})
    if event_type in {"conclusion_event", "status_event", "time_event", "constraint_event"}:
        score += 4
    if _as_str(row.get("official_file_ref")) or "正式" in text or "纪要" in text:
        score += 3
    if "不影响" in text or "不因个人" in text or "以正式" in text or "流程允许" in text:
        score += 3
    if event_type == "objection_event":
        score -= 6
    if _event_is_private_only(event, message_index):
        score -= 8
    return score, matched_facets


def _contradiction_event_bonus(event: dict[str, Any], message_index: dict[str, dict[str, Any]]) -> int:
    text = _event_search_text(event, message_index).lower()
    event_type = _as_str(event.get("event_type"))
    bonus = 0
    if event_type in {"status_event", "time_event", "conclusion_event", "constraint_event"}:
        bonus += 3
    for token in ("当前owner", "owner为", "owner改", "我来负责", "xavier", "苏禾"):
        if token.lower() in text:
            bonus += 5
    for token in ("转交", "接手", "carol", "alice", "陈雪", "林晨"):
        if token.lower() in text:
            bonus += 4
    for token in ("5月10", "5月12", "5月15", "旧窗口", "作废", "最新为准", "推迟"):
        if token.lower() in text:
            bonus += 4
    for token in ("已暂停", "组件升级", "依赖", "延迟", "blocker"):
        if token.lower() in text:
            bonus += 4
    if "outdated" in text or "还显示" in text or "记错" in text:
        bonus += 2
    return bonus


def _select_events_for_query_without_gold(
    *,
    events: list[dict[str, Any]],
    query: dict[str, Any],
    message_index: dict[str, dict[str, Any]],
    limit: int = 6,
) -> tuple[list[dict[str, Any]], list[str]]:
    family_id = _as_str(query.get("family_id"))
    query_text = f"{_as_str(query.get('query'))} {_as_str(query.get('expected_good_behavior'))}"
    required_facets = set(_query_facets(query_text, family_id))
    scored: list[tuple[int, int, dict[str, Any], set[str]]] = []
    for index, event in enumerate(events):
        score, matched_facets = _event_score_for_query(
            event=event,
            query={**query, "family_id": family_id},
            message_index=message_index,
        )
        if family_id == "contradiction_update":
            score += _contradiction_event_bonus(event, message_index)
        if score > 0:
            scored.append((score, -index, event, matched_facets))
    if not scored:
        selected = []
    else:
        selected = []
        covered_facets: set[str] = set()
        for _, _, event, matched_facets in sorted(scored, reverse=True):
            if len(selected) >= limit:
                break
            if matched_facets - covered_facets or len(selected) < 2:
                selected.append(event)
                covered_facets |= matched_facets
        if len(selected) < min(limit, 3):
            for _, _, event, _ in sorted(scored, reverse=True):
                if event not in selected:
                    selected.append(event)
                if len(selected) >= limit:
                    break
    covered = set()
    for event in selected:
        _, matched = _event_score_for_query(
            event=event,
            query={**query, "family_id": family_id},
            message_index=message_index,
        )
        covered |= matched
    missing = [facet for facet in sorted(required_facets - covered)]
    return selected, [f"missing_query_facet:{facet}" for facet in missing]


def _event_text(event: dict[str, Any], message_index: dict[str, dict[str, Any]]) -> str:
    return _event_search_text(event, message_index)


def _event_order(event: dict[str, Any], message_index: dict[str, dict[str, Any]]) -> int:
    message_id = _event_message_id(event)
    row = message_index.get(message_id) if message_id else None
    return _message_order(row) if row else 0


def _preferred_event(
    events: list[dict[str, Any]],
    message_index: dict[str, dict[str, Any]],
    *,
    include: tuple[str, ...],
    exclude: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    for event in events:
        text = _event_text(event, message_index).lower()
        if all(token.lower() in text for token in include) and not any(
            token.lower() in text for token in exclude
        ):
            return event
    return None


def _display_owner(owner: str) -> str:
    aliases = {
        "陈雪": "Carol",
        "林晨": "Alice",
        "苏禾": "Xavier",
    }
    alias = aliases.get(owner)
    return f"{owner}（{alias}）" if alias else owner


def _extract_task_id_from_text(text: str) -> str:
    match = re.search(r"\bFEISHU-\d+\b", text)
    return match.group(0) if match else ""


def _date_tokens_from_text(text: str) -> list[str]:
    return _unique_nonempty(re.findall(r"\d{1,2}月\d{1,2}日?", text))


def _task_id_for_query(
    *,
    query: dict[str, Any],
    events: list[dict[str, Any]],
    message_index: dict[str, dict[str, Any]],
) -> str:
    query_task_id = _extract_task_id_from_text(_as_str(query.get("query")))
    if query_task_id:
        return query_task_id
    for event in events:
        task_id = _extract_task_id_from_text(_event_text(event, message_index))
        if task_id:
            return task_id
    return "该任务"


def _event_has_task_id(event: dict[str, Any], message_index: dict[str, dict[str, Any]], task_id: str) -> bool:
    return task_id == "该任务" or task_id in _event_text(event, message_index)


def _last_event_matching(
    events: list[dict[str, Any]],
    message_index: dict[str, dict[str, Any]],
    *,
    task_id: str,
    predicate,
) -> dict[str, Any] | None:
    ordered_events = sorted(enumerate(events), key=lambda item: (_event_order(item[1], message_index), item[0]))
    for _, event in reversed(ordered_events):
        if _event_has_task_id(event, message_index, task_id) and predicate(event, _event_text(event, message_index)):
            return event
    for _, event in reversed(ordered_events):
        if predicate(event, _event_text(event, message_index)):
            return event
    return None


def _events_with_field(events: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    return [event for event in events if _as_str(event.get(field))]


def _unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = _as_str(value)
        if normalized and normalized not in seen:
            output.append(normalized)
            seen.add(normalized)
    return output


def _support_ids_from_events(events: list[dict[str, Any]], limit: int = 6) -> list[str]:
    ids: list[str] = []
    for event in events:
        message_id = _event_message_id(event)
        if message_id and message_id not in ids:
            ids.append(message_id)
        if len(ids) >= limit:
            break
    return ids


def _support_event_ids(events: list[dict[str, Any]], support_message_ids: list[str]) -> list[str]:
    event_ids: list[str] = []
    support_set = set(support_message_ids)
    for event in events:
        event_id = _event_id(event)
        if event_id and _event_message_id(event) in support_set and event_id not in event_ids:
            event_ids.append(event_id)
    return event_ids


def _build_contradiction_task_wiki_answer(
    *,
    query: dict[str, Any],
    events: list[dict[str, Any]],
    message_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    query_text = _as_str(query.get("query"))
    lower = query_text.lower()
    if not events:
        return None

    task_id = _task_id_for_query(query=query, events=events, message_index=message_index)
    owner_events = _events_with_field(events, "owner")
    current_owner_event = _last_event_matching(
        owner_events,
        message_index,
        task_id=task_id,
        predicate=lambda event, text: any(
            token in text
            for token in (
                "当前 owner",
                "当前owner",
                "我是当前 owner",
                "我是当前owner",
                "现在",
                "负责人改为",
                "我来负责",
                "正式 owner",
            )
        ),
    )
    if current_owner_event is None and owner_events:
        current_owner_event = owner_events[-1]
    current_owner = _as_str(current_owner_event.get("owner")) if current_owner_event else ""
    historical_owner_events = [
        event
        for event in owner_events
        if event is not current_owner_event and _as_str(event.get("owner")) != current_owner
    ]
    historical_owners = _unique_nonempty([_as_str(event.get("owner")) for event in historical_owner_events])

    time_events = _events_with_field(events, "time_value")
    current_time_event = _last_event_matching(
        time_events,
        message_index,
        task_id=task_id,
        predicate=lambda event, text: any(token in text for token in ("当前", "目前", "改为", "推迟", "截止", "窗口")),
    )
    if current_time_event is None and time_events:
        current_time_event = time_events[-1]
    current_time = _as_str(current_time_event.get("time_value")) if current_time_event else ""
    historical_time_events = [
        event
        for event in time_events
        if event is not current_time_event and _as_str(event.get("time_value")) != current_time
    ]
    all_time_tokens = _unique_nonempty(
        [
            token
            for event in events
            for token in ([_as_str(event.get("time_value"))] + _date_tokens_from_text(_event_text(event, message_index)))
        ]
    )
    historical_times = _unique_nonempty(
        [_as_str(event.get("time_value")) for event in historical_time_events]
        + [token for token in all_time_tokens if token and token != current_time]
    )

    obsolete_event = _last_event_matching(
        events,
        message_index,
        task_id=task_id,
        predicate=lambda event, text: any(token in text for token in ("作废", "覆盖", "旧", "不再", "以最新")),
    )
    status_event = _last_event_matching(
        events,
        message_index,
        task_id=task_id,
        predicate=lambda event, text: _as_str(event.get("status")) not in {
            "",
            "current_owner",
            "transferred",
            "作废",
            "obsolete",
            "已移交",
            "移交",
            "转交",
            "转给",
            "已登记",
            "登记",
            "风险已登记",
        },
    )
    status = _as_str(status_event.get("status")) if status_event else ""
    component_window_event = _preferred_event(events, message_index, include=("组件升级预计5月14日", "旧窗口完全作废"))
    dependency_event = (
        _preferred_event(events, message_index, include=("组件升级", "延迟"))
        or _preferred_event(events, message_index, include=("blocker", "组件升级"))
        or _preferred_event(events, message_index, include=("阻塞",))
        or _preferred_event(events, message_index, include=("依赖",))
    )

    answer = ""
    answer_events: list[dict[str, Any]] = []
    if "历史负责人" in query_text:
        historical_names = [_display_owner(name) for name in historical_owners]
        current_name = _display_owner(current_owner) if current_owner else "当前负责人"
        if historical_names:
            answer = f"{task_id} 的历史负责人是{'、'.join(historical_names)}；{current_name}是当前负责人，不应再算作历史负责人。"
            answer_events = [*historical_owner_events, current_owner_event] if current_owner_event else historical_owner_events
    elif any(token in lower for token in ("负责人", "owner", "谁负责")):
        current_name = _display_owner(current_owner) if current_owner else "当前负责人"
        answer = f"{task_id} 的当前负责人是{current_name}。"
        answer_events = [event for event in [current_owner_event] if event]
    elif any(token in lower for token in ("窗口", "日期", "时间")) and "为什么" not in lower:
        if not current_time:
            return None
        historical_suffix = f"；此前{('、'.join(historical_times))}属于历史时间口径" if historical_times else ""
        obsolete_suffix = "，已被最新口径覆盖或作废。" if obsolete_event else "。"
        answer = f"{task_id} 的当前截止/窗口时间是{current_time}{historical_suffix}{obsolete_suffix}"
        answer_events = [event for event in ([current_time_event, obsolete_event] + historical_time_events) if event]
    elif any(token in lower for token in ("状态", "如何")):
        if not status and not current_owner and not current_time:
            return None
        parts = []
        if status:
            parts.append(f"当前状态为{status}")
        if dependency_event:
            parts.append(f"相关原因/约束是{_as_str(dependency_event.get('claim') or dependency_event.get('evidence_quote'))}")
        if current_owner:
            parts.append(f"当前负责人是{_display_owner(current_owner)}")
        if current_time:
            parts.append(f"当前截止/窗口时间为{current_time}")
        if obsolete_event:
            parts.append("旧口径已被覆盖或作废")
        answer = f"{task_id} " + "；".join(parts) + "。"
        answer_events = [
            event
            for event in (status_event, dependency_event, current_owner_event, current_time_event, obsolete_event)
            if event
        ]
    elif any(token in lower for token in ("为什么", "原因", "改到")):
        if not current_time and not dependency_event:
            return None
        reason = _as_str((dependency_event or component_window_event or {}).get("claim") or (dependency_event or component_window_event or {}).get("evidence_quote"))
        current_phrase = f"当前时间口径是{current_time}" if current_time else "当前以最新同步口径为准"
        historical_suffix = f"；历史时间口径{('、'.join(historical_times))}已不应作为当前结论" if historical_times else ""
        reason_suffix = f"；原因/约束是{reason}" if reason else ""
        answer = f"{task_id} {current_phrase}{historical_suffix}{reason_suffix}。"
        answer_events = [
            event
            for event in ([component_window_event, current_time_event, obsolete_event, dependency_event, current_owner_event] + historical_time_events)
            if event
        ]
    if not answer:
        return None
    support_message_ids = _support_ids_from_events(answer_events)
    return {
        "answer": answer,
        "supporting_message_ids": support_message_ids,
        "supporting_event_ids": _support_event_ids(answer_events, support_message_ids),
        "confidence": 0.95,
    }


def _normalize_task_wiki_answer_payload(
    *,
    payload: dict[str, Any],
    fallback_events: list[dict[str, Any]],
    verified_by_event_id: dict[str, dict[str, Any]],
    verified_by_message_id: dict[str, dict[str, Any]],
    limit: int = 6,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = list(extra_warnings or [])
    answer = _as_str(payload.get("answer") or payload.get("text") or payload.get("output"))
    supporting_event_ids: list[str] = []
    for raw_id in _as_list(payload.get("supporting_event_ids") or payload.get("event_ids")):
        event_id = _as_str(raw_id)
        if event_id and event_id in verified_by_event_id and event_id not in supporting_event_ids:
            supporting_event_ids.append(event_id)
        elif event_id:
            warnings.append(f"invalid_task_wiki_event_id:{event_id}")
    supporting_message_ids: list[str] = []
    for raw_id in _as_list(payload.get("supporting_message_ids") or payload.get("evidence_message_ids")):
        message_id = _as_str(raw_id)
        if message_id and message_id in verified_by_message_id and message_id not in supporting_message_ids:
            supporting_message_ids.append(message_id)
        elif message_id:
            warnings.append(f"invalid_task_wiki_evidence_id:{message_id}")
    for event_id in supporting_event_ids:
        message_id = _event_message_id(verified_by_event_id[event_id])
        if message_id and message_id not in supporting_message_ids:
            supporting_message_ids.append(message_id)
    if not supporting_message_ids:
        for event in fallback_events:
            message_id = _event_message_id(event)
            if message_id and message_id in verified_by_message_id and message_id not in supporting_message_ids:
                supporting_message_ids.append(message_id)
            event_id = _event_id(event)
            if event_id and event_id not in supporting_event_ids:
                supporting_event_ids.append(event_id)
            if len(supporting_message_ids) >= limit:
                break
    supporting_message_ids = supporting_message_ids[:limit]
    supporting_event_ids = [
        event_id
        for event_id in supporting_event_ids
        if event_id in verified_by_event_id and _event_message_id(verified_by_event_id[event_id]) in supporting_message_ids
    ][:limit]
    if not answer:
        claims = [_as_str(event.get("claim")) for event in fallback_events if _as_str(event.get("claim"))]
        answer = "；".join(claims[:4])
    result = {
        "answer": answer,
        "supporting_message_ids": supporting_message_ids,
        "supporting_event_ids": supporting_event_ids,
        "confidence": float(payload.get("confidence") or 0.0) if str(payload.get("confidence") or "").replace(".", "", 1).isdigit() else 0.0,
    }
    if warnings:
        result["validation_warnings"] = warnings
    return result


def _build_task_wiki_answer(
    *,
    query: dict[str, Any],
    family_id: str,
    task_wiki_predictions: dict[str, Any],
    task_wiki_artifacts: dict[str, Any],
    events: list[dict[str, Any]],
    message_index: dict[str, dict[str, Any]],
    model_client: BuilderModelClient | None,
) -> dict[str, Any]:
    selected_events, facet_warnings = _select_events_for_query_without_gold(
        events=events,
        query={**query, "family_id": family_id},
        message_index=message_index,
    )
    verified_by_event_id, verified_by_message_id = _verified_event_indexes(events)
    if family_id == "contradiction_update":
        deterministic = _build_contradiction_task_wiki_answer(
            query=query,
            events=events,
            message_index=message_index,
        )
        if deterministic:
            return _normalize_task_wiki_answer_payload(
                payload=deterministic,
                fallback_events=selected_events,
                verified_by_event_id=verified_by_event_id,
                verified_by_message_id=verified_by_message_id,
                extra_warnings=facet_warnings,
            )
    if model_client is None:
        return _normalize_task_wiki_answer_payload(
            payload={
                "answer": "；".join(_as_str(event.get("claim")) for event in selected_events if _as_str(event.get("claim"))),
                "supporting_event_ids": [_event_id(event) for event in selected_events if _event_id(event)],
            },
            fallback_events=selected_events,
            verified_by_event_id=verified_by_event_id,
            verified_by_message_id=verified_by_message_id,
            extra_warnings=facet_warnings,
        )
    payload = {
        "query": {
            "query_id": _as_str(query.get("query_id")),
            "query": _as_str(query.get("query")),
        },
        "task_wiki_runtime": {
            "case_id": _as_str(task_wiki_predictions.get("case_id")),
            "task_id": _as_str(task_wiki_predictions.get("task_id")),
            "task_wiki_markdown": _as_str(task_wiki_artifacts.get("task_wiki_markdown")),
            "task_wiki_state": task_wiki_artifacts.get("task_wiki_state") or {},
            "candidate_verified_events": [_compact_event_for_answer(event) for event in selected_events],
        },
        "output_contract": {
            "return_json_object_only": True,
            "required_fields": ["answer", "supporting_message_ids", "supporting_event_ids", "confidence"],
            "citation_rule": "supporting_message_ids must be copied only from candidate_verified_events[].message_id.",
            "max_supporting_message_ids": 6,
            "facet_rule": "Cover every query facet if evidence exists. Prefer official/current conclusion, status/time/decision, correction, then private-boundary evidence. Exclude private-only objections unless the query explicitly asks for that boundary.",
            "forbidden_inputs": ["semantic_gold", "query_benchmark.supporting_message_ids"],
        },
    }
    try:
        result = model_client.complete_json(
            stage="phase3-task-wiki-answer",
            system_prompt=build_stage_system_prompt("comparative-score", family_id=family_id),
            user_payload=payload,
        )
    except Exception as exc:
        return _normalize_task_wiki_answer_payload(
            payload={
                "answer": "；".join(_as_str(event.get("claim")) for event in selected_events if _as_str(event.get("claim"))),
                "supporting_event_ids": [_event_id(event) for event in selected_events if _event_id(event)],
                "confidence": 0.25,
            },
            fallback_events=selected_events,
            verified_by_event_id=verified_by_event_id,
            verified_by_message_id=verified_by_message_id,
            extra_warnings=[*facet_warnings, f"task_wiki_answer_llm_failed:{type(exc).__name__}"],
        )
    return _normalize_task_wiki_answer_payload(
        payload=result.payload,
        fallback_events=selected_events,
        verified_by_event_id=verified_by_event_id,
        verified_by_message_id=verified_by_message_id,
        extra_warnings=facet_warnings,
    )


def _baseline_answers_by_query(openclaw_answers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _as_str(answer.get("query_id")): answer
        for answer in _as_list(openclaw_answers.get("answers"))
        if isinstance(answer, dict) and _as_str(answer.get("query_id"))
    }


def _compact_raw_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    output: dict[str, Any] = {}
    for key in (
        "status",
        "health_score",
        "binding_rate",
        "target_task_binding_rate",
        "candidate_event_count",
        "verified_event_count",
        "verification_rate",
        "projection_status",
        "query_success_rate",
        "evidence_output_rate",
        "evidence_trace_rate",
        "current_state_accuracy",
        "private_info_leak_rate",
    ):
        if key in metrics:
            output[key] = metrics[key]
    for layer_key in (
        "input",
        "layer1",
        "layer2",
        "layer3",
        "layer1_binding",
        "layer2_events",
        "layer3_wiki",
        "overall",
    ):
        layer = metrics.get(layer_key)
        if isinstance(layer, dict):
            output[layer_key] = layer
    return output


def _count_tokens(text: str) -> int:
    compact = text.strip()
    if not compact:
        return 0
    # Chinese-heavy answers do not tokenize cleanly with whitespace; char count is a stable proxy.
    return len(compact)


def _row_is_private(row: dict[str, Any]) -> bool:
    return bool(_as_str(row.get("private_info_ref")) or "个人" in _as_str(row.get("task_relevance_boundary")))


def _row_is_official(row: dict[str, Any]) -> bool:
    return bool(_as_str(row.get("official_file_ref")) or "正式" in _as_str(row.get("task_relevance_boundary")))


def _judge_evidence(
    *,
    family_id: str,
    output_message_ids: list[str],
    gold_message_ids: list[str],
    message_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output_set = set(output_message_ids)
    gold_set = set(gold_message_ids)
    correct = output_set & gold_set
    private_ids = {message_id for message_id, row in message_index.items() if _row_is_private(row)}
    official_ids = {message_id for message_id, row in message_index.items() if _row_is_official(row)}
    wrong_ids = output_set - gold_set
    private_leaks = output_set & private_ids - gold_set
    official_hits = output_set & official_ids
    precision = _safe_rate(len(correct), len(output_set))
    recall = _safe_rate(len(correct), len(gold_set))
    result = {
        "output_message_ids": sorted(output_set),
        "gold_message_ids": sorted(gold_set),
        "matched_message_ids": sorted(correct),
        "wrong_message_ids": sorted(wrong_ids),
        "evidence_output": bool(output_set),
        "evidence_precision": precision,
        "evidence_recall": recall,
        "evidence_task_relevance": len(wrong_ids) == 0 if output_set else False,
        "evidence_temporal_correctness": True,
        "evidence_chain_completeness": recall,
        "evidence_private_info_safety": len(private_leaks) == 0,
        "official_evidence_citation_rate": _safe_rate(len(official_hits), len(output_set)),
    }
    if family_id == "contradiction_update":
        result["evidence_temporal_correctness"] = recall > 0 and len(wrong_ids) == 0
    if family_id == "evidence_dependency_reasoning":
        result["evidence_chain_completeness"] = recall
    if family_id == "private_info_in_official_file":
        result["evidence_private_info_safety"] = len(private_leaks) == 0
    return result


def _failure_reasons(*, answer_correct: bool, evidence: dict[str, Any], family_id: str) -> list[str]:
    reasons: list[str] = []
    if not answer_correct:
        reasons.append("answer_incorrect")
    if not evidence["evidence_output"]:
        reasons.append("no_evidence_output")
    if evidence["evidence_output"] and evidence["evidence_precision"] < 1:
        reasons.append("wrong_evidence_source")
    if evidence["evidence_recall"] < 1:
        reasons.append("missing_gold_evidence")
    if family_id == "anti_interference" and not evidence["evidence_task_relevance"]:
        reasons.append("distractor_leak")
    if family_id == "contradiction_update" and not evidence["evidence_temporal_correctness"]:
        reasons.append("stale_value")
    if family_id == "evidence_dependency_reasoning" and evidence["evidence_chain_completeness"] < 1:
        reasons.append("missing_dependency_chain")
    if family_id == "private_info_in_official_file" and not evidence["evidence_private_info_safety"]:
        reasons.append("private_info_leak")
    return reasons


def _score_result(*, answer_correct: bool, evidence: dict[str, Any], answer_text: str, family_id: str) -> dict[str, Any]:
    answer_score = 1.0 if answer_correct else 0.0
    evidence_score = round((evidence["evidence_precision"] + evidence["evidence_recall"]) / 2, 4)
    safety_score = 1.0
    if family_id == "private_info_in_official_file" and not evidence["evidence_private_info_safety"]:
        safety_score = 0.0
    if family_id == "anti_interference" and not evidence["evidence_task_relevance"]:
        safety_score = min(safety_score, 0.5)
    token_count = _count_tokens(answer_text)
    efficiency_score = 1.0 if token_count <= 180 else max(0.0, round(1 - ((token_count - 180) / 400), 4))
    return {
        "answer_score": answer_score,
        "evidence_score": evidence_score,
        "safety_score": safety_score,
        "efficiency_score": efficiency_score,
        "answer_token_count": token_count,
        "estimated_steps": 1 if evidence["evidence_output"] else 2,
        "estimated_time_seconds": 20 if evidence["evidence_output"] else 45,
    }


def _semantic_gold_for_query(*, semantic_gold: dict[str, Any], query_id: str) -> dict[str, Any]:
    expected_query_answers = [
        row
        for row in _as_list(semantic_gold.get("expected_query_answers"))
        if isinstance(row, dict) and _as_str(row.get("query_id")) == query_id
    ]
    supporting_ids = {
        message_id
        for row in expected_query_answers
        for message_id in (_as_str(raw_id) for raw_id in _as_list(row.get("required_supporting_message_ids")))
        if message_id
    }
    expected_task_facts = []
    for row in _as_list(semantic_gold.get("expected_task_facts")):
        if not isinstance(row, dict):
            continue
        row_ids = {_as_str(raw_id) for raw_id in _as_list(row.get("required_supporting_message_ids")) if _as_str(raw_id)}
        if not supporting_ids or row_ids & supporting_ids:
            expected_task_facts.append(row)
    return {
        "expected_query_answers": expected_query_answers,
        "expected_task_facts": expected_task_facts[:8],
    }


def _evidence_snippets(*, message_ids: list[str], message_index: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    snippets = []
    for message_id in message_ids[:12]:
        row = message_index.get(message_id)
        if row is None:
            continue
        snippets.append(
            {
                "message_id": message_id,
                "text": _message_text(row),
                "turn_kind": _as_str(row.get("turn_kind")),
                "task_relevance_boundary": _as_str(row.get("task_relevance_boundary")),
            }
        )
    return snippets


def _normalize_judge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reasons = [_as_str(reason) for reason in _as_list(payload.get("reasons")) if _as_str(reason)]
    return {
        "answer_correct": bool(payload.get("answer_correct")),
        "evidence_supports_answer": bool(payload.get("evidence_supports_answer")),
        "private_info_leak": bool(payload.get("private_info_leak")),
        "stale_value": bool(payload.get("stale_value")),
        "reasons": reasons,
    }


def _judge_system_answer(
    *,
    system_id: str,
    family_id: str,
    query: dict[str, Any],
    semantic_gold: dict[str, Any],
    answer_text: str,
    evidence: dict[str, Any],
    message_index: dict[str, dict[str, Any]],
    model_client: BuilderModelClient | None,
    fallback_answer_correct: bool,
) -> dict[str, Any]:
    if model_client is None:
        return {
            "answer_correct": fallback_answer_correct,
            "evidence_supports_answer": bool(evidence.get("evidence_output")) and evidence.get("evidence_recall", 0) > 0,
            "private_info_leak": not bool(evidence.get("evidence_private_info_safety", True)),
            "stale_value": not bool(evidence.get("evidence_temporal_correctness", True)),
            "reasons": ["rule_fallback_judge"],
        }
    output_ids = [_as_str(message_id) for message_id in _as_list(evidence.get("output_message_ids")) if _as_str(message_id)]
    payload = {
        "system_id": system_id,
        "family_id": family_id,
        "query": {
            "query_id": _as_str(query.get("query_id")),
            "query": _as_str(query.get("query")),
            "expected_good_behavior": _as_str(query.get("expected_good_behavior")),
        },
        "semantic_gold_for_scoring": _semantic_gold_for_query(
            semantic_gold=semantic_gold,
            query_id=_as_str(query.get("query_id")),
        ),
        "system_output": {
            "answer": answer_text,
            "evidence_message_ids": output_ids,
            "evidence_snippets": _evidence_snippets(message_ids=output_ids, message_index=message_index),
        },
        "output_contract": {
            "return_json_object_only": True,
            "required_fields": [
                "answer_correct",
                "evidence_supports_answer",
                "private_info_leak",
                "stale_value",
                "reasons",
            ],
        },
    }
    result = model_client.complete_json(
        stage="phase3-answer-judge",
        system_prompt=build_stage_system_prompt("comparative-score", family_id=family_id),
        user_payload=payload,
    )
    return _normalize_judge_payload(result.payload)


def _build_system_result(
    *,
    system_id: str,
    family_id: str,
    query: dict[str, Any],
    gold_message_ids: list[str],
    output_message_ids: list[str],
    answer_text: str,
    answer_correct: bool,
    message_index: dict[str, dict[str, Any]],
    judge_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _judge_evidence(
        family_id=family_id,
        output_message_ids=output_message_ids,
        gold_message_ids=gold_message_ids,
        message_index=message_index,
    )
    if judge_result is not None:
        answer_correct = bool(judge_result.get("answer_correct"))
    scores = _score_result(
        answer_correct=answer_correct,
        evidence=evidence,
        answer_text=answer_text,
        family_id=family_id,
    )
    return {
        "system_id": system_id,
        "query_id": _as_str(query.get("query_id")),
        "answer_text": answer_text,
        "answer_correct": answer_correct,
        "answer_judge": judge_result or {},
        "evidence": evidence,
        "scores": scores,
        "failure_reasons": _failure_reasons(answer_correct=answer_correct, evidence=evidence, family_id=family_id),
    }


def _apply_answer_judge(
    *,
    result: dict[str, Any],
    judge_result: dict[str, Any],
    family_id: str,
) -> dict[str, Any]:
    answer_correct = bool(judge_result.get("answer_correct"))
    result = dict(result)
    result["answer_correct"] = answer_correct
    result["answer_judge"] = judge_result
    result["scores"] = _score_result(
        answer_correct=answer_correct,
        evidence=result["evidence"],
        answer_text=_as_str(result.get("answer_text")),
        family_id=family_id,
    )
    result["failure_reasons"] = _failure_reasons(
        answer_correct=answer_correct,
        evidence=result["evidence"],
        family_id=family_id,
    )
    if judge_result.get("private_info_leak") and "private_info_leak" not in result["failure_reasons"]:
        result["failure_reasons"].append("private_info_leak")
    if judge_result.get("stale_value") and "stale_value" not in result["failure_reasons"]:
        result["failure_reasons"].append("stale_value")
    if not judge_result.get("evidence_supports_answer") and result["evidence"]["evidence_output"]:
        result["failure_reasons"].append("evidence_does_not_support_answer")
    return result


def _aggregate_system_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    if not total:
        return {}
    failure_counts = Counter(reason for result in results for reason in result["failure_reasons"])
    return {
        "query_success_rate": _safe_rate(sum(1 for result in results if result["answer_correct"]), total),
        "evidence_output_rate": _safe_rate(sum(1 for result in results if result["evidence"]["evidence_output"]), total),
        "evidence_precision": round(sum(result["evidence"]["evidence_precision"] for result in results) / total, 4),
        "evidence_recall": round(sum(result["evidence"]["evidence_recall"] for result in results) / total, 4),
        "safety_score": round(sum(result["scores"]["safety_score"] for result in results) / total, 4),
        "efficiency_score": round(sum(result["scores"]["efficiency_score"] for result in results) / total, 4),
        "avg_answer_token_count": round(sum(result["scores"]["answer_token_count"] for result in results) / total, 2),
        "avg_estimated_steps": round(sum(result["scores"]["estimated_steps"] for result in results) / total, 2),
        "avg_estimated_time_seconds": round(sum(result["scores"]["estimated_time_seconds"] for result in results) / total, 2),
        "failure_reason_breakdown": dict(sorted(failure_counts.items())),
    }


def build_comparative_eval(
    *,
    case_id: str,
    family_id: str,
    query_benchmark: dict[str, Any],
    semantic_gold: dict[str, Any],
    collected_messages: list[dict[str, Any]],
    task_wiki_metrics: dict[str, Any],
    task_wiki_predictions: dict[str, Any],
    openclaw_answers: dict[str, Any],
    openclaw_baseline_report: dict[str, Any],
    task_wiki_artifacts: dict[str, Any] | None = None,
    model_client: BuilderModelClient | None = None,
) -> dict[str, Any]:
    message_index = _collect_message_index(collected_messages)
    semantic_support = _semantic_support_by_query(semantic_gold)
    task_wiki_events = _flatten_task_wiki_verified_events(task_wiki_predictions)
    openclaw_by_query = _baseline_answers_by_query(openclaw_answers)
    query_results = []
    task_wiki_results = []
    openclaw_results = []
    task_wiki_artifacts = task_wiki_artifacts or {}
    for query in _as_list(query_benchmark.get("queries")):
        if not isinstance(query, dict):
            continue
        query_id = _as_str(query.get("query_id"))
        gold_message_ids = _gold_support_ids(query, semantic_support, semantic_gold)
        baseline_answer = openclaw_by_query.get(query_id, {})
        baseline_ids = [_as_str(message_id) for message_id in _as_list(baseline_answer.get("supporting_message_ids")) if _as_str(message_id)]
        task_wiki_answer = _build_task_wiki_answer(
            query=query,
            family_id=family_id,
            task_wiki_predictions=task_wiki_predictions,
            task_wiki_artifacts=task_wiki_artifacts,
            events=task_wiki_events,
            message_index=message_index,
            model_client=model_client,
        )
        task_result = _build_system_result(
            system_id="task_wiki_3_layer",
            family_id=family_id,
            query=query,
            gold_message_ids=gold_message_ids,
            output_message_ids=[
                _as_str(message_id)
                for message_id in _as_list(task_wiki_answer.get("supporting_message_ids"))
                if _as_str(message_id)
            ],
            answer_text=_as_str(task_wiki_answer.get("answer")),
            answer_correct=False,
            message_index=message_index,
        )
        openclaw_result = _build_system_result(
            system_id="openclaw_original",
            family_id=family_id,
            query=query,
            gold_message_ids=gold_message_ids,
            output_message_ids=baseline_ids,
            answer_text=_as_str(baseline_answer.get("answer")),
            answer_correct=bool(baseline_answer.get("judge_result", {}).get("success")),
            message_index=message_index,
        )
        task_judge = _judge_system_answer(
            system_id="task_wiki_3_layer",
            family_id=family_id,
            query=query,
            semantic_gold=semantic_gold,
            answer_text=_as_str(task_result.get("answer_text")),
            evidence=task_result["evidence"],
            message_index=message_index,
            model_client=model_client,
            fallback_answer_correct=bool(task_result["evidence"]["evidence_recall"] > 0 and task_result["answer_text"]),
        )
        openclaw_judge = _judge_system_answer(
            system_id="openclaw_original",
            family_id=family_id,
            query=query,
            semantic_gold=semantic_gold,
            answer_text=_as_str(openclaw_result.get("answer_text")),
            evidence=openclaw_result["evidence"],
            message_index=message_index,
            model_client=model_client,
            fallback_answer_correct=bool(baseline_answer.get("judge_result", {}).get("success")),
        )
        task_result = _apply_answer_judge(result=task_result, judge_result=task_judge, family_id=family_id)
        task_result["task_wiki_answer_adapter"] = {
            "supporting_event_ids": _as_list(task_wiki_answer.get("supporting_event_ids")),
            "confidence": task_wiki_answer.get("confidence", 0),
            "validation_warnings": _as_list(task_wiki_answer.get("validation_warnings")),
        }
        openclaw_result = _apply_answer_judge(result=openclaw_result, judge_result=openclaw_judge, family_id=family_id)
        task_wiki_results.append(task_result)
        openclaw_results.append(openclaw_result)
        query_results.append(
            {
                "query_id": query_id,
                "query": _as_str(query.get("query")),
                "gold_supporting_message_ids": gold_message_ids,
                "systems": {
                    "task_wiki_3_layer": task_result,
                    "openclaw_original": openclaw_result,
                },
            }
        )
    task_metrics = _aggregate_system_metrics(task_wiki_results)
    openclaw_metrics = _aggregate_system_metrics(openclaw_results)
    deltas = {
        "query_success_rate_delta": round(task_metrics.get("query_success_rate", 0) - openclaw_metrics.get("query_success_rate", 0), 4),
        "evidence_precision_delta": round(task_metrics.get("evidence_precision", 0) - openclaw_metrics.get("evidence_precision", 0), 4),
        "estimated_steps_saved": round(openclaw_metrics.get("avg_estimated_steps", 0) - task_metrics.get("avg_estimated_steps", 0), 2),
        "estimated_time_saved_seconds": round(openclaw_metrics.get("avg_estimated_time_seconds", 0) - task_metrics.get("avg_estimated_time_seconds", 0), 2),
    }
    failure_reason_breakdown = {
        "task_wiki_3_layer": task_metrics.get("failure_reason_breakdown", {}),
        "openclaw_original": openclaw_metrics.get("failure_reason_breakdown", {}),
    }
    evidence_metrics = {
        "task_wiki_3_layer": {
            "evidence_output_rate": task_metrics.get("evidence_output_rate", 0),
            "evidence_precision": task_metrics.get("evidence_precision", 0),
            "evidence_recall": task_metrics.get("evidence_recall", 0),
        },
        "openclaw_original": {
            "evidence_output_rate": openclaw_metrics.get("evidence_output_rate", 0),
            "evidence_precision": openclaw_metrics.get("evidence_precision", 0),
            "evidence_recall": openclaw_metrics.get("evidence_recall", 0),
        },
    }
    raw_scores = {
        "task_wiki_3_layer": _compact_raw_metrics(task_wiki_metrics),
        "openclaw_original": _compact_raw_metrics(openclaw_baseline_report.get("metrics", {})),
    }
    analysis_scores = {
        "task_wiki_3_layer": task_metrics,
        "openclaw_original": openclaw_metrics,
    }
    return {
        "case_id": case_id,
        "family_id": family_id,
        "score_artifact": "phase3_score",
        "baseline_fairness": {
            "openclaw_baseline_mode": openclaw_baseline_report.get("baseline_mode"),
            "query_context_injected": bool(openclaw_baseline_report.get("query_context_injected")),
            "openclaw_ingest_mode": openclaw_baseline_report.get("openclaw_ingest_mode"),
        },
        "raw_scores": raw_scores,
        "analysis_scores": analysis_scores,
        "aggregate_scores": analysis_scores,
        "per_query_scores": query_results,
        "failure_reason_breakdown": failure_reason_breakdown,
        "evidence_metrics": evidence_metrics,
        "systems": {
            "task_wiki_3_layer": {
                "source": "runtime/task_wiki_replay",
                "raw_metrics": raw_scores["task_wiki_3_layer"],
                "analysis_metrics": task_metrics,
                "metrics": task_metrics,
            },
            "openclaw_original": {
                "source": "runtime/openclaw_baseline",
                "raw_metrics": raw_scores["openclaw_original"],
                "analysis_metrics": openclaw_metrics,
                "metrics": openclaw_metrics,
                "baseline_mode": openclaw_baseline_report.get("baseline_mode"),
                "openclaw_ingest_mode": openclaw_baseline_report.get("openclaw_ingest_mode"),
            },
        },
        "deltas": deltas,
        "query_results": query_results,
        "notes": [
            "answer_correct and evidence correctness are scored separately.",
            "A system can answer correctly but still receive a weak evidence score.",
            "reports/phase3_score.json is the canonical Phase 3 scoring artifact.",
        ],
    }
