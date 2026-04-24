"""CrossDeptMem scorer and output writer."""

from __future__ import annotations

from pathlib import Path
import re
from statistics import mean
from typing import Any

from eval.base import BenchmarkScorer
from eval.scorers.common import answer_f1, dump_json, dump_jsonl, exact_match, normalize_answer


_STRUCTURED_ID_RE = re.compile(r"\b(?:[A-Z][A-Z0-9]+-\d+|AP-\d+|TASK-\d+)\b", re.IGNORECASE)


def _structured_ids(text: str | None) -> set[str]:
    return {match.group(0).upper() for match in _STRUCTURED_ID_RE.finditer(text or "")}


def _evidence_matches(gold_texts: list[str], snippet: str) -> bool:
    normalized_snippet = normalize_answer(snippet)
    snippet_ids = _structured_ids(snippet)
    for gold_text in gold_texts:
        normalized_gold = normalize_answer(gold_text)
        if not normalized_gold and not normalized_snippet:
            return True
        if not normalized_gold or not normalized_snippet:
            continue
        if normalized_gold in normalized_snippet or normalized_snippet in normalized_gold:
            return True
        token_f1 = answer_f1(snippet, gold_text)
        if token_f1 >= 0.6:
            return True
        gold_ids = _structured_ids(gold_text)
        if gold_ids and snippet_ids and gold_ids.intersection(snippet_ids) and token_f1 >= 0.35:
            return True
    return False


def _token_recall(prediction: str, gold: str) -> float:
    pred_tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalize_answer(prediction), re.IGNORECASE)
    gold_tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalize_answer(gold), re.IGNORECASE)
    if not gold_tokens:
        return 1.0
    if not pred_tokens:
        return 0.0
    pred_counts: dict[str, int] = {}
    gold_counts: dict[str, int] = {}
    for token in pred_tokens:
        pred_counts[token] = pred_counts.get(token, 0) + 1
    for token in gold_tokens:
        gold_counts[token] = gold_counts.get(token, 0) + 1
    overlap = 0
    for token, count in gold_counts.items():
        overlap += min(count, pred_counts.get(token, 0))
    return overlap / len(gold_tokens)


def _answer_score(prediction: str, gold: str) -> float:
    normalized_prediction = normalize_answer(prediction)
    normalized_gold = normalize_answer(gold)
    if not normalized_prediction and not normalized_gold:
        return 1.0
    if not normalized_prediction or not normalized_gold:
        return 0.0
    if normalized_prediction == normalized_gold:
        return 1.0
    if normalized_gold in normalized_prediction or normalized_prediction in normalized_gold:
        return 1.0
    gold_ids = _structured_ids(gold)
    prediction_ids = _structured_ids(prediction)
    token_recall = _token_recall(prediction, gold)
    if token_recall >= 0.85 and (not gold_ids or gold_ids.issubset(prediction_ids)):
        return 1.0
    return answer_f1(prediction, gold)


def _recall_at_k(
    retrieval_results: list[dict[str, Any]],
    gold_evidence_items: list[dict[str, Any]],
    *,
    k: int,
) -> float:
    if not gold_evidence_items:
        return 1.0
    top_results = retrieval_results[: max(0, k)]
    if not top_results:
        return 0.0
    hits = 0
    for gold_item in gold_evidence_items:
        gold_texts = [
            str(text).strip()
            for text in gold_item.get("texts", [])
            if isinstance(text, str) and str(text).strip()
        ]
        if not gold_texts:
            continue
        if any(_evidence_matches(gold_texts, str(result.get("snippet") or "")) for result in top_results):
            hits += 1
    return hits / len(gold_evidence_items)


