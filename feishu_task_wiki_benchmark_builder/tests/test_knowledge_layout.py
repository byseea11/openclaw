from __future__ import annotations

import unittest
from pathlib import Path


class KnowledgeLayoutTests(unittest.TestCase):
    def test_all_internal_skill_files_exist(self) -> None:
        expected = [
            "root.md",
            "family-selection.md",
            "capability-brief.md",
            "case-world.md",
            "story-plan.md",
            "evaluation.md",
        ]
        for name in expected:
            self.assertTrue((Path("feishu_task_wiki_benchmark_builder/skills") / name).exists())

    def test_root_skill_contains_stage_routing_and_identification(self) -> None:
        content = Path("feishu_task_wiki_benchmark_builder/skills/root.md").read_text(encoding="utf-8")
        self.assertIn("Stage Routing", content)
        self.assertIn("Stage Identification", content)
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
