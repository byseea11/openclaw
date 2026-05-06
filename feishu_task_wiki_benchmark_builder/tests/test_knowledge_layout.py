from __future__ import annotations

import unittest
from pathlib import Path


class KnowledgeLayoutTests(unittest.TestCase):
    def test_internal_skill_files_exist(self) -> None:
        skill_files = sorted(path.name for path in Path("feishu_task_wiki_benchmark_builder/skills").glob("*.md"))
        self.assertEqual(
            skill_files,
            [
                "anti-interference-context.md",
                "capability-brief.md",
                "case-world.md",
                "characters.md",
                "collect.md",
                "command-plan.md",
                "contradiction-update-context.md",
                "conversation-plan.md",
                "coverage-spec.md",
                "evaluation.md",
                "evidence-dependency-context.md",
                "execute.md",
                "family-selection.md",
                "pre-annotation-validate.md",
                "spec-generation.md",
                "state-trajectory.md",
                "story-beats.md",
                "story-plan.md",
                "task-actor-layout.md",
                "v3-phase1-dataset-generation.md",
                "workflow.md",
            ],
        )

    def test_workflow_skill_contains_stage_routing_and_skill_references(self) -> None:
        content = Path("feishu_task_wiki_benchmark_builder/skills/workflow.md").read_text(encoding="utf-8")
        self.assertIn("Stage Routing", content)
        self.assertIn("family-selection.md", content)
        self.assertIn("capability-brief.md", content)
        self.assertIn("task-actor-layout.md", content)
        self.assertIn("case-world.md", content)
        self.assertIn("story-beats.md", content)
        self.assertIn("conversation-plan.md", content)
        self.assertIn("story-plan.md", content)
        self.assertIn("anti-interference-context.md", content)
        self.assertIn("contradiction-update-context.md", content)
        self.assertIn("evidence-dependency-context.md", content)
        self.assertIn("evaluation.md", content)
        self.assertIn("case_context.json", content)
        self.assertIn("task_actor_layout.json", content)
        self.assertIn("case_world.json", content)
        self.assertIn("story_beats.json", content)
        self.assertIn("conversation_plan.json", content)
        self.assertIn("story_plan.json", content)

    def test_human_docs_structure_exists(self) -> None:
        self.assertTrue(Path("feishu_task_wiki_benchmark_builder/docs/architecture.md").exists())
        self.assertTrue(Path("feishu_task_wiki_benchmark_builder/docs/workflow.md").exists())
        self.assertTrue(Path("feishu_task_wiki_benchmark_builder/docs/evaluation.md").exists())
        self.assertTrue(Path("feishu_task_wiki_benchmark_builder/docs/families/overview.md").exists())

    def test_family_docs_include_downstream_help_and_probe_guidance(self) -> None:
        for path in Path("feishu_task_wiki_benchmark_builder/docs/families").glob("*.md"):
            if path.name == "overview.md":
                continue
            content = path.read_text(encoding="utf-8")
            self.assertIn("对后续阶段的帮助", content)
            self.assertIn("有效 probe", content)
            self.assertIn("无效 probe", content)


if __name__ == "__main__":
    unittest.main()
