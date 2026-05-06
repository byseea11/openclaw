from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder.cli import compile_phase1, compile_phase2, compile_phase3
from feishu_task_wiki_benchmark_builder.family_catalog import ordered_family_ids
from feishu_task_wiki_benchmark_builder.io import read_jsonl


class EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(
            os.environ,
            {"FEISHU_TASK_WIKI_BENCHMARK_BUILDER_MODEL_BACKEND": "fixture"},
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def test_phase1_outputs_minimal_checkpoint_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compiled = compile_phase1(dataset_root=tmpdir, seed=21, difficulty="medium")
            case_dir = Path(compiled["case_dir"])
            self.assertTrue((case_dir / "input" / "case_context.json").exists())
            self.assertTrue((case_dir / "input" / "story_plan.json").exists())
            self.assertTrue((case_dir / "input" / "command_plan.jsonl").exists())
            self.assertTrue((case_dir / "runtime" / "executed_commands.jsonl").exists())
            self.assertTrue((case_dir / "data" / "collected_messages.jsonl").exists())
            self.assertTrue((case_dir / "checks" / "pre_annotation_validation_report.json").exists())
            self.assertTrue((case_dir / "logs" / "model_call_log.jsonl").exists())
            self.assertFalse((case_dir / "input" / "family_selection.json").exists())
            self.assertFalse((case_dir / "input" / "memory_capability_brief.json").exists())
            self.assertFalse((case_dir / "case_spec.json").exists())
            self.assertFalse((case_dir / "input" / "case_world.json").exists())
            model_calls = read_jsonl(case_dir / "logs" / "model_call_log.jsonl")
            self.assertEqual([row["stage"] for row in model_calls], ["case-context", "story-plan"])
            for row in model_calls:
                self.assertIn("backend", row)
                self.assertIn("base_url", row)
                self.assertIn("duration_ms", row)
                self.assertNotIn("system_prompt", row)
                self.assertNotIn("user_payload", row)
                self.assertNotIn("request_payload", row)
                self.assertNotIn("response_payload", row)
                self.assertNotIn("raw_response_text", row)

    def test_phase2_and_phase3_output_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compiled = compile_phase1(dataset_root=tmpdir, seed=22, difficulty="medium")
            compile_phase2(case_dir=compiled["case_dir"])
            compile_phase3(case_dir=compiled["case_dir"])
            case_dir = Path(compiled["case_dir"])
            self.assertTrue((case_dir / "gold" / "annotation_gold.jsonl").exists())
            self.assertTrue((case_dir / "gold" / "query_benchmark.json").exists())
            self.assertTrue((case_dir / "reports" / "replay_eval.json").exists())
            self.assertTrue((case_dir / "reports" / "baseline_eval.json").exists())
            self.assertTrue((case_dir / "reports" / "value_eval.json").exists())
            self.assertTrue((case_dir / "reports" / "final_benchmark_report.md").exists())

    def test_build_all_supports_every_formal_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for offset, family_id in enumerate(ordered_family_ids(), start=31):
                compiled = compile_phase1(
                    dataset_root=tmpdir,
                    seed=offset,
                    difficulty="medium",
                    family_id=family_id,
                )
                compile_phase2(case_dir=compiled["case_dir"])
                compile_phase3(case_dir=compiled["case_dir"])
                case_dir = Path(compiled["case_dir"])
                report_text = (case_dir / "reports" / "final_benchmark_report.md").read_text(encoding="utf-8")
                self.assertIn("Project Requirement Mapping", report_text)


if __name__ == "__main__":
    unittest.main()
