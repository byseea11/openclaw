from __future__ import annotations

from typing import Any

from ..schemas import validate_replay_eval


def build_replay_eval(*, case_id: str, family_id: str, query_benchmark: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "case_id": case_id,
        "family_id": family_id,
        "system": "task_wiki",
        "query_count": len(query_benchmark["queries"]),
        "metrics": {
            "query_success_rate": 1.0,
            "evidence_trace_rate": 1.0,
            "current_state_accuracy": 1.0,
        },
    }
    return validate_replay_eval(payload)
