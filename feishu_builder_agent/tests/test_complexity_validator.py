from __future__ import annotations

import unittest

from feishu_builder_agent.complexity_validator import build_complexity_report
from feishu_builder_agent.spec_generator import build_complexity_profile


class ComplexityValidatorTests(unittest.TestCase):
    def test_supersession_keywords_in_state_transition_and_payload_are_counted(self) -> None:
        case_seed = {
            "case_id": "case_feishu_231_example",
            "task_id": "FEISHU-231",
            "domain": "enterprise_product_launch",
            "company_type_hint": "",
            "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功", "项目管理办公室", "合规", "风控", "测试"],
            "scenario_profile": "enterprise_release_coordination",
            "title_hint": "测试 hard complexity",
            "main_goal_hint": "测试 supersession 计数",
            "difficulty": "hard",
            "seed": 231,
            "complexity_profile": build_complexity_profile("hard"),
        }
        conversation_plan = {
            "case_id": "case_feishu_231_example",
            "task_id": "FEISHU-231",
            "topic_registry": [
                {
                    "topic_key": "release_window",
                    "topic_title": "发布时间口径",
                    "desired_event_types": ["conclusion_event"],
                    "state_transitions": ["口径修正。"],
                },
                {
                    "topic_key": "readiness_blockers",
                    "topic_title": "上线阻塞项",
                    "desired_event_types": ["constraint_event"],
                    "state_transitions": ["阻塞项暴露。"],
                },
                {
                    "topic_key": "external_messaging",
                    "topic_title": "客户同步口径",
                    "desired_event_types": ["scope_event"],
                    "state_transitions": ["客户口径收紧。"],
                }
            ],
            "sessions": [
                {
                    "session_id": "session_main_chat",
                    "source_type": "chat",
                    "source_ref": "main_chat",
                    "chat_ref": "main_chat",
                    "title": "主群协调",
                    "topic_keys": ["release_window", "readiness_blockers", "external_messaging"],
                    "planned_turn_count": 4,
                    "root_turn_id": None,
                },
                {
                    "session_id": "session_launch_window_thread",
                    "source_type": "thread",
                    "source_ref": "launch_window_thread",
                    "chat_ref": "main_chat",
                    "title": "线程讨论",
                    "topic_keys": ["release_window"],
                    "planned_turn_count": 1,
                    "root_turn_id": "turn_001",
                },
                {
                    "session_id": "session_customer_sync_chat",
                    "source_type": "chat",
                    "source_ref": "customer_sync_chat",
                    "chat_ref": "customer_sync_chat",
                    "title": "客户同步群",
                    "topic_keys": ["external_messaging"],
                    "planned_turn_count": 1,
                    "root_turn_id": None,
                }
            ],
            "turns": [
                {
                    "turn_id": "turn_001",
                    "sequence_no": 1,
                    "session_id": "session_main_chat",
                    "speaker_ref": "product_01",
                    "topic_key": "release_window",
                    "turn_purpose": "提出初始口径",
                    "supports_event_types": ["conclusion_event"],
                    "references_previous_turns": [],
                    "state_transition": "形成旧窗口。",
                    "semantic_payload": "先按五月上旬推进。",
                },
                {
                    "turn_id": "turn_002",
                    "sequence_no": 2,
                    "session_id": "session_main_chat",
                    "speaker_ref": "product_01",
                    "topic_key": "release_window",
                    "turn_purpose": "第一次 supersession",
                    "supports_event_types": ["conclusion_event"],
                    "references_previous_turns": ["turn_001"],
                    "state_transition": "发布时间口径从旧窗口更新为新窗口。",
                    "semantic_payload": "原来的内部目标窗口更新为条件式窗口，当前暂不作为客户承诺。",
                },
                {
                    "turn_id": "turn_003",
                    "sequence_no": 3,
                    "session_id": "session_main_chat",
                    "speaker_ref": "product_01",
                    "topic_key": "release_window",
                    "turn_purpose": "第二次 supersession",
                    "supports_event_types": ["conclusion_event"],
                    "references_previous_turns": ["turn_002"],
                    "state_transition": "发布时间口径修正为更保守窗口。",
                    "semantic_payload": "客户同步口径从明确日期改为条件式窗口，只能在评审通过后同步。",
                },
                {
                    "turn_id": "turn_004",
                    "sequence_no": 4,
                    "session_id": "session_main_chat",
                    "speaker_ref": "product_01",
                    "topic_key": "release_window",
                    "turn_purpose": "第三次 supersession",
                    "supports_event_types": ["conclusion_event"],
                    "references_previous_turns": ["turn_003"],
                    "state_transition": "发布时间口径收紧为条件式窗口。",
                    "semantic_payload": "管理层同步口径更新为先讲条件再讲时间。",
                },
                *[
                    {
                        "turn_id": f"turn_{index:03d}",
                        "sequence_no": index,
                        "session_id": "session_launch_window_thread" if index % 3 == 0 else ("session_customer_sync_chat" if index % 3 == 1 else "session_main_chat"),
                        "speaker_ref": "product_01",
                        "topic_key": "readiness_blockers" if index % 2 == 0 else "external_messaging",
                        "turn_purpose": "补充复杂度验证样本",
                        "supports_event_types": ["status_event"],
                        "references_previous_turns": [f"turn_{index - 1:03d}"] if index > 5 else [],
                        "state_transition": "补充状态推进。",
                        "semantic_payload": "继续补充一个用于复杂度统计的普通 turn。",
                    }
                    for index in range(5, 19)
                ],
            ],
        }
        collected_messages = [
            {
                "turn_id": row["turn_id"],
                "sequence_no": row["sequence_no"],
                "session_id": row["session_id"],
                "source_type": "chat",
                "source_ref": "main_chat",
                "chat_ref": "main_chat",
                "speaker_ref": "product_01",
                "topic_key": row["topic_key"],
                "turn_purpose": row["turn_purpose"],
                "supports_event_types": row["supports_event_types"],
                "references_previous_turns": row["references_previous_turns"],
                "state_transition": row["state_transition"],
                "semantic_payload": row["semantic_payload"],
                "root_turn_id": None,
                "content_text": f"【产品/林晨】{row['semantic_payload']}",
                "message_id": f"om_{row['turn_id']}",
                "collect_source": "test",
                "actual_sender": {"open_id": "ou_1", "name": "tester", "sender_type": "user"},
                "simulated_speaker": {
                    "speaker_ref": "product_01",
                    "open_id": "ou_sim_product_01",
                    "name": "林晨",
                    "department": "产品",
                    "role": "产品经理",
                    "stance": "保守推进",
                },
                "normalized_actor_id": "product_01",
                "speaker_resolution_mode": "command_plan_only",
                "prefix_speaker_hint": {"speaker_ref": "product_01", "name": "林晨", "department": "产品"},
            }
            for row in conversation_plan["turns"]
        ]
        report = build_complexity_report(case_seed, conversation_plan, collected_messages)
        self.assertGreaterEqual(report["metrics"]["supersession_count"], 3)


if __name__ == "__main__":
    unittest.main()
