"""LongMemEval scorer and output writer."""

from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any

from eval_old.base import BenchmarkScorer
from eval_old.scorers.common import answer_f1, dump_json, dump_jsonl, exact_match, normalize_answer


class LongMemEvalScorer(BenchmarkScorer):
    benchmark_name = "longmemeval"

    def save_outputs(self, rows: list[dict[str, Any]], output_path: str | Path) -> None:
        official_rows = [
            {
                "question_id": row.get("question_id"),
                "hypothesis": row.get("hypothesis"),
            }
            for row in rows
        ]
        dump_jsonl(official_rows, output_path)
        details_path = Path(output_path).with_suffix(".details.json")
        dump_json(rows, details_path)

    def score(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "benchmark": self.benchmark_name,
                "sample_count": 0,
                "exact_match": 0.0,
                "average_f1": 0.0,
                "abstention_accuracy": 0.0,
                "average_latency_ms": 0.0,
            }

        enriched = []
        for row in rows:
            question_id = str(row.get("question_id") or "")
            hypothesis = str(row.get("hypothesis") or "")
            gold_answer = str(row.get("gold_answer") or "")
            should_abstain = question_id.endswith("_abs")
            abstention_correct = True
            if should_abstain:
                normalized = normalize_answer(hypothesis)
                abstention_correct = (
                    "don t know" in normalized
                    or "do not know" in normalized
                    or "not enough" in normalized
                )
            enriched.append(
                {
                    **row,
                    "exact_match": exact_match(hypothesis, gold_answer),
                    "f1": answer_f1(hypothesis, gold_answer),
                    "abstention_correct": float(abstention_correct),
                }
            )
        rows[:] = enriched
        return {
            "benchmark": self.benchmark_name,
            "sample_count": len(rows),
            "exact_match": round(mean(float(row["exact_match"]) for row in rows), 4),
            "average_f1": round(mean(float(row["f1"]) for row in rows), 4),
            "abstention_accuracy": round(mean(float(row["abstention_correct"]) for row in rows), 4),
            "average_latency_ms": round(
                mean(float(row.get("latency_ms") or 0.0) for row in rows),
                3,
            ),
        }
