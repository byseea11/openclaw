from __future__ import annotations

import unittest
from pathlib import Path


class BoundaryTests(unittest.TestCase):
    def test_trigger_shell_points_to_code_side_workflow_skill(self) -> None:
        content = Path(".agents/skills/feishu-task-wiki-benchmark-builder/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("feishu_task_wiki_benchmark_builder/skills/workflow.md", content)

    def test_docs_directory_no_longer_contains_machine_prompt_or_skill_docs(self) -> None:
        self.assertFalse(Path("feishu_task_wiki_benchmark_builder/docs/prompts.md").exists())
        self.assertFalse(Path("feishu_task_wiki_benchmark_builder/docs/prompt-boundaries.md").exists())
        self.assertFalse(Path("feishu_task_wiki_benchmark_builder/docs/artifact-contracts.md").exists())

    def test_prompt_runtime_is_code_owned(self) -> None:
        prompt_module = Path("feishu_task_wiki_benchmark_builder/prompt.py").read_text(encoding="utf-8")
        self.assertIn("build_case_context_system_prompt", prompt_module)
        self.assertIn("build_story_plan_system_prompt", prompt_module)
        self.assertIn("build_stage_system_prompt", prompt_module)

    def test_runner_help_lists_generic_phase1_step(self) -> None:
        script = Path("amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh").read_text(encoding="utf-8")
        self.assertIn("phase1-step", script)
        self.assertIn("auth-check", script)
        self.assertIn("repo 根 `.env`", script)
        self.assertIn("--stage case-context", script)
        self.assertNotIn("phase1-family-selection", script)

    def test_builder_package_and_runner_do_not_retain_legacy_family_ids(self) -> None:
        legacy_ids = [
            "_".join(["context", "interference"]),
            "_".join(["temporal", "supersession"]),
            "_".join(["evidence", "traceability"]),
            "_".join(["dependency", "impact", "tracking"]),
        ]
        roots = [
            Path("feishu_task_wiki_benchmark_builder"),
            Path("amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh"),
        ]
        for root in roots:
            paths = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
            for path in paths:
                if "__pycache__" in path.parts:
                    continue
                if path.suffix not in {".py", ".md", ".sh", ".json"} and path.name != "SKILL.md":
                    continue
                content = path.read_text(encoding="utf-8")
                for legacy_id in legacy_ids:
                    self.assertNotIn(legacy_id, content, msg=f"{legacy_id} leaked in {path}")


if __name__ == "__main__":
    unittest.main()
