from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def execute_command_plan(*, case_id: str, command_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start = datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc)
    results: list[dict[str, Any]] = []
    for index, command in enumerate(command_plan, start=1):
        timestamp = start + timedelta(minutes=index * 7)
        results.append(
            {
                "execution_id": f"{case_id}_exec_{index:03d}",
                "command_id": command["command_id"],
                "beat_id": command["beat_id"],
                "actor_id": command["actor_id"],
                "session_id": command["session_id"],
                "message_text": command["message_text"],
                "executed_at": timestamp.isoformat(),
                "status": "sent",
                "message_id": f"msg_{index:03d}",
            }
        )
    return results
