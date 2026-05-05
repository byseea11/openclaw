from __future__ import annotations

import unittest

from feishu_builder_agent.prompt_templates import (
    build_case_world_prompts,
    build_character_prompts,
    build_conversation_plan_prompts,
    build_spec_prompts,
)


class PromptTemplateTests(unittest.TestCase):
    def test_spec_prompt_includes_department_pool_and_array_rule(self) -> None:
        system_prompt, user_prompt = build_spec_prompts(
            scenario_profile="enterprise_release_coordination",
            difficulty="hard",
            seed=231,
            user_hint="测试安全和上线窗口",
        )
        self.assertIn("department_hints must be a JSON array", system_prompt)
        self.assertIn("allowed_departments", user_prompt)
        self.assertIn("项目管理办公室", user_prompt)
        self.assertIn("target_department_count: 10", user_prompt)

    def test_case_world_prompt_includes_hard_targets_and_chinese_department_rule(self) -> None:
        system_prompt, user_prompt = build_case_world_prompts(
            seed={
                "case_id": "case_feishu_231_example",
                "task_id": "FEISHU-231",
                "scenario_profile": "enterprise_release_coordination",
                "difficulty": "hard",
                "seed": 231,
                "department_hints": ["产品", "研发", "安全"],
                "title_hint": "发布窗口协调",
                "main_goal_hint": "统一口径",
                "company_type_hint": "",
                "domain": "enterprise_product_launch",
                "complexity_profile": {"session_count_target": 5, "message_count_target": 28},
            },
            fallback_world={
                "departments": ["产品", "研发", "安全"],
                "selected_topics": [],
            },
        )
        self.assertIn("departments must be a JSON array of unique Simplified Chinese department names", system_prompt)
        self.assertIn("Each selected_topics item must contain topic_key, topic_title, desired_event_types, state_transitions, and turn_templates", system_prompt)
        self.assertIn("target_department_count: 10", user_prompt)
        self.assertIn("target_topic_count: 5", user_prompt)
        self.assertIn("不允许输出 SRE、PMO", user_prompt)

    def test_character_prompt_includes_character_range(self) -> None:
        _system_prompt, user_prompt = build_character_prompts(
            world={
                "difficulty": "hard",
                "departments": ["产品", "研发", "安全", "运维"],
            }
        )
        self.assertIn("character_count_min: 10", user_prompt)
        self.assertIn("character_count_max: 12", user_prompt)
        self.assertIn("selected_departments: 产品、研发、安全、运维", user_prompt)

    def test_plan_prompt_includes_session_message_targets(self) -> None:
        _system_prompt, user_prompt = build_conversation_plan_prompts(
            world={
                "difficulty": "hard",
                "departments": ["产品", "研发", "安全"],
            },
            validated_characters={
                "characters": [
                    {"person_id": "product_manager_01", "department": "产品"},
                    {"person_id": "engineering_lead_02", "department": "研发"},
                ]
            },
        )
        self.assertIn("required_session_count_min: 5", user_prompt)
        self.assertIn("required_topic_count_min: 5", user_prompt)
        self.assertIn("required_turn_count_min: 28", user_prompt)
        self.assertIn("required_cross_source_revision_count_min: 2", user_prompt)


if __name__ == "__main__":
    unittest.main()
