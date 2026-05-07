from __future__ import annotations

import json
import shutil
import subprocess
from collections import deque
from typing import Any, Callable

from ..schemas import validate_execution_plan, validate_execution_result

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=True)


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text.strip()) if text.strip() else {}
    except json.JSONDecodeError:
        return {"stdout": text.strip()}


def _extract_string_field(payload: Any, *keys: str) -> str:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _extract_string_field(value, *keys)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_string_field(item, *keys)
            if found:
                return found
    return ""


def _extract_message_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message_id", "messageId", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _extract_message_id(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_message_id(item)
            if found:
                return found
    return ""


def preflight(
    *,
    lark_cli_bin: str = "lark-cli",
    runner: Runner | None = None,
    operator_identity: str = "user",
) -> dict[str, Any]:
    available = shutil.which(lark_cli_bin) is not None
    result: dict[str, Any] = {
        "lark_cli_available": available,
        "operator_identity": operator_identity,
        "auth_ok": False,
        "im_capabilities_ok": False,
        "warnings": [],
    }
    if not available:
        result["warnings"].append("lark-cli not found on PATH")
        return result
    if runner is None:
        result["warnings"].append("auth status not checked")
        return result
    completed = runner([lark_cli_bin, "auth", "status"])
    result["auth_status"] = _safe_json(completed.stdout)
    result["auth_ok"] = completed.returncode == 0
    result["im_capabilities_ok"] = completed.returncode == 0
    if completed.returncode != 0:
        result["warnings"].append("lark-cli auth status failed")
    return result


def _topological_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {action["action_id"]: action for action in actions}
    indegree = {action["action_id"]: 0 for action in actions}
    graph: dict[str, list[str]] = {action["action_id"]: [] for action in actions}
    for action in actions:
        for dep in action.get("depends_on", []):
            if dep in by_id:
                indegree[action["action_id"]] += 1
                graph[dep].append(action["action_id"])
    queue = deque(sorted(action_id for action_id, degree in indegree.items() if degree == 0))
    ordered: list[dict[str, Any]] = []
    while queue:
        action_id = queue.popleft()
        ordered.append(by_id[action_id])
        for neighbor in sorted(graph[action_id]):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)
    if len(ordered) != len(actions):
        raise ValueError("execution_plan contains a dependency cycle")
    return ordered


def _action_command(
    action: dict[str, Any],
    *,
    lark_cli_bin: str,
    created_resources: dict[str, dict[str, Any]],
    operator_identity: str,
) -> list[str]:
    params = action["params"]
    action_type = action["action_type"]
    if action_type == "create_chat":
        command = [lark_cli_bin, "im", "+chat-create", "--name", str(params["name"])]
        users = [str(item).strip() for item in params.get("users", []) if str(item).strip().startswith("ou_")]
        if users:
            command.extend(["--users", ",".join(users), "--type", "public"])
        command.extend(["--as", operator_identity])
        return command
    if action_type == "send_message":
        chat_ref = str(params["chat_ref"])
        chat_id = created_resources.get(chat_ref, {}).get("chat_id", chat_ref)
        return [
            lark_cli_bin,
            "im",
            "+messages-send",
            "--chat-id",
            str(chat_id),
            "--text",
            str(params["content_text"]),
            "--as",
            operator_identity,
        ]
    if action_type == "reply_in_thread":
        root_ref = str(params["root_message_ref"])
        root_message_id = created_resources.get(root_ref, {}).get("message_id", root_ref)
        return [
            lark_cli_bin,
            "im",
            "+messages-reply",
            "--message-id",
            str(root_message_id),
            "--text",
            str(params["content_text"]),
            "--reply-in-thread",
            "--as",
            operator_identity,
        ]
    if action_type == "fetch_chat_messages":
        chat_ref = str(params["chat_ref"])
        chat_id = created_resources.get(chat_ref, {}).get("chat_id", chat_ref)
        return [
            lark_cli_bin,
            "im",
            "+chat-messages-list",
            "--chat-id",
            str(chat_id),
            "--sort",
            "asc",
            "--page-size",
            "50",
            "--format",
            "json",
            "--as",
            operator_identity,
        ]
    if action_type == "fetch_thread_messages":
        root_ref = str(params["root_message_ref"])
        root_resource = created_resources.get(root_ref, {})
        thread_id = root_resource.get("thread_id") or root_resource.get("message_id") or root_ref
        return [
            lark_cli_bin,
            "im",
            "+threads-messages-list",
            "--thread",
            str(thread_id),
            "--sort",
            "asc",
            "--page-size",
            "50",
            "--format",
            "json",
            "--as",
            operator_identity,
        ]
    raise ValueError(f"Unsupported action_type: {action_type}")


