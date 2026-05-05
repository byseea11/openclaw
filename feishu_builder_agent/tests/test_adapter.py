from __future__ import annotations

import unittest

from feishu_builder_agent.adapter import adapt_fetch_records


class AdapterTests(unittest.TestCase):
    def test_adapter_fills_chat_id_and_maps_to_simulated_speaker(self) -> None:
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
        collected_messages = [
            {
                "turn_id": "step_1",
                "sequence_no": 1,
                "session_id": "session_1",
                "source_type": "thread",
                "source_ref": "launch_window_thread",
                "chat_ref": "main_chat",
                "speaker_ref": "ops_01",
                "topic_key": "release_date",
                "turn_purpose": "补充约束",
                "supports_event_types": ["constraint_event"],
                "references_previous_turns": [],
                "state_transition": "引入运维约束",
                "semantic_payload": "这个日期暂时不要对外说死。",
                "root_turn_id": "turn_1",
                "content_text": "【运维/周宇】这个日期暂时不要对外说死。",
                "message_id": "om_1",
                "collect_source": "fetch_records",
                "actual_sender": {"open_id": "ou_1", "name": "真实发送者", "sender_type": "user"},
                "simulated_speaker": {
                    "speaker_ref": "ops_01",
                    "open_id": "ou_sim_ops_01",
                    "name": "周宇",
                    "department": "运维",
                    "role": "SRE 负责人",
                    "stance": "明确反对过早对外承诺日期。",
                },
                "normalized_actor_id": "ops_01",
                "speaker_resolution_mode": "command_plan+prefix",
                "prefix_speaker_hint": {"speaker_ref": "ops_01", "name": "周宇", "department": "运维"},
            }
        ]
        events, report = adapt_fetch_records(case_spec, execution_result, fetch_records, collected_messages)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["message"]["chat_id"], "oc_1")
        self.assertEqual(event["message"]["root_id"], "omt_1")
        self.assertIn('{"text":"这个日期暂时不要对外说死。"}', event["message"]["content"])
        self.assertEqual(event["sender"]["sender_id"]["open_id"], "ou_sim_ops_01")
        self.assertNotIn("actual_sender", event)
        self.assertNotIn("simulated_speaker", event)
        self.assertNotIn("normalized_actor_id", event)
        self.assertNotIn("source_message", event)
        self.assertEqual(report["simulated_sender_applied"], 1)
        self.assertEqual(report["output_events"], 1)

    def test_adapter_can_fill_chat_id_from_created_resources_or_fetch_command(self) -> None:
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
            "created_resources": {
                "msg_turn_001": {"message_id": "om_1", "chat_id": "oc_1"},
            },
            "thread_id_to_chat_id": {},
            "action_status": [],
            "preflight": {},
        }
        fetch_records = [
            {
                "record_id": "fetch-1",
                "domain": "im",
                "kind": "chat_messages_fetch",
                "command": "lark-cli im +chat-messages-list --chat-id oc_1 --sort asc --page-size 50 --format json --as user",
                "response": {
                    "data": {
                        "messages": [
                            {
                                "message_id": "om_1",
                                "content": "主群口径先不要对外承诺。",
                                "msg_type": "text",
                                "create_time": "2026-04-26 13:07",
                                "deleted": False,
                                "sender": {"id": "ou_1", "sender_type": "user"},
                            },
                            {
                                "message_id": "om_2",
                                "content": "这个消息没有 created_resources，但能从命令参数补 chat_id。",
                                "msg_type": "text",
                                "create_time": "2026-04-26 13:08",
                                "deleted": False,
                                "sender": {"id": "ou_1", "sender_type": "user"},
                            },
                        ],
                    }
                },
            }
        ]
        events, report = adapt_fetch_records(case_spec, execution_result, fetch_records)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["message"]["chat_id"], "oc_1")
        self.assertEqual(events[1]["message"]["chat_id"], "oc_1")
        self.assertEqual(report["output_events"], 2)
        self.assertEqual(report["skipped_messages"], 0)
        self.assertEqual(report["simulated_sender_applied"], 0)
        self.assertTrue(any(item["source"] == "execution_result.created_resources" for item in report["filled_fields"]))
        self.assertTrue(any(item["source"] == "fetch_record.command" for item in report["filled_fields"]))


if __name__ == "__main__":
    unittest.main()
