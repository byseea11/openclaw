from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.cli import adapt_case, compile_case
from feishu_builder_agent.build_report import build_case_report
from feishu_builder_agent.collector import utc_now_iso
from feishu_builder_agent.io_utils import write_json, write_jsonl


class EndToEndTests(unittest.TestCase):
    def test_compile_and_adapt_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_spec = {
                "case_id": "case_smoke",
                "task_id": "REQ-231",
                "title": "企业级 SSO 上线推进",
                "company_type": "企业级 SaaS",
                "departments": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                "main_goal": "评估并推动五月上旬完成上线",
                "difficulty": "medium",
                "seed": 3,
            }
            case_spec_path = root / "case_spec.json"
            write_json(case_spec_path, case_spec)
            compiled = compile_case(case_spec_path=case_spec_path, dataset_root=root / "dataset")
            self.assertIn(compiled["llm_mode"], {"fallback", "mixed", "live"})
            self.assertIn("case_world", compiled["generation_modes"])
            self.assertIn("conversation_plan", compiled["generation_modes"])
            self.assertIn("message_realizer", compiled["generation_modes"])
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "case_seed.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "case_world.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "conversation_plan.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "utterance_plan.jsonl").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "data" / "realized_messages.jsonl").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "gold" / "expected_events.jsonl").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "checks" / "conversation_complexity_report.json").exists())
            self.assertTrue(compiled["complexity_report"]["passed"])
            self.assertTrue(compiled["dataset_validation_report"]["passed"])
            case_dir = Path(compiled["case_dir"])
            write_json(
                case_dir / "execution_result.json",
                {
                    "case_id": "case_smoke",
                    "status": "success",
                    "operator_identity": "user",
                    "delivery_mode": "prefixed_single_operator",
                    "created_resources": {},
                    "thread_id_to_chat_id": {"omt_1": "oc_1"},
                    "action_status": [],
                    "preflight": {"auth_ok": True},
                },
            )
            write_jsonl(
                case_dir / "lark_fetch_records.jsonl",
                [
                    {
                        "record_id": "fetch-1",
                        "domain": "im",
                        "kind": "thread_messages_fetch",
                        "captured_at": utc_now_iso(),
                        "identity": "user",
                        "command": "lark-cli im +threads-messages-list",
                        "response": {
                            "data": {
                                "thread_id": "omt_1",
                                "messages": [
                                    {
                                        "message_id": "om_1",
                                        "content": "这个日期暂时不要对外说死。",
                                        "msg_type": "text",
                                        "create_time": "2026-04-26 13:07",
                                        "deleted": False,
                                        "sender": {"id": "ou_1", "sender_type": "user"},
                                    }
                                ],
                            }
                        },
                    }
                ],
            )
            adapted = adapt_case(case_dir_path=case_dir)
            self.assertEqual(adapted["adapter_report"]["output_events"], 1)
            self.assertTrue((case_dir / "openclaw_message_ingress.jsonl").exists())
            self.assertTrue((case_dir / "build_report.json").exists())


if __name__ == "__main__":
    unittest.main()
