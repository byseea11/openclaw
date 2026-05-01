from __future__ import annotations

import unittest

from feishu_builder_agent.adapter import adapt_fetch_records


class AdapterTests(unittest.TestCase):
    def test_adapter_fills_chat_id_and_wraps_content(self) -> None:
        case_spec = {
            "case_id": "case-1",
            "task_id": "REQ-1",
            "title": "项目标题",
            "company_type": "企业软件",
            "departments": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
            "main_goal": "推进本周内形成上线口径",
            "difficulty": "medium",
            "seed": 1,
        }
        execution_result = {
            "case_id": "case-1",
            "status": "success",
            "operator_identity": "user",
            "delivery_mode": "prefixed_single_operator",
            "created_resources": {},
            "thread_id_to_chat_id": {"omt_1": "oc_1"},
            "action_status": [],
            "preflight": {},
        }
        fetch_records = [
            {
                "record_id": "fetch-1",
                "domain": "im",
                "kind": "thread_messages_fetch",
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
        ]
        events, report = adapt_fetch_records(case_spec, execution_result, fetch_records)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["message"]["chat_id"], "oc_1")
        self.assertEqual(event["message"]["root_id"], "omt_1")
        self.assertIn('{"text":"这个日期暂时不要对外说死。"}', event["message"]["content"])
        self.assertEqual(report["output_events"], 1)


if __name__ == "__main__":
    unittest.main()
