"""LoCoMo scorer and output writer."""

from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any

from eval.base import BenchmarkScorer
from eval.scorers.common import answer_f1, dump_json, exact_match


class LoCoMoScorer(BenchmarkScorer):
    benchmark_name = "locomo"

    def save_outputs(self, rows: list[dict[str, Any]], output_path: str | Path) -> None:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            sample_id = str(row.get("sample_id") or "")
            sample = grouped.setdefault(sample_id, {"sample_id": sample_id, "qa": []})
            sample["qa"].append(
                {
                    "qa_index": row.get("qa_index"),
                    "question": row.get("question"),
                    "answer": row.get("gold_answer"),
                    "evidence": row.get("gold_evidence"),
                    "category": row.get("category"),
                    "prediction": row.get("prediction"),
                    "exact_match": row.get("exact_match"),
                    "f1": row.get("f1"),
                    "latency_ms": row.get("latency_ms"),
                }
            )
        ordered = [grouped[key] for key in sorted(grouped)]
        dump_json(ordered, output_path)

    def score(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "benchmark": self.benchmark_name,
                "sample_count": 0,
                "qa_count": 0,
                "average_exact_match": 0.0,
                "average_f1": 0.0,
                "average_latency_ms": 0.0,
            }

        enriched = []
        for row in rows:
            enriched.append(
                {
                    **row,
                    "exact_match": exact_match(row.get("prediction"), row.get("gold_answer")),
                    "f1": answer_f1(row.get("prediction"), row.get("gold_answer")),
                }
            )
        rows[:] = enriched
        return {
            "benchmark": self.benchmark_name,
            "sample_count": len({str(row.get("sample_id") or "") for row in rows}),
            "qa_count": len(rows),
            "average_exact_match": round(mean(float(row["exact_match"]) for row in rows), 4),
            "average_f1": round(mean(float(row["f1"]) for row in rows), 4),
            "average_latency_ms": round(
                mean(float(row.get("latency_ms") or 0.0) for row in rows),
                3,
            ),
        }
