from __future__ import annotations

import unittest

from feishu_builder_agent.collected_message_builder import build_collected_messages


CHARACTERS = {
    "case_id": "case_feishu_1_v3",
    "characters": [
        {
            "person_id": "engineering_owner_1",
            "actor_slot_id": "engineering_owner_1",
            "simulated_open_id": "ou_sim_engineering_owner_1",
            "name": "赵敏",
            "department": "研发",
            "role": "研发负责人",
            "task_ids": ["FEISHU-1"],
            "default_channels": ["main_chat"],
            "profile": "研发负责人，提供任务依赖和阻塞信息。",
        }
    ],
}

COMMAND_PLAN = [
    {
        "case_id": "case_feishu_1_v3",
        "step_id": "step_001",
        "sequence_no": 1,
        "action_type": "send_message",
        "session_id": "session_main_chat",
        "source_type": "chat",
        "source_ref": "chat:main_chat",
        "chat_ref": "main_chat",
        "topic_key": "static_memory_stale_state",
        "turn_id": "turn_001",
        "turn_purpose": "测试消息落地",
        "speaker_role": "研发负责人",
        "speaker_ref": "engineering_owner_1",
        "depends_on_step_ids": [],
        "benchmark_role": "target_fact_turn",
        "memory_failure_mode": "static_memory_stale_state",
        "memory_trap": "trap_001",
        "expected_openclaw_memory_risk": "可能把旧状态当当前状态。",
        "task_wiki_expected_handling": "应区分历史与当前状态。",
        "state_field_hints": ["owner"],
        "semantic_payload": "当前 owner 先这样记。",
        "planned_message_text": "当前 owner 先这样记。",
        "output_ref": "msg_turn_001",
        "params": {
            "chat_ref": "main_chat",
            "sender_ref": "engineering_owner_1",
            "content_text": "【研发/赵敏】当前 owner 先这样记。",
        },
        "lark_cli_command": "",
    }
]

EXECUTION_PLAN = {
    "case_id": "case_feishu_1_v3",
    "operator_identity": "user",
    "delivery_mode": "prefixed_single_operator",
    "actions": [
        {
            "action_id": "step_001",
            "action_type": "send_message",
            "params": {
                "chat_ref": "main_chat",
                "sender_ref": "engineering_owner_1",
                "content_text": "【研发/赵敏】当前 owner 先这样记。",
            },
            "output_ref": "msg_turn_001",
        }
    ],
}

EXECUTION_RESULT = {
    "case_id": "case_feishu_1_v3",
    "status": "success",
    "operator_identity": "user",
    "delivery_mode": "prefixed_single_operator",
    "created_resources": {"msg_turn_001": {"message_id": "om_1", "chat_id": "oc_1"}},
    "thread_id_to_chat_id": {},
    "action_status": [],
    "preflight": {},
}

FETCH_RECORDS = [
    {
        "response": {
            "data": {
                "messages": [
                    {
                        "message_id": "om_1",
                        "content": "【研发/赵敏】当前 owner 先这样记。",
                        "sender": {"id": "ou_real_user", "name": "真实发送者", "sender_type": "user"},
                    }
                ]
            }
        }
    }
]


class CollectedMessageBuilderTests(unittest.TestCase):
    def test_builder_keeps_failure_metadata(self) -> None:
        rows = build_collected_messages(CHARACTERS, COMMAND_PLAN, EXECUTION_PLAN, EXECUTION_RESULT, FETCH_RECORDS)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["benchmark_role"], "target_fact_turn")
        self.assertEqual(row["memory_failure_mode"], "static_memory_stale_state")
        self.assertEqual(row["memory_trap"], "trap_001")
        self.assertEqual(row["actual_sender"]["open_id"], "ou_real_user")


if __name__ == "__main__":
    unittest.main()
