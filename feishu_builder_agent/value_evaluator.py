from __future__ import annotations

from collections import defaultdict
from typing import Any

from .eval_common import build_task_wiki_answer, deterministic_answer_checks, semantic_judge
from .schemas import validate_query_benchmark, validate_value_eval


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _evaluate_system_queries(
    *,
    queries: list[dict[str, Any]],
    answers_by_query_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    rows = []
    by_failure_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_query_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        answer = answers_by_query_id.get(query["query_id"], {})
        answer_text = str(answer.get("answer_text") or "")
        citations = [str(item) for item in answer.get("citations") or [] if str(item).strip()]
        deterministic = deterministic_answer_checks(
            query,
            answer_text,
            citations,
            citation_message_ids=answer.get("traceability_message_ids") or answer.get("retrieved_messages") or answer.get("citation_message_ids") or [],
        )
        semantic = semantic_judge(query, answer_text, citations)
        row = {
            "query_id": query["query_id"],
            "failure_mode": query["failure_mode"],
            "query_family": query["query_family"],
            "deterministic": deterministic,
            "semantic": semantic,
        }
        rows.append(row)
        by_failure_mode[query["failure_mode"]].append(row)
        by_query_family[query["query_family"]].append(row)

    def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {
                "task_specific_answer_accuracy": 0.0,
                "irrelevant_memory_pollution_rate": 0.0,
                "evidence_citation_success_rate": 0.0,
                "stale_memory_answer_rate": 0.0,
                "current_state_answer_accuracy": 0.0,
                "dependency_impact_recall": 0.0,
                "memory_claim_traceability_rate": 0.0,
                "memory_scope_purity": 0.0,
            }
        return {
            "task_specific_answer_accuracy": round(
                sum(float(item["semantic"].get("answer_point_coverage") or 0.0) for item in items) / len(items),
                4,
            ),
            "irrelevant_memory_pollution_rate": round(
                sum(1 for item in items if item["deterministic"].get("forbidden_claim_hit")) / len(items),
                4,
            ),
            "evidence_citation_success_rate": round(
                sum(1 for item in items if item["deterministic"].get("citation_traceability")) / len(items),
                4,
            ),
            "stale_memory_answer_rate": round(
                sum(1 for item in items if item["semantic"].get("stale_answer")) / len(items),
                4,
            ),
            "current_state_answer_accuracy": round(
                sum(float(item["semantic"].get("faithfulness") or 0.0) for item in items) / len(items),
                4,
            ),
            "dependency_impact_recall": round(
                sum(float(item["semantic"].get("cross_source_reasoning") or 0.0) for item in items) / len(items),
                4,
            ),
            "memory_claim_traceability_rate": round(
                sum(1 for item in items if item["deterministic"].get("citation_traceability")) / len(items),
                4,
            ),
            "memory_scope_purity": round(
                1.0 - (sum(1 for item in items if item["deterministic"].get("forbidden_claim_hit")) / len(items)),
                4,
            ),
        }

    overall = aggregate(rows)
    failure = {key: aggregate(value) for key, value in by_failure_mode.items()}
    family = {key: aggregate(value) for key, value in by_query_family.items()}
    return rows, overall, failure, family


def evaluate_value(
    *,
    case_id: str,
    query_benchmark: dict[str, Any],
    task_wiki_state: dict[str, Any],
    session_events: list[dict[str, Any]],
    memory_md_baseline_report: dict[str, Any],
    raw_message_rag_report: dict[str, Any],
) -> dict[str, Any]:
    benchmark = validate_query_benchmark(query_benchmark)
    task_wiki_answers = {
        query["query_id"]: build_task_wiki_answer(task_wiki_state, session_events, query)
        for query in benchmark["queries"]
    }
    memory_answers = {item["query_id"]: item for item in memory_md_baseline_report.get("queries") or []}
    rag_answers = {item["query_id"]: item for item in raw_message_rag_report.get("queries") or []}

    systems = {}
    overall = {}
    by_failure_mode = {}
    by_query_family = {}
    for system_name, answers in {
        "task_wiki": task_wiki_answers,
        "openclaw_memory_md": memory_answers,
        "raw_message_rag": rag_answers,
    }.items():
        rows, overall_metrics, failure_metrics, family_metrics = _evaluate_system_queries(
            queries=benchmark["queries"],
            answers_by_query_id=answers,
        )
        systems[system_name] = {"queries": rows}
        overall[system_name] = overall_metrics
        by_failure_mode[system_name] = failure_metrics
        by_query_family[system_name] = family_metrics

    report = {
        "case_id": case_id,
        "baseline_mode": "openclaw_real",
        "systems": systems,
        "overall": overall,
        "by_failure_mode": by_failure_mode,
        "by_query_family": by_query_family,
    }
    return validate_value_eval(report)
