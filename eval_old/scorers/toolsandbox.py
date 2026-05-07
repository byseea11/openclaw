"""ToolSandbox summary scorer."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from eval_old.base import BenchmarkScorer
from eval_old.scorers.common import dump_json


class ToolSandboxScorer(BenchmarkScorer):
    benchmark_name = "toolsandbox"

    def save_outputs(self, rows: list[dict[str, Any]], output_path: str | Path) -> None:
        dump_json(rows, output_path)

    def score(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "benchmark": self.benchmark_name,
                "scenario_count": 0,
                "success_count": 0,
                "average_similarity": 0.0,
                "average_milestone_similarity": 0.0,
                "average_minefield_similarity": 0.0,
                "categories": {},
            }
        return {
            "benchmark": self.benchmark_name,
            "scenario_count": len(rows),
            "success_count": sum(1 for row in rows if not row.get("error")),
            "average_similarity": round(mean(float(row.get("similarity") or 0.0) for row in rows), 4),
            "average_milestone_similarity": round(
                mean(float(row.get("milestone_similarity") or 0.0) for row in rows),
                4,
            ),
            "average_minefield_similarity": round(
                mean(float(row.get("minefield_similarity") or 0.0) for row in rows),
                4,
            ),
            "categories": dict(
                Counter(category for row in rows for category in list(row.get("categories") or []))
            ),
        }
