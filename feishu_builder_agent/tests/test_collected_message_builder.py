from __future__ import annotations

import unittest

from feishu_builder_agent.collected_message_builder import build_collected_messages


CHARACTERS = {
    "case_id": "case-1",
    "characters": [
        {
            "person_id": "eng_01",
            "simulated_open_id": "ou_sim_eng_01",
            "name": "赵敏",
            "department": "研发",
            "role": "研发负责人",
            "responsibility": "负责核心依赖评估。",
            "communication_style": "直接、具体。",
            "conflict_bias": "会指出实现风险。",
            "stance": "倾向于先锁依赖再承诺日期。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握本职能关键事实",
            "default_channels": ["main_chat", "launch_window_thread"],
        },
        {
            "person_id": "pm_01",
            "simulated_open_id": "ou_sim_pm_01",
            "name": "林晨",
            "department": "产品",
            "role": "产品经理",
            "responsibility": "负责统一口径。",
            "communication_style": "谨慎、强调对齐。",
            "conflict_bias": "会反对过早承诺。",
            "stance": "倾向于先统一内部口径。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握跨部门上下游信息",
            "default_channels": ["main_chat"],
        },
        {
            "person_id": "ops_01",
            "simulated_open_id": "ou_sim_ops_01",
            "name": "周宇",
            "department": "运维",
            "role": "运维负责人",
            "responsibility": "负责上线窗口。",
            "communication_style": "偏保守。",
            "conflict_bias": "会指出窗口风险。",
            "stance": "倾向于先完成回滚准备。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握本职能关键事实",
            "default_channels": ["main_chat"],
        },
        {
            "person_id": "qa_01",
            "simulated_open_id": "ou_sim_qa_01",
            "name": "陈雪",
            "department": "测试",
            "role": "测试负责人",
            "responsibility": "负责验证风险。",
            "communication_style": "系统化。",
            "conflict_bias": "会阻止质量不确定的上线。",
            "stance": "倾向于先收敛高优问题。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握本职能关键事实",
            "default_channels": ["main_chat"],
        },
        {
            "person_id": "sales_01",
            "simulated_open_id": "ou_sim_sales_01",
            "name": "罗天",
            "department": "销售",
            "role": "客户经理",
            "responsibility": "推动客户口径。",
            "communication_style": "结果导向。",
            "conflict_bias": "会推动更激进承诺。",
            "stance": "倾向于尽快形成外部同步口径。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握客户侧压力信息",
            "default_channels": ["customer_sync_chat"],
        },
        {
            "person_id": "security_01",
            "simulated_open_id": "ou_sim_security_01",
            "name": "高骏",
            "department": "安全",
            "role": "安全评审",
            "responsibility": "负责高风险能力评审。",
            "communication_style": "直接、规则优先。",
            "conflict_bias": "会拒绝未经评审的风险。",
            "stance": "倾向于在评审前收紧承诺。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握敏感能力风险信息",
            "default_channels": ["main_chat"],
        },
    ],
}

COMMAND_PLAN = [
    {
        "case_id": "case-1",
        "step_id": "step_001",
        "sequence_no": 1,
        "action_type": "send_message",
        "session_id": "session_main",
        "source_type": "chat",
        "source_ref": "chat_main",
        "channel_scope": "chat:main_chat",
        "chat_ref": "main_chat",
        "topic_key": "launch_window",
        "turn_purpose": "先给出研发侧阻塞判断",
        "speaker_role": "研发负责人",
        "speaker_ref": "eng_01",
        "supports_event_types": ["constraint_event"],
        "depends_on_step_ids": [],
        "gold_intent_refs": ["launch_window:constraint"],
        "expected_effect": "让主群看到研发阻塞",
        "state_transition": "把重点转到迁移窗口",
        "semantic_payload": "真正的 blocker 是数据迁移窗口未锁定",
        "root_turn_id": None,
        "root_message_ref": None,
        "output_ref": "msg_turn_001",
        "params": {
            "chat_ref": "main_chat",
            "sender_ref": "eng_01",
            "content_text": "【研发/赵敏】真正的 blocker 是数据迁移窗口未锁定。",
        },
        "lark_cli_command": 'lark-cli im +messages-send --chat-id $main_chat --text "【研发/赵敏】真正的 blocker 是数据迁移窗口未锁定。" --as user',
    }
]

EXECUTION_PLAN = {
    "case_id": "case-1",
    "operator_identity": "user",
    "delivery_mode": "prefixed_single_operator",
    "actions": [
        {
            "action_id": "step_001",
            "action_type": "send_message",
            "params": {
                "chat_ref": "main_chat",
                "sender_ref": "eng_01",
                "content_text": "【研发/赵敏】真正的 blocker 是数据迁移窗口未锁定。",
            },
            "output_ref": "msg_turn_001",
        }
    ],
}

EXECUTION_RESULT = {
    "case_id": "case-1",
    "status": "success",
    "operator_identity": "user",
    "delivery_mode": "prefixed_single_operator",
    "created_resources": {
        "msg_turn_001": {
            "message_id": "om_1",
            "chat_id": "oc_1",
        }
    },
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
                        "content": "【研发/赵敏】真正的 blocker 是数据迁移窗口未锁定。",
                        "sender": {
                            "id": "ou_real_user",
                            "name": "许祝愿",
                            "sender_type": "user",
                        },
                    }
                ]
            }
        }
    }
]


class CollectedMessageBuilderTests(unittest.TestCase):
    def test_build_collected_messages_keeps_actual_sender_and_simulated_speaker(self) -> None:
        rows = build_collected_messages(CHARACTERS, COMMAND_PLAN, EXECUTION_PLAN, EXECUTION_RESULT, FETCH_RECORDS)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["actual_sender"]["open_id"], "ou_real_user")
        self.assertEqual(row["actual_sender"]["name"], "许祝愿")
        self.assertEqual(row["simulated_speaker"]["speaker_ref"], "eng_01")
        self.assertEqual(row["simulated_speaker"]["open_id"], "ou_sim_eng_01")
        self.assertEqual(row["simulated_speaker"]["name"], "赵敏")
        self.assertEqual(row["normalized_actor_id"], "eng_01")
        self.assertEqual(row["speaker_resolution_mode"], "command_plan+prefix")
        self.assertEqual(row["prefix_speaker_hint"]["speaker_ref"], "eng_01")


if __name__ == "__main__":
    unittest.main()
