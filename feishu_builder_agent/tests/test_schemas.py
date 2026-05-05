from __future__ import annotations

import unittest

from feishu_builder_agent.schemas import (
    ValidationError,
    validate_case_spec,
    validate_case_profile_catalog,
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
                    "departments": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                    "main_goal": "推动五月初上线",
                    "difficulty": "medium",
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

    def test_case_profile_catalog_accepts_current_shape(self) -> None:
        payload = validate_case_profile_catalog(
            {
                "scenario_profiles": {
                    "enterprise_release_coordination": {
                        "domain": "enterprise_product_launch",
                        "company_type_options": ["企业级 SaaS"],
                        "department_pool": ["产品", "研发", "测试", "运维"],
                        "must_include_departments": ["产品", "研发"],
                        "department_count_by_difficulty": {"easy": 5, "medium": 7, "hard": 8},
                        "initiative_labels": ["发布窗口"],
                        "delivery_motions": ["协调推进"],
                        "target_window_options": ["五月上旬"],
                        "title_templates": ["{task_id} 发布窗口协调推进"],
                        "main_goal_templates": ["围绕 {task_id} 推动五月上旬上线决策收敛"],
                        "stakeholder_templates": {"产品": "产品团队需要统一口径。"},
                        "conflict_axis_templates": ["内部目标日期是否可以被当成对外承诺。"],
                        "hidden_constraint_templates": ["回滚演练未完成前，运维不愿意锁定最终上线窗口。"],
                        "reversal_point_templates": ["原本乐观的目标日期会在后续讨论中被修正。"],
                        "topic_templates": [],
                        "session_layout_templates": [],
                        "character_role_templates": {},
                        "default_complexity_profile_by_difficulty": {
                            "easy": {
                                "session_count_target": 3,
                                "source_session_count_target": 3,
                                "message_count_target": 18,
                                "topic_count_target": 3,
                                "thread_reply_depth_target": 3,
                                "state_transition_target": 4,
                                "supersession_target": 1,
                                "cross_source_revision_target": 1,
                                "event_family_target": 5,
                            },
                            "medium": {
                                "session_count_target": 3,
                                "source_session_count_target": 3,
                                "message_count_target": 20,
                                "topic_count_target": 4,
                                "thread_reply_depth_target": 5,
                                "state_transition_target": 8,
                                "supersession_target": 1,
                                "cross_source_revision_target": 2,
                                "event_family_target": 6,
                            },
                            "hard": {
                                "session_count_target": 4,
                                "source_session_count_target": 4,
                                "message_count_target": 24,
                                "topic_count_target": 5,
                                "thread_reply_depth_target": 6,
                                "state_transition_target": 10,
                                "supersession_target": 2,
                                "cross_source_revision_target": 2,
                                "event_family_target": 7,
                            },
                        },
                    }
                }
            }
        )
        self.assertIn("enterprise_release_coordination", payload["scenario_profiles"])


if __name__ == "__main__":
    unittest.main()
