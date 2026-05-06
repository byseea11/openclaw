from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.cli import (
    compile_case_phase1,
    compile_case_phase2,
    compile_case_phase3,
    generate_case_spec_stage,
)


class EndToEndTests(unittest.TestCase):
    def test_compile_case_phase1_outputs_v3_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dataset"
            generated = generate_case_spec_stage(
                dataset_root=root,
                scenario_profile="enterprise_task_memory",
                difficulty="medium",
                seed=81,
                user_hint="重点覆盖 owner 修正、模糊 claim 和 cross-task 污染",
            )
            compiled = compile_case_phase1(case_spec_path=generated["case_spec_path"], dataset_root=root, dry_run=True)
            case_dir = Path(compiled["case_dir"])
            self.assertTrue((case_dir / "input" / "memory_failure_blueprint.json").exists())
            self.assertTrue((case_dir / "input" / "task_actor_layout.json").exists())
            self.assertTrue((case_dir / "input" / "conversation_plan.json").exists())
            self.assertTrue((case_dir / "input" / "command_plan.jsonl").exists())
            self.assertTrue((case_dir / "data" / "collected_messages.jsonl").exists())
            self.assertTrue((case_dir / "data" / "openclaw_message_ingress.jsonl").exists())
            self.assertTrue((case_dir / "checks" / "pre_annotation_validation_report.json").exists())
            self.assertFalse((case_dir / "gold").exists())
            self.assertFalse((case_dir / "reports").exists())

    def test_compile_case_phase3_outputs_full_v3_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "dataset"
            generated = generate_case_spec_stage(
                dataset_root=root,
                scenario_profile="enterprise_task_memory",
                difficulty="medium",
                seed=82,
                user_hint="覆盖完整 phase3 产物",
            )
            compiled = compile_case_phase1(case_spec_path=generated["case_spec_path"], dataset_root=root, dry_run=True)
            compile_case_phase2(case_dir_path=compiled["case_dir"])
            compile_case_phase3(case_dir_path=compiled["case_dir"])
            case_dir = Path(compiled["case_dir"])
            self.assertTrue((case_dir / "gold" / "event_annotations.jsonl").exists())
            self.assertTrue((case_dir / "predictions" / "task_wiki_state.json").exists())
            self.assertTrue((case_dir / "reports" / "value_eval.json").exists())
            self.assertTrue((case_dir / "reports" / "final_benchmark_report.json").exists())


if __name__ == "__main__":
    unittest.main()
