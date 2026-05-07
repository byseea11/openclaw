"""Replay a frozen office snapshot into a Feishu test workspace via OpenClaw CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval_old.office_dataset import capture_dir, load_snapshot_bundle, utc_now_iso
from eval_old.scorers.common import dump_json, dump_jsonl

Executor = Callable[..., subprocess.CompletedProcess[str]]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_feishu_injection_message(event: dict[str, Any], employee_by_open_id: dict[str, dict[str, Any]]) -> str:
    sender_open_id = str(event.get("sender_open_id") or "")
    employee = employee_by_open_id.get(sender_open_id, {})
    actor_name = str(employee.get("name") or event.get("sender_name") or sender_open_id or "Unknown")
    department = str(employee.get("department_name") or "Unknown department")
    title = str(employee.get("title") or "Unknown title")
    metadata = {
        "event_id": event.get("event_id"),
        "snapshot_id": event.get("snapshot_id"),
        "event_time": event.get("event_time"),
        "thread_id": event.get("thread_id"),
        "message_type": event.get("message_type"),
        "mentions": event.get("mentions") or [],
        "task_refs": event.get("task_refs") or [],
        "approval_refs": event.get("approval_refs") or [],
        "doc_refs": event.get("doc_refs") or [],
        "attachments": event.get("attachments") or [],
    }
    card_payload = event.get("card_payload")
    card_section = f"\nCard payload: {_json_dumps(card_payload)}" if card_payload else ""
    return (
        f"[Dataset actor: {actor_name} / {department} / {title}]\n"
        f"[Dataset event metadata: {_json_dumps(metadata)}]\n"
        f"{event.get('content_text') or ''}"
        f"{card_section}"
    ).strip()


def _extract_message_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("messageId", "message_id", "id"):
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


def _parse_stdout_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {"stdout": stripped}


def _build_command(
    *,
    openclaw_bin: str,
    target_chat_id: str,
    message: str,
    account_id: str | None = None,
    reply_to_message_id: str | None = None,
) -> list[str]:
    command = [
        openclaw_bin,
        "message",
        "send",
        "--channel",
        "feishu",
        "--target",
        target_chat_id,
        "--message",
        message,
        "--json",
    ]
    if account_id:
        command.extend(["--account-id", account_id])
    if reply_to_message_id:
        command.extend(["--reply-to", reply_to_message_id])
    return command


def _env_with_gateway(gateway_url: str | None, gateway_token: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if gateway_url:
        env["OPENCLAW_GATEWAY_URL"] = gateway_url
    if gateway_token:
        env["OPENCLAW_GATEWAY_TOKEN"] = gateway_token
    return env


def inject_snapshot_to_feishu(
    *,
    root_dir: str | Path,
    snapshot_id: str,
    target_chat_id: str,
    capture_id: str,
    gateway_url: str | None = None,
    gateway_token: str | None = None,
    account_id: str | None = None,
    openclaw_bin: str = "openclaw",
    dry_run: bool = False,
    event_ids: set[str] | None = None,
    inter_message_delay_ms: float = 0.0,
    executor: Executor = subprocess.run,
) -> dict[str, Any]:
    bundle = load_snapshot_bundle(root_dir, snapshot_id)
    employees = bundle["employees"]
    events = [
        event
        for event in bundle["events"]
        if not event_ids or str(event.get("event_id") or "") in event_ids
    ]
    employee_by_open_id = {employee["open_id"]: employee for employee in employees}
    delivered_message_by_snapshot_message: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    output_dir = capture_dir(root_dir, capture_id)
    if output_dir.exists() and not dry_run:
        raise FileExistsError(f"Capture/injection output already exists: {output_dir}")

    for event in events:
        message = build_feishu_injection_message(event, employee_by_open_id)
        reply_to = delivered_message_by_snapshot_message.get(str(event.get("reply_to_message_id") or ""))
        command = _build_command(
            openclaw_bin=openclaw_bin,
            target_chat_id=target_chat_id,
            message=message,
            account_id=account_id,
            reply_to_message_id=reply_to or None,
        )
        if dry_run:
            results.append(
                {
                    "event_id": event.get("event_id"),
                    "snapshot_message_id": event.get("message_id"),
                    "reply_to_snapshot_message_id": event.get("reply_to_message_id"),
                    "reply_to_delivered_message_id": reply_to,
                    "command": command[:8] + ["<message omitted>", *command[9:]],
                    "status": "dry_run",
                }
            )
            continue

        completed = executor(
            command,
            check=False,
            text=True,
            capture_output=True,
            env=_env_with_gateway(gateway_url, gateway_token),
        )
        parsed_stdout = _parse_stdout_json(completed.stdout)
        delivered_message_id = _extract_message_id(parsed_stdout)
        if delivered_message_id and event.get("message_id"):
            delivered_message_by_snapshot_message[str(event["message_id"])] = delivered_message_id
        row = {
            "event_id": event.get("event_id"),
            "snapshot_id": snapshot_id,
            "snapshot_message_id": event.get("message_id"),
            "target_chat_id": target_chat_id,
            "reply_to_snapshot_message_id": event.get("reply_to_message_id"),
            "reply_to_delivered_message_id": reply_to,
            "delivered_message_id": delivered_message_id,
            "returncode": completed.returncode,
            "stdout": parsed_stdout,
            "stderr": completed.stderr.strip(),
            "sent_at": utc_now_iso(),
        }
        results.append(row)
        if completed.returncode != 0:
            break
        if inter_message_delay_ms > 0:
            time.sleep(inter_message_delay_ms / 1000)

    summary = {
        "snapshot_id": snapshot_id,
        "capture_id": capture_id,
        "target_chat_id": target_chat_id,
        "dry_run": dry_run,
        "event_count": len(events),
        "sent_count": sum(1 for row in results if row.get("returncode") == 0),
        "failed_count": sum(1 for row in results if row.get("returncode") not in (None, 0)),
        "result_count": len(results),
    }

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=False)
        dump_json(
            {
                "capture_id": capture_id,
                "snapshot_id": snapshot_id,
                "source": "openclaw_cli_feishu_injection_ledger",
                "target_chat_id": target_chat_id,
                "created_at": utc_now_iso(),
                "note": "This directory records injection delivery results. Feishu callback capture should write office_events.jsonl separately before freezing a true captured snapshot.",
            },
            output_dir / "capture-metadata.json",
        )
        dump_jsonl(results, output_dir / "injection-results.jsonl")
        dump_json(summary, output_dir / "injection-summary.json")

    return {"summary": summary, "results": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay a frozen office snapshot into a Feishu test workspace.")
    parser.add_argument("--root-dir", default="eval/office_dataset")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--target-chat-id", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--gateway-url")
    parser.add_argument("--gateway-token")
    parser.add_argument("--account-id")
    parser.add_argument("--openclaw-bin", default="openclaw")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--event-id", action="append", dest="event_ids")
    parser.add_argument("--inter-message-delay-ms", type=float, default=0.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = inject_snapshot_to_feishu(
        root_dir=args.root_dir,
        snapshot_id=args.snapshot_id,
        target_chat_id=args.target_chat_id,
        capture_id=args.capture_id,
        gateway_url=args.gateway_url,
        gateway_token=args.gateway_token,
        account_id=args.account_id,
        openclaw_bin=args.openclaw_bin,
        dry_run=args.dry_run,
        event_ids=set(args.event_ids or []) or None,
        inter_message_delay_ms=args.inter_message_delay_ms,
    )
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
