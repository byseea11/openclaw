from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.prompt import build_conversation_plan_system_prompt
from feishu_task_wiki_benchmark_builder.prompt_loader import (
    build_stage_system_prompt,
    list_stage_prompt_sources,
)


class PromptLoaderTests(unittest.TestCase):
    def test_conversation_plan_prompt_assembles_current_family_sources(self) -> None:
        prompt = build_conversation_plan_system_prompt(
            family_id="private_info_in_official_file",
            difficulty="hard",
        )
        self.assertIn("workflow.md", prompt)
        self.assertIn("conversation-plan.md", prompt)
        self.assertIn("private-info-official-file-context.md", prompt)
        self.assertIn("official_file_ref", prompt)
        self.assertIn("private_info_ref", prompt)
        self.assertIn("不允许模板刷屏", prompt)
        self.assertIn("\"difficulty\": \"hard\"", prompt)
        self.assertIn("\"min_private_info_items\": 4", prompt)
        self.assertNotIn("case-context.md", prompt)
        self.assertNotIn("story-plan.md", prompt)

    def test_semantic_gold_prompt_uses_observed_evidence_sources(self) -> None:
        prompt = build_stage_system_prompt(
            "semantic-gold",
            family_id="evidence_dependency_reasoning",
            difficulty="medium",
        )
        self.assertIn("evaluation.md", prompt)
        self.assertIn("evidence-dependency-context.md", prompt)
        self.assertIn("semantic", prompt.lower())
        self.assertIn("message_id", prompt)
        self.assertIn("\"difficulty\": \"medium\"", prompt)
        self.assertIn("min_dependency_hops", prompt)

    def test_stage_prompt_source_list_is_current_and_rejects_legacy_public_stages(self) -> None:
        self.assertEqual(
            [path.name for path in list_stage_prompt_sources("conversation-plan", family_id="anti_interference")],
            ["workflow.md", "conversation-plan.md", "anti-interference-context.md"],
        )
        self.assertEqual(
            [path.name for path in list_stage_prompt_sources("semantic-gold", family_id="contradiction_update")],
            ["workflow.md", "evaluation.md", "contradiction-update-context.md"],
        )
        with self.assertRaises(ValueError):
            list_stage_prompt_sources("case-context")
        with self.assertRaises(ValueError):
            list_stage_prompt_sources("story-plan")


if __name__ == "__main__":
    unittest.main()
