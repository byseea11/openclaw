from __future__ import annotations

import unittest
from pathlib import Path

from feishu_task_wiki_benchmark_builder.family_catalog import FAMILY_CATALOG, ordered_family_ids
from feishu_task_wiki_benchmark_builder.prompt import (
    build_capability_brief_system_prompt,
    build_case_world_system_prompt,
    build_family_selection_system_prompt,
    build_story_plan_system_prompt,
)


class DocsAndSkillTests(unittest.TestCase):
    def test_skill_shell_exists(self) -> None:
        skill_path = Path(".agents/skills/feishu-task-wiki-benchmark-builder/SKILL.md")
        openai_yaml = Path(".agents/skills/feishu-task-wiki-benchmark-builder/agents/openai.yaml")
        self.assertTrue(skill_path.exists())
        self.assertTrue(openai_yaml.exists())

    def test_workflow_doc_lists_all_phases(self) -> None:
        workflow = Path("feishu_task_wiki_benchmark_builder/docs/workflow.md").read_text(encoding="utf-8")
        self.assertIn("dataset-plan", workflow)
        self.assertIn("pre-annotation-validate", workflow)
        self.assertIn("annotation-gold", workflow)
        self.assertIn("benchmark-report", workflow)

    def test_root_skill_lists_internal_skills(self) -> None:
        root_skill = Path("feishu_task_wiki_benchmark_builder/skills/root.md").read_text(encoding="utf-8")
        self.assertIn("family-selection", root_skill)
        self.assertIn("capability-brief", root_skill)
        self.assertIn("case-world", root_skill)
        self.assertIn("story-plan", root_skill)
        self.assertIn("evaluation", root_skill)

    def test_every_family_id_has_a_matching_family_doc(self) -> None:
        for family_id in ordered_family_ids():
            path = Path("feishu_task_wiki_benchmark_builder/docs/families") / f"{family_id.replace('_', '-')}.md"
            self.assertTrue(path.exists())

    def test_family_catalog_carries_requirement_mapping_fields(self) -> None:
        for family_id in ordered_family_ids():
            definition = FAMILY_CATALOG[family_id]
            self.assertTrue(definition.benchmark_requirement_name)
            self.assertTrue(definition.benchmark_requirement_summary)
            self.assertTrue(definition.report_display_name)

    def test_prompt_module_exports_required_stage_prompts(self) -> None:
        self.assertIn("anti_interference", build_family_selection_system_prompt())
        self.assertIn("memory-capability-brief", build_capability_brief_system_prompt())
        self.assertIn("case-world", build_case_world_system_prompt())
        self.assertIn("story-plan", build_story_plan_system_prompt())


if __name__ == "__main__":
    unittest.main()
