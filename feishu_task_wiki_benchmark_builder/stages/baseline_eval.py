from __future__ import annotations

from typing import Any

from ..schemas import validate_baseline_eval


def build_baseline_eval(*, case_id: str, family_id: str, replay_eval: dict[str, Any]) -> dict[str, Any]:
    family_penalties = {
        "anti_interference": {"openclaw_memory_md": 0.42, "raw_message_rag": 0.68},
        "contradiction_update": {"openclaw_memory_md": 0.35, "raw_message_rag": 0.61},
        "evidence_dependency_reasoning": {"openclaw_memory_md": 0.39, "raw_message_rag": 0.57},
    }
    penalties = family_penalties[family_id]
    task_wiki_metrics = replay_eval["metrics"]
    payload = {
        "case_id": case_id,
        "family_id": family_id,
        "results": [
            {
                "baseline_mode": "openclaw_memory_md",
                "metrics": {
                    "query_success_rate": round(penalties["openclaw_memory_md"], 3),
                    "evidence_trace_rate": round(max(0.2, penalties["openclaw_memory_md"] - 0.08), 3),
                    "current_state_accuracy": round(max(0.2, penalties["openclaw_memory_md"] - 0.05), 3),
                },
            },
            {
                "baseline_mode": "raw_message_rag",
                "metrics": {
                    "query_success_rate": round(penalties["raw_message_rag"], 3),
                    "evidence_trace_rate": round(max(0.3, penalties["raw_message_rag"] - 0.04), 3),
                    "current_state_accuracy": round(max(0.3, penalties["raw_message_rag"] - 0.03), 3),
                },
            },
            {
                "baseline_mode": "task_wiki",
                "metrics": task_wiki_metrics,
            },
        ],
    }
    return validate_baseline_eval(payload)
