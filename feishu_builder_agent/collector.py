from __future__ import annotations

from datetime import datetime, timezone
import subprocess
from typing import Any, Callable

from .executor import Runner, _action_command, _safe_json, default_runner
from .schemas import validate_execution_plan, validate_execution_result


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collect_fetch_records(
    execution_plan: dict[str, Any],
    execution_result: dict[str, Any],
    *,
    runner: Runner | None = None,
    lark_cli_bin: str = "lark-cli",
    fetch_identity: str = "user",
) -> list[dict[str, Any]]:
    plan = validate_execution_plan(execution_plan)
    result = validate_execution_result(execution_result)
    runner = runner or default_runner
    created_resources = result["created_resources"]
    rows: list[dict[str, Any]] = []
    for action in plan["actions"]:
        if action["action_type"] not in {"fetch_chat_messages", "fetch_thread_messages"}:
            continue
        command = _action_command(
            action,
            lark_cli_bin=lark_cli_bin,
            created_resources=created_resources,
            operator_identity=fetch_identity,
        )
        completed = runner(command)
        rows.append(
            {
                "record_id": f"fetch-{action['action_id']}",
                "domain": "im",
                "kind": "chat_messages_fetch" if action["action_type"] == "fetch_chat_messages" else "thread_messages_fetch",
                "captured_at": utc_now_iso(),
                "identity": fetch_identity,
                "command": " ".join(command),
                "response": _safe_json(completed.stdout),
                "stderr": completed.stderr.strip(),
                "returncode": completed.returncode,
            }
        )
    return rows
