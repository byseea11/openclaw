from __future__ import annotations

import unittest

from feishu_builder_agent.schemas import ValidationError, validate_case_spec, validate_execution_plan


class SchemaTests(unittest.TestCase):
    def test_sender_ref_must_exist_in_characters(self) -> None:
        plan = {
            "case_id": "case-1",
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
                    "params": {"chat_ref": "main_chat", "sender_ref": "unknown", "content_text": "收到，先按这个方向推进。"},
                    "output_ref": "msg_1",
                },
            ],
        }
        with self.assertRaises(ValidationError):
            validate_execution_plan(plan, allowed_sender_refs={"pm_alice"})

    def test_case_spec_requires_chinese_natural_language_fields(self) -> None:
        with self.assertRaises(ValidationError):
            validate_case_spec(
                {
                    "case_id": "case-1",
                    "task_id": "REQ-1",
                    "title": "Enterprise rollout",
                    "company_type": "B2B SaaS",
                    "departments": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                    "main_goal": "推动五月初上线",
                    "difficulty": "medium",
                    "seed": 1,
                }
            )


if __name__ == "__main__":
    unittest.main()
