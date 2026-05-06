from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.stages.capability_brief import build_memory_capability_brief
from feishu_task_wiki_benchmark_builder.stages.case_spec import build_case_spec
from feishu_task_wiki_benchmark_builder.stages.case_world import build_case_world
from feishu_task_wiki_benchmark_builder.stages.story_plan import build_story_plan


class GenerationContractTests(unittest.TestCase):
    def test_memory_capability_brief_contains_required_fields(self) -> None:
        brief = build_memory_capability_brief(family_id="contradiction_update")
        self.assertEqual(brief["family_id"], "contradiction_update")
        self.assertEqual(brief["benchmark_requirement_name"], "矛盾更新测试")
        self.assertTrue(brief["benchmark_requirement_summary"])
        self.assertTrue(brief["report_display_name"])
        self.assertTrue(brief["generation_rules"])
        self.assertTrue(brief["required_case_structure"])
        self.assertTrue(brief["probe_strategy"])

    def test_case_world_explains_how_family_lands_in_business_context(self) -> None:
        case_spec = build_case_spec(
            family_id="anti_interference",
            difficulty="medium",
            seed=11,
            comparison_target="default_memory_architectures",
        )
        brief = build_memory_capability_brief(family_id="anti_interference")
        case_world = build_case_world(case_spec=case_spec, capability_brief=brief)
        self.assertIn("这个场景", case_world["family_fit_explanation"])

    def test_story_plan_contains_formal_sections(self) -> None:
        case_spec = build_case_spec(
            family_id="evidence_dependency_reasoning",
            difficulty="medium",
            seed=12,
            comparison_target="default_memory_architectures",
        )
        brief = build_memory_capability_brief(family_id="evidence_dependency_reasoning")
        case_world = build_case_world(case_spec=case_spec, capability_brief=brief)
        story_plan = build_story_plan(case_spec=case_spec, case_world=case_world, capability_brief=brief)
        self.assertIn("tasks", story_plan)
        self.assertIn("actors", story_plan)
        self.assertIn("task_actor_layout", story_plan)
        self.assertIn("state_changes", story_plan)
        self.assertIn("message_beats", story_plan)
        self.assertIn("planned_probe_queries", story_plan)
        self.assertTrue(story_plan["planned_probe_queries"][0]["query"])
        self.assertNotEqual(
            story_plan["planned_probe_queries"][0]["query"],
            story_plan["planned_probe_queries"][0]["expected_good_behavior"],
        )
        probe = story_plan["planned_probe_queries"][0]["query"]
        self.assertIn("依据来自谁", probe)
        self.assertIn("影响", probe)
        message_texts = [beat["message_intent"] for beat in story_plan["message_beats"]]
        self.assertTrue(any("确认过" in text for text in message_texts))
        self.assertTrue(any("我听别人说" in text for text in message_texts))
        task_roles = [task["role"] for task in story_plan["tasks"]]
        self.assertIn("upstream_task", task_roles)
        self.assertIn("downstream_task", task_roles)


if __name__ == "__main__":
    unittest.main()
