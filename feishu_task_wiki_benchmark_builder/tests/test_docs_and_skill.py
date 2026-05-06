from __future__ import annotations

import unittest
from pathlib import Path

from feishu_task_wiki_benchmark_builder.family_catalog import FAMILY_CATALOG, ordered_family_ids
from feishu_task_wiki_benchmark_builder.prompt import (
    build_case_context_system_prompt,
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
        self.assertIn("case-context", workflow)
        self.assertIn("pre-annotation-validate", workflow)
        self.assertIn("annotation-gold", workflow)
        self.assertIn("benchmark-report", workflow)

    def test_workflow_skill_exists_and_routes_phase1(self) -> None:
        workflow_skill = Path("feishu_task_wiki_benchmark_builder/skills/workflow.md").read_text(encoding="utf-8")
        self.assertIn("Canonical Workflow", workflow_skill)
        self.assertIn("Stage Routing", workflow_skill)
        self.assertIn("Stage Summary", workflow_skill)
        self.assertIn("Minimal Global Invariants", workflow_skill)
        self.assertIn("case-context", workflow_skill)
        self.assertIn("task-actor-layout", workflow_skill)
        self.assertIn("case-world", workflow_skill)
        self.assertIn("story-beats", workflow_skill)
        self.assertIn("conversation-plan", workflow_skill)
        self.assertIn("story-plan", workflow_skill)
        self.assertIn("command-plan", workflow_skill)
        self.assertIn("task_actor_layout.json", workflow_skill)
        self.assertIn("case_world.json", workflow_skill)
        self.assertIn("story_beats.json", workflow_skill)
        self.assertIn("conversation_plan.json", workflow_skill)
        self.assertIn("story_plan.json", workflow_skill)
        self.assertIn("效能指标验证", workflow_skill)
        self.assertIn("不允许走规则 fallback", workflow_skill)
        self.assertIn("family-selection.md", workflow_skill)
        self.assertIn("capability-brief.md", workflow_skill)
        self.assertIn("task-actor-layout.md", workflow_skill)
        self.assertIn("case-world.md", workflow_skill)
        self.assertIn("story-beats.md", workflow_skill)
        self.assertIn("conversation-plan.md", workflow_skill)
        self.assertIn("anti-interference-context.md", workflow_skill)
        self.assertIn("contradiction-update-context.md", workflow_skill)
        self.assertIn("evidence-dependency-context.md", workflow_skill)
        self.assertIn("evaluation.md", workflow_skill)

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
        self.assertIn("case-context", build_case_context_system_prompt())
        self.assertIn("story-plan", build_story_plan_system_prompt())
        architecture = Path("feishu_task_wiki_benchmark_builder/docs/architecture.md").read_text(encoding="utf-8")
        self.assertIn("builder_settings.yml", architecture)
        self.assertIn("只负责数字控制面", architecture)
        self.assertIn("唯一语义 owner", architecture)
        self.assertIn("prompt_settings_renderer.py", architecture)


if __name__ == "__main__":
    unittest.main()
