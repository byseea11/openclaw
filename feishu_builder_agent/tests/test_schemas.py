from __future__ import annotations

import unittest

from feishu_builder_agent.schemas import (
    ValidationError,
    validate_case_spec,
    validate_characters,
    validate_execution_plan,
    validate_target_state,
)


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
                    "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                    "main_goal": "推动五月初上线",
                    "difficulty": "medium",
                    "seed": 1,
                }
            )

    def test_case_spec_rejects_unknown_difficulty(self) -> None:
        with self.assertRaises(ValidationError):
            validate_case_spec(
                {
                    "case_id": "case_feishu_1_example",
                    "task_id": "FEISHU-1",
                    "title": "",
                    "company_type": "",
                    "department_hints": ["产品", "研发"],
                    "title_hint": "测试难度校验",
                    "main_goal_hint": "验证未知难度会直接报错",
                    "main_goal": "",
                    "difficulty": "unknown",
                    "seed": 1,
                }
            )

    def test_target_state_requires_current_targets(self) -> None:
        payload = validate_target_state(
            {
                "case_id": "case-1",
                "expected_topics": ["release_date"],
                "expected_block_targets": [
                    {
                        "topic_key": "release_date",
                        "topic_title": "发布时间口径",
                        "slots": ["conclusion", "time"],
                    }
                ],
                "expected_current_state_targets": [
                    {
                        "topic_key": "release_date",
                        "slot": "time",
                        "claim_hint": "内部目标先同步更新为 5 月 10 日。",
                    }
                ],
                "required_event_coverage": ["conclusion_event", "time_event"],
                "required_state_transitions": ["内部目标日期从 5 月 5 日切换到 5 月 10 日。"],
                "required_cross_source_revisions": ["release_date"],
            }
        )
        self.assertEqual(payload["expected_current_state_targets"][0]["slot"], "time")

    def test_characters_require_rule_based_simulated_open_id(self) -> None:
        with self.assertRaises(ValidationError):
            validate_characters(
                {
                    "case_id": "case-1",
                    "characters": [
                        {
                            "person_id": "security_01",
                            "simulated_open_id": "simulated_security_01",
                            "name": "林晨",
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
                        {
                            "person_id": "eng_01",
                            "name": "赵敏",
                            "department": "研发",
                            "role": "研发负责人",
                            "responsibility": "负责核心依赖评估。",
                            "communication_style": "直接、具体。",
                            "conflict_bias": "会指出实现风险。",
                            "stance": "倾向于先锁依赖再承诺日期。",
                            "risk_preference": "低风险偏好",
                            "information_access_level": "掌握本职能关键事实",
                            "default_channels": ["main_chat"],
                        },
                        {
                            "person_id": "ops_01",
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
                            "person_id": "pm_01",
                            "name": "王源",
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
                    ],
                }
            )

if __name__ == "__main__":
    unittest.main()
