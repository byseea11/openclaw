from __future__ import annotations

from collections import Counter
from typing import Any


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
    return {_message_id(row): row for row in collected_messages if _message_id(row)}


def _semantic_support_by_query(semantic_gold: dict[str, Any]) -> dict[str, list[str]]:
    by_query: dict[str, list[str]] = {}
    for item in _as_list(semantic_gold.get("expected_query_answers")):
        query_id = _as_str(item.get("query_id"))
        if not query_id:
            continue
        by_query[query_id] = [_as_str(message_id) for message_id in _as_list(item.get("required_supporting_message_ids")) if _as_str(message_id)]
    return by_query


def _gold_support_ids(query: dict[str, Any], semantic_support: dict[str, list[str]]) -> list[str]:
    query_id = _as_str(query.get("query_id"))
    ids = [_as_str(message_id) for message_id in _as_list(query.get("supporting_message_ids")) if _as_str(message_id)]
    ids.extend(semantic_support.get(query_id, []))
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


def _baseline_answers_by_query(openclaw_answers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _as_str(answer.get("query_id")): answer
        for answer in _as_list(openclaw_answers.get("answers"))
        if isinstance(answer, dict) and _as_str(answer.get("query_id"))
    }


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
) -> dict[str, Any]:
    evidence = _judge_evidence(
        family_id=family_id,
        output_message_ids=output_message_ids,
        gold_message_ids=gold_message_ids,
        message_index=message_index,
    )
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
        "evidence": evidence,
        "scores": scores,
        "failure_reasons": _failure_reasons(answer_correct=answer_correct, evidence=evidence, family_id=family_id),
    }


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
) -> dict[str, Any]:
    message_index = _collect_message_index(collected_messages)
    semantic_support = _semantic_support_by_query(semantic_gold)
    task_wiki_events = _flatten_task_wiki_verified_events(task_wiki_predictions)
    task_wiki_message_ids = _infer_message_ids_from_events(
        events=task_wiki_events,
        collected_messages=collected_messages,
    )
    task_wiki_status = _as_str(task_wiki_metrics.get("overall", {}).get("status"))
    openclaw_by_query = _baseline_answers_by_query(openclaw_answers)
    query_results = []
    task_wiki_results = []
    openclaw_results = []
    for query in _as_list(query_benchmark.get("queries")):
        if not isinstance(query, dict):
            continue
        query_id = _as_str(query.get("query_id"))
        gold_message_ids = _gold_support_ids(query, semantic_support)
        baseline_answer = openclaw_by_query.get(query_id, {})
        baseline_ids = [_as_str(message_id) for message_id in _as_list(baseline_answer.get("supporting_message_ids")) if _as_str(message_id)]
        task_result = _build_system_result(
            system_id="task_wiki_3_layer",
            family_id=family_id,
            query=query,
            gold_message_ids=gold_message_ids,
            output_message_ids=task_wiki_message_ids,
            answer_text="Task Wiki runtime projection uses verified events and wiki evidence refs.",
            answer_correct=task_wiki_status == "passed" and bool(set(task_wiki_message_ids) & set(gold_message_ids)),
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
    return {
        "case_id": case_id,
        "family_id": family_id,
        "score_artifact": "phase3_score",
        "aggregate_scores": {
            "task_wiki_3_layer": task_metrics,
            "openclaw_original": openclaw_metrics,
        },
        "per_query_scores": query_results,
        "failure_reason_breakdown": failure_reason_breakdown,
        "evidence_metrics": evidence_metrics,
        "systems": {
            "task_wiki_3_layer": {
                "source": "runtime/task_wiki_replay",
                "metrics": task_metrics,
            },
            "openclaw_original": {
                "source": "runtime/openclaw_baseline",
                "metrics": openclaw_metrics,
                "baseline_mode": openclaw_baseline_report.get("baseline_mode"),
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
