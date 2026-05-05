from __future__ import annotations

import unittest

from feishu_builder_agent.spec_generator import generate_case_spec_with_mode


class SpecGeneratorTests(unittest.TestCase):
    class _StringDepartmentsLLM:
        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
            return {
                "case_id": "case_001",
                "task_id": "task_001",
                "title": "",
                "company_type": "",
                "department_hints": "涉及研发部、测试部、运维部、产品部",
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "企业级发布协调场景，需跨部门协作完成版本发布",
                "main_goal_hint": "确保发布流程顺畅，各部门职责明确，风险可控",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 231,
            }

    class _EnglishHintsLLM:
        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
            return {
                "case_id": "",
                "task_id": "",
                "title": "",
                "company_type": "",
                "department_hints": ["产品", "研发", "安全"],
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "English title",
                "main_goal_hint": "English goal",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 231,
            }

    def test_fallback_generates_minimal_case_spec(self) -> None:
        payload, mode = generate_case_spec_with_mode(
            scenario_profile="enterprise_release_coordination",
            difficulty="medium",
            seed=231,
            user_hint="重点关注安全评审、研发依赖和客户同步压力",
            llm_client=None,
        )
        self.assertEqual(mode, "fallback")
        self.assertEqual(payload["difficulty"], "medium")
        self.assertEqual(payload["seed"], 231)
        self.assertEqual(payload["title"], "")
        self.assertEqual(payload["company_type"], "")
        self.assertEqual(payload["main_goal"], "")
        self.assertTrue(payload["department_hints"])
        self.assertTrue(payload["title_hint"])
        self.assertTrue(payload["main_goal_hint"])

    def test_string_department_hints_are_normalized_before_validation(self) -> None:
        payload, mode = generate_case_spec_with_mode(
            scenario_profile="enterprise_release_coordination",
            difficulty="medium",
            seed=231,
            user_hint="",
            llm_client=self._StringDepartmentsLLM(),
        )
        self.assertEqual(mode, "live")
        self.assertEqual(payload["task_id"], "FEISHU-001")
        self.assertEqual(payload["case_id"], "case_feishu_001_example")
        self.assertEqual(payload["department_hints"], ["产品", "研发", "运维", "测试"])

    def test_invalid_hint_language_falls_back_per_field_not_whole_spec(self) -> None:
        payload, mode = generate_case_spec_with_mode(
            scenario_profile="enterprise_release_coordination",
            difficulty="medium",
            seed=231,
            user_hint="",
            llm_client=self._EnglishHintsLLM(),
        )
        self.assertEqual(mode, "live")
        self.assertEqual(payload["case_id"], "case_feishu_231_example")
        self.assertEqual(payload["task_id"], "FEISHU-231")
        self.assertTrue(payload["title_hint"])
        self.assertTrue(payload["main_goal_hint"])


if __name__ == "__main__":
    unittest.main()
