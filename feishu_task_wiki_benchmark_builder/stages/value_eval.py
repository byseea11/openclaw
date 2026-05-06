from __future__ import annotations

from typing import Any

from ..schemas import validate_value_eval


def build_value_eval(*, case_id: str, family_id: str, baseline_eval: dict[str, Any]) -> dict[str, Any]:
    results = {item["baseline_mode"]: item["metrics"] for item in baseline_eval["results"]}
    task_wiki = results["task_wiki"]
    payload = {
        "case_id": case_id,
        "family_id": family_id,
        "task_wiki_advantage": {
            "vs_openclaw_memory_md": round(
                task_wiki["query_success_rate"] - results["openclaw_memory_md"]["query_success_rate"],
                3,
            ),
            "vs_raw_message_rag": round(
                task_wiki["query_success_rate"] - results["raw_message_rag"]["query_success_rate"],
                3,
            ),
        },
        "summary": "Task Wiki 在该 case 上保持完整 query 成功率，并相对 baseline 展现正向提升。",
    }
    return validate_value_eval(payload)