def execute_plan(
    execution_plan: dict[str, Any],
    *,
    runner: Runner | None = None,
    lark_cli_bin: str = "lark-cli",
    dry_run: bool = False,
    resume_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = validate_execution_plan(execution_plan)
    active_runner = runner or default_runner
    existing_successes = {
        row["action_id"]: row
        for row in (resume_result or {}).get("action_status", [])
        if row.get("status") == "success"
    }
    created_resources: dict[str, dict[str, Any]] = dict((resume_result or {}).get("created_resources") or {})
    thread_id_to_chat_id: dict[str, str] = dict((resume_result or {}).get("thread_id_to_chat_id") or {})
    action_status = list((resume_result or {}).get("action_status") or [])
    preflight_result = preflight(
        lark_cli_bin=lark_cli_bin,
        runner=None if dry_run else active_runner,
        operator_identity=plan["operator_identity"],
    )
    for action in _topological_actions(plan["actions"]):
        action_id = action["action_id"]
        if action_id in existing_successes:
            continue
        command = _action_command(
            action,
            lark_cli_bin=lark_cli_bin,
            created_resources=created_resources,
            operator_identity=plan["operator_identity"],
        )
        if dry_run:
            action_status.append({"action_id": action_id, "status": "dry_run", "command": command})
            continue
        completed = active_runner(command)
        parsed = _safe_json(completed.stdout)
        status = "success" if completed.returncode == 0 else "failed"
        row = {
            "action_id": action_id,
            "status": status,
            "command": command,
            "stdout": parsed,
            "stderr": completed.stderr.strip(),
            "returncode": completed.returncode,
        }
        output_ref = str(action.get("output_ref") or "").strip()
        if status == "success" and output_ref:
            resource: dict[str, Any] = {}
            if action["action_type"] == "create_chat":
                resource["chat_id"] = _extract_string_field(parsed, "chat_id", "chatId", "id") or output_ref
            elif action["action_type"] in {"send_message", "reply_in_thread"}:
                message_id = _extract_message_id(parsed) or output_ref
                resource["message_id"] = message_id
                if action["action_type"] == "reply_in_thread":
                    resource["thread_id"] = _extract_string_field(parsed, "thread_id", "threadId") or message_id
                chat_ref = str(action["params"].get("chat_ref") or "")
                chat_id = created_resources.get(chat_ref, {}).get("chat_id")
                if chat_id:
                    resource["chat_id"] = chat_id
                if resource.get("thread_id") and resource.get("chat_id"):
                    thread_id_to_chat_id[str(resource["thread_id"])] = str(resource["chat_id"])
            created_resources[output_ref] = resource
        action_status.append(row)
        if status != "success":
            break
    result = {
        "case_id": plan["case_id"],
        "status": "success" if all(row["status"] in {"success", "dry_run"} for row in action_status) else "failed",
        "operator_identity": plan["operator_identity"],
        "delivery_mode": plan["delivery_mode"],
        "created_resources": created_resources,
        "thread_id_to_chat_id": thread_id_to_chat_id,
        "action_status": action_status,
        "preflight": preflight_result,
    }
    return validate_execution_result(result)


def execution_result_rows(execution_result: dict[str, Any]) -> list[dict[str, Any]]:
    result = validate_execution_result(execution_result)
    return [
        {
            "execution_id": f"{result['case_id']}_{row['action_id']}",
            **row,
        }
        for row in result["action_status"]
    ]
