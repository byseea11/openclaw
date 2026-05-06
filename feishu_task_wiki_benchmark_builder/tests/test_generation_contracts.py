from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.llm import BuilderModelClient, FixtureModelClient, ModelCallResult
from feishu_task_wiki_benchmark_builder.stages.case_context import build_case_context, generate_case_context
from feishu_task_wiki_benchmark_builder.stages.common import generate_default_seed, normalize_seed
from feishu_task_wiki_benchmark_builder.stages.story_plan import build_story_plan


class WeirdNamingCaseContextClient:
    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, object],
    ) -> ModelCallResult:
        return ModelCallResult(
            payload={
                "family_id": "contradiction_update",
                "benchmark_requirement_name": "矛盾更新测试",
                "benchmark_requirement_summary": "test summary",
                "report_display_name": "矛盾更新测试",
                "capability_under_test": "test capability",
                "why_memory_systems_may_fail": "test why",
                "generation_rules": ["rule 1"],
                "required_case_structure": ["structure 1"],
                "probe_strategy": ["probe 1"],
                "expected_good_system_behavior": ["behavior 1"],
                "case_id": "contra_001",
                "task_id": "TASK-123",
                "seed": 999,
                "difficulty": "hard",
                "comparison_target": "wrong_target",
                "organization": "Org",
                "team": "Team",
                "business_goal": "Goal",
                "scenario_summary": "Summary",
                "family_fit_explanation": "Reason",
            },
            backend="fixture",
            model="fixture-test",
            base_url="fixture://local",
            duration_ms=0,
        )


class GenerationContractTests(unittest.TestCase):
    def test_default_seed_generation_is_unique_and_normalized(self) -> None:
        first = generate_default_seed()
        second = generate_default_seed()
        self.assertNotEqual(first, second)
        self.assertGreater(second, first)
        self.assertEqual(normalize_seed(17), 17)

    def test_case_context_contains_required_fields(self) -> None:
        case_context = build_case_context(
            seed=11,
            requested_family_id="contradiction_update",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        self.assertEqual(case_context["family_id"], "contradiction_update")
        self.assertEqual(case_context["benchmark_requirement_name"], "矛盾更新测试")
        self.assertTrue(case_context["benchmark_requirement_summary"])
        self.assertTrue(case_context["report_display_name"])
        self.assertTrue(case_context["generation_rules"])
        self.assertTrue(case_context["required_case_structure"])
        self.assertTrue(case_context["probe_strategy"])
        self.assertIn("这个场景", case_context["family_fit_explanation"])

    def test_case_context_ids_are_code_owned_not_model_named(self) -> None:
        case_context, _ = generate_case_context(
            seed=17,
            requested_family_id="contradiction_update",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=WeirdNamingCaseContextClient(),
        )
        self.assertEqual(case_context["case_id"], "case_0017_contradiction_update")
        self.assertEqual(case_context["task_id"], "FEISHU-217")
        self.assertEqual(case_context["seed"], 17)
        self.assertEqual(case_context["difficulty"], "medium")
        self.assertEqual(case_context["comparison_target"], "default_memory_architectures")

    def test_case_context_without_explicit_seed_does_not_fall_back_to_case_0001(self) -> None:
        case_context = build_case_context(
            seed=None,
            requested_family_id="anti_interference",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        self.assertNotEqual(case_context["seed"], 1)
        self.assertNotEqual(case_context["case_id"], "case_0001_anti_interference")
        self.assertTrue(case_context["case_id"].startswith("case_"))

    def test_story_plan_contains_formal_sections(self) -> None:
        case_context = build_case_context(
            seed=12,
            requested_family_id="evidence_dependency_reasoning",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        story_plan = build_story_plan(case_context=case_context, model_client=FixtureModelClient())
        self.assertIn("task", story_plan)
        self.assertIn("actors", story_plan)
        self.assertIn("task_actor_layout", story_plan)
        self.assertIn("state_changes", story_plan)
        self.assertIn("message_beats", story_plan)
        self.assertIn("planned_probe_queries", story_plan)
        self.assertEqual(story_plan["task"]["role"], "target_task")
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
        dependency_contexts = story_plan["task_actor_layout"]["dependency_context_blocks"]
        self.assertEqual(len(dependency_contexts), 4)
        dependency_roles = {context["dependency_role"] for context in dependency_contexts}
        self.assertIn("verified_anchor", dependency_roles)
        self.assertIn("hearsay_channel", dependency_roles)
        self.assertIn("ambiguous_channel", dependency_roles)
        self.assertIn("downstream_impact", dependency_roles)


if __name__ == "__main__":
    unittest.main()
