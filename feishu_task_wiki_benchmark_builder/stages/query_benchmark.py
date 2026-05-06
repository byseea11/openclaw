from __future__ import annotations

from typing import Any

from ..schemas import validate_query_benchmark


def build_query_benchmark(
    *,
    case_id: str,
    family_id: str,
    story_plan: dict[str, Any],
    annotation_gold_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    supporting_ids = [row["message_id"] for row in annotation_gold_rows]
    payload = {
        "case_id": case_id,
        "family_id": family_id,
        "queries": [
            {
                "query_id": f"{case_id}_query_{index:03d}",
                "query": probe["query"],
                "expected_good_behavior": probe["expected_good_behavior"],
                "supporting_message_ids": supporting_ids,
            }
            for index, probe in enumerate(story_plan["planned_probe_queries"], start=1)
        ],
    }
    return validate_query_benchmark(payload)
