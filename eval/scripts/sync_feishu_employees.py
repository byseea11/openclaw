"""Sync employees.json from a real Feishu workspace through OpenClaw tools."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.env import resolve_openclaw_token
from eval.office_dataset import EMPLOYEES_JSON, export_employees_csv
from eval.openclaw_client import OpenClawEvalClient
from eval.scorers.common import dump_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Feishu chat members into employees.json.")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--gateway-token")
    parser.add_argument(
        "--chat-id",
        action="append",
        dest="chat_ids",
        default=[],
        help="Repeat for each Feishu chat to crawl members from.",
    )
    parser.add_argument("--output-dir", default="eval/office_dataset")
    parser.add_argument("--session-key", default="eval:feishu_employee_sync")
    parser.add_argument("--message-channel", default="feishu")
    parser.add_argument("--workspace-id", default="")
    return parser


def _tool_result_items(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        details = payload.get("details")
        if isinstance(details, dict):
            payload = details
    if not isinstance(payload, dict):
        return []
    members = payload.get("members")
    if isinstance(members, list):
        return [item for item in members if isinstance(item, dict)]
    return []


def main() -> None:
    args = build_parser().parse_args()
    if not args.chat_ids:
        raise SystemExit("At least one --chat-id is required.")

    client = OpenClawEvalClient(
        args.gateway_url,
        token=resolve_openclaw_token(args.gateway_token),
    )

    employees_by_open_id: dict[str, dict] = {}
    for chat_id in args.chat_ids:
        members_response = client.invoke_tool(
            session_key=args.session_key,
            tool="feishu_chat",
            args={"action": "members", "chat_id": chat_id, "member_id_type": "open_id"},
            message_channel=args.message_channel,
        )
        if not members_response.ok:
            raise SystemExit(f"feishu_chat members failed for {chat_id}: {members_response.raw_payload}")

        for member in _tool_result_items(members_response.result):
            member_id = str(member.get("member_id") or "").strip()
            if not member_id or member_id in employees_by_open_id:
                continue
            info_response = client.invoke_tool(
                session_key=args.session_key,
                tool="feishu_chat",
                args={"action": "member_info", "member_id": member_id, "member_id_type": "open_id"},
                message_channel=args.message_channel,
            )
            if not info_response.ok or not isinstance(info_response.result, dict):
                continue
            details = info_response.result.get("details")
            if not isinstance(details, dict):
                continue
            open_id = str(details.get("open_id") or member_id).strip()
            employees_by_open_id[open_id] = {
                "employee_id": str(details.get("employee_no") or open_id).strip(),
                "open_id": open_id,
                "name": str(details.get("name") or member.get("name") or open_id).strip(),
                "department_id": (
                    str((details.get("department_ids") or [""])[0] or "").strip()
                    if isinstance(details.get("department_ids"), list)
                    else ""
                ),
                "department_name": "",
                "title": str(details.get("job_title") or "").strip(),
                "manager_id": str(details.get("leader_user_id") or "").strip(),
                "employment_status": "active",
                "aliases": list(
                    {
                        str(alias).strip()
                        for alias in [
                            details.get("en_name"),
                            details.get("nickname"),
                            details.get("enterprise_email"),
                        ]
                        if str(alias or "").strip()
                    }
                ),
                "workspace_id": args.workspace_id,
                "source_chat_ids": [chat_id],
            }

    employees = sorted(employees_by_open_id.values(), key=lambda item: (item["employee_id"], item["open_id"]))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dump_json({"employees": employees}, output_dir / EMPLOYEES_JSON)
    export_employees_csv(employees, output_dir / "employees.csv")
    print(f"Wrote {len(employees)} employees to {output_dir / EMPLOYEES_JSON}")


if __name__ == "__main__":
    main()
