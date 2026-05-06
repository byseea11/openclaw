from __future__ import annotations

from collections import defaultdict
from typing import Any

from .eval_common import build_task_wiki_answer, deterministic_answer_checks, semantic_judge
from .schemas import validate_qa_eval, validate_query_benchmark


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_qa(
    *,
    case_id: str,
    query_benchmark: dict[str, Any],
    session_events: list[dict[str, Any]],
    task_wiki_state: dict[str, Any],
) -> dict[str, Any]:
    benchmark = validate_query_benchmark(query_benchmark)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped["overall"] = benchmark["queries"]
    for query in benchmark["queries"]:
        grouped[query["failure_mode"]].append(query)

    query_results = []
    for query in benchmark["queries"]:
        answer = build_task_wiki_answer(task_wiki_state, session_events, query)
        deterministic = deterministic_answer_checks(
            query,
            answer["answer_text"],
            answer["citations"],
            citation_message_ids=answer.get("citation_message_ids") or [],
        )
        semantic = semantic_judge(query, answer["answer_text"], answer["citations"])
        query_results.append(
            {
                "query_id": query["query_id"],
                "failure_mode": query["failure_mode"],
                "answer_text": answer["answer_text"],
                "citations": answer["citations"],
                "deterministic": deterministic,
                "semantic": semantic,
            }
        )

    def compute(results: list[dict[str, Any]]) -> dict[str, Any]:
        if not results:
            return {
                "answer_point_coverage": 0.0,
                "faithfulness": 0.0,
                "citation_traceability": 0.0,
                "stale_answer_rate": 0.0,
            }
        return {
            "answer_point_coverage": round(
                sum(float(item["semantic"].get("answer_point_coverage") or 0.0) for item in results) / len(results),
                4,
            ),
            "faithfulness": round(
                sum(float(item["semantic"].get("faithfulness") or 0.0) for item in results) / len(results),
                4,
            ),
            "citation_traceability": round(
                sum(1 for item in results if item["deterministic"].get("citation_traceability")) / len(results),
                4,
            ),
            "stale_answer_rate": round(
                sum(1 for item in results if item["semantic"].get("stale_answer")) / len(results),
                4,
            ),
        }

    report = {
        "case_id": case_id,
        "overall": compute(query_results),
        "by_failure_mode": {
            key: compute([item for item in query_results if item["failure_mode"] == key])
            for key in grouped
            if key != "overall"
        },
        "queries": query_results,
        "judge_mode": query_results[0]["semantic"].get("judge_mode") if query_results else "heuristic_fallback",
    }
    return validate_qa_eval(report)
