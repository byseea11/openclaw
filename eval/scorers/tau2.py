"""tau2 summary scorer."""

from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any

from eval.base import BenchmarkScorer
from eval.scorers.common import dump_json


class Tau2Scorer(BenchmarkScorer):
    benchmark_name = "tau2"

    def save_outputs(self, rows: list[dict[str, Any]], output_path: str | Path) -> None:
        dump_json(rows, output_path)

    def score(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "benchmark": self.benchmark_name,
                "task_count": 0,
                "success_rate": 0.0,
                "average_reward": 0.0,
            }
        rewards = [float(row.get("reward") or 0.0) for row in rows]
        successes = [1.0 if row.get("success") else 0.0 for row in rows]
        return {
            "benchmark": self.benchmark_name,
            "task_count": len(rows),
            "success_rate": round(mean(successes), 4),
            "average_reward": round(mean(rewards), 4),
        }
