from __future__ import annotations

from typing import Any


def collect_messages(*, case_id: str, execution_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collected: list[dict[str, Any]] = []
    ingress: list[dict[str, Any]] = []
    for row in execution_rows:
        collected_row = {
            "case_id": case_id,
            "message_id": row["message_id"],
            "beat_id": row["beat_id"],
            "actor_id": row["actor_id"],
            "session_id": row["session_id"],
            "message_text": row["message_text"],
            "observed_at": row["executed_at"],
        }
        ingress_row = {
            "message_id": row["message_id"],
            "content": row["message_text"],
            "source_session": row["session_id"],
            "captured_at": row["executed_at"],
        }
        collected.append(collected_row)
        ingress.append(ingress_row)
    return collected, ingress