class CrossDeptMemScorer(BenchmarkScorer):
    benchmark_name = "cross_dept_mem"

    def save_outputs(self, rows: list[dict[str, Any]], output_path: str | Path) -> None:
        """Save outputs in both official and detailed formats."""
        official_rows = [
            {
                "sample_id": row.get("sample_id"),
                "query_id": row.get("query_id"),
                "predicted_answer": row.get("predicted_answer"),
                "exact_match": row.get("exact_match"),
                "f1": row.get("f1"),
                "recall_at_5": row.get("recall_at_5"),
                "recall_at_10": row.get("recall_at_10"),
            }
            for row in rows
        ]
        dump_jsonl(official_rows, output_path)
        details_path = Path(output_path).with_suffix(".details.json")
        dump_json(rows, details_path)

    def score(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate metrics for CrossDeptMem benchmark."""
        if not rows:
            return {
                "benchmark": self.benchmark_name,
                "sample_count": 0,
                "query_count": 0,
                "exact_match": 0.0,
                "average_f1": 0.0,
                "average_recall_at_5": 0.0,
                "average_recall_at_10": 0.0,
                "average_latency_ms": 0.0,
                "average_prompt_tokens": 0.0,
                "average_memory_search_calls": 0.0,
                "average_memory_get_calls": 0.0,
                "average_memory_tool_calls": 0.0,
                "buckets": {},
            }

        # Enrich rows with computed metrics
        enriched = []
        for row in rows:
            predicted = str(row.get("predicted_answer") or "")
            gold = str(row.get("gold_answer") or "")
            tool_calls = row.get("tool_calls", [])
            retrieval_results = [
                dict(item) for item in row.get("retrieval_results", []) if isinstance(item, dict)
            ]
            gold_evidence_items = [
                dict(item) for item in row.get("gold_evidence_items", []) if isinstance(item, dict)
            ]

            # Count memory_search calls
            memory_search_calls = sum(
                1 for call in tool_calls if call.get("tool") == "memory_search"
            )
            memory_get_calls = sum(1 for call in tool_calls if call.get("tool") == "memory_get")
            memory_tool_calls = memory_search_calls + memory_get_calls

            recall_at_5 = (
                _recall_at_k(retrieval_results, gold_evidence_items, k=5)
                if row.get("retrieval_probe_status") != "missing_tool_output"
                or retrieval_results
                else 0.0
            )
            recall_at_10 = (
                _recall_at_k(retrieval_results, gold_evidence_items, k=10)
                if row.get("retrieval_probe_status") != "missing_tool_output"
                or retrieval_results
                else 0.0
            )

            enriched.append(
                {
                    **row,
                    "exact_match": exact_match(predicted, gold),
                    "f1": _answer_score(predicted, gold),
                    "memory_search_calls": memory_search_calls,
                    "memory_get_calls": memory_get_calls,
                    "memory_tool_calls": memory_tool_calls,
                    "recall_at_5": round(recall_at_5, 4),
                    "recall_at_10": round(recall_at_10, 4),
                }
            )

        rows[:] = enriched

        # Compute overall metrics
        overall = {
            "benchmark": self.benchmark_name,
            "sample_count": len({row.get("sample_id") for row in rows}),
            "query_count": len(rows),
            "exact_match": round(mean(float(row["exact_match"]) for row in rows), 4),
            "average_f1": round(mean(float(row["f1"]) for row in rows), 4),
            "average_recall_at_5": round(mean(float(row["recall_at_5"]) for row in rows), 4),
            "average_recall_at_10": round(mean(float(row["recall_at_10"]) for row in rows), 4),
            "average_latency_ms": round(
                mean(float(row.get("latency_ms") or 0.0) for row in rows),
                3,
            ),
            "average_prompt_tokens": round(
                mean(float(row.get("prompt_tokens") or 0.0) for row in rows),
                1,
            ),
            "average_memory_search_calls": round(
                mean(float(row.get("memory_search_calls") or 0.0) for row in rows),
                2,
            ),
            "average_memory_get_calls": round(
                mean(float(row.get("memory_get_calls") or 0.0) for row in rows),
                2,
            ),
            "average_memory_tool_calls": round(
                mean(float(row.get("memory_tool_calls") or 0.0) for row in rows),
                2,
            ),
        }

        # Compute per-query-type buckets
        buckets: dict[str, dict[str, Any]] = {}
        for query_type in {"state", "why", "timeline", "list_relation"}:
            bucket_rows = [row for row in rows if row.get("query_type") == query_type]
            if bucket_rows:
                buckets[query_type] = {
                    "count": len(bucket_rows),
                    "exact_match": round(mean(float(row["exact_match"]) for row in bucket_rows), 4),
                    "average_f1": round(mean(float(row["f1"]) for row in bucket_rows), 4),
                    "average_recall_at_5": round(
                        mean(float(row["recall_at_5"]) for row in bucket_rows),
                        4,
                    ),
                    "average_recall_at_10": round(
                        mean(float(row["recall_at_10"]) for row in bucket_rows),
                        4,
                    ),
                    "average_prompt_tokens": round(
                        mean(float(row.get("prompt_tokens") or 0.0) for row in bucket_rows),
                        1,
                    ),
                    "average_memory_search_calls": round(
                        mean(float(row.get("memory_search_calls") or 0.0) for row in bucket_rows),
                        2,
                    ),
                    "average_memory_get_calls": round(
                        mean(float(row.get("memory_get_calls") or 0.0) for row in bucket_rows),
                        2,
                    ),
                    "average_memory_tool_calls": round(
                        mean(float(row.get("memory_tool_calls") or 0.0) for row in bucket_rows),
                        2,
                    ),
                }

        overall["buckets"] = buckets
        return overall
