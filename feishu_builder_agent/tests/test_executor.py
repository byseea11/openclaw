from __future__ import annotations

import subprocess
import unittest

from feishu_builder_agent.executor import execute_plan


def _runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    if command[:3] == ["lark-cli", "auth", "status"]:
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}', stderr="")
    if command[:3] == ["lark-cli", "im", "+chat-create"]:
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true,"data":{"chat_id":"oc_1"}}', stderr="")
    return subprocess.CompletedProcess(
        command,
        0,
        stdout='{"ok":true,"data":{"message_id":"om_1","thread_id":"omt_1","chat_id":"oc_1"}}',
        stderr="",
    )


PLAN = {
    "case_id": "case-1",
    "operator_identity": "user",
    "delivery_mode": "prefixed_single_operator",
    "actions": [
        {
            "action_id": "act_001",
            "action_type": "create_chat",
            "params": {"chat_ref": "main_chat", "name": "项目协作群"},
            "output_ref": "main_chat",
        },
        {
            "action_id": "act_002",
            "action_type": "send_message",
            "depends_on": ["act_001"],
            "params": {"chat_ref": "main_chat", "sender_ref": "pm_alice", "content_text": "【产品/林晨】先按内部目标推进，但暂时不要对外承诺。"},
            "output_ref": "msg_1",
        },
    ],
}


class ExecutorTests(unittest.TestCase):
    def test_dry_run_records_commands(self) -> None:
        result = execute_plan(PLAN, dry_run=True)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action_status"][0]["status"], "dry_run")

    def test_create_chat_reads_nested_chat_id(self) -> None:
        result = execute_plan(PLAN, runner=_runner)
        self.assertEqual(result["created_resources"]["main_chat"]["chat_id"], "oc_1")

    def test_resume_skips_successful_actions(self) -> None:
        resume_result = {
            "case_id": "case-1",
            "status": "success",
            "operator_identity": "user",
            "delivery_mode": "prefixed_single_operator",
            "created_resources": {"main_chat": {"chat_id": "oc_1"}},
            "thread_id_to_chat_id": {},
            "action_status": [{"action_id": "act_001", "status": "success"}],
            "preflight": {},
        }
        result = execute_plan(PLAN, runner=_runner, resume_result=resume_result)
        action_ids = [row["action_id"] for row in result["action_status"]]
        self.assertEqual(action_ids.count("act_001"), 1)
        self.assertIn("msg_1", result["created_resources"])


if __name__ == "__main__":
    unittest.main()
