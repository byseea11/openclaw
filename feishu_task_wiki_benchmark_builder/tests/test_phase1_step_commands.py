from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder.cli import PHASE1_STAGE_ORDER, compile_phase1, compile_phase2, compile_phase3, main
from feishu_task_wiki_benchmark_builder.io import read_json, read_jsonl
from feishu_task_wiki_benchmark_builder.llm import ModelBackendError


class Phase1StepCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_replay_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.fake_replay_tmp.cleanup)
        fake_replay = Path(self.fake_replay_tmp.name) / "fake_openclaw_replay.mjs"
        fake_replay.write_text(
            """
let body = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => body += chunk);
process.stdin.on("end", () => {
  const input = JSON.parse(body);
  const answers = input.query_benchmark.queries.map((query) => ({
    query_id: query.query_id,
    answer: "fixture answer with evidence",
    supporting_message_ids: query.supporting_message_ids || [],
    judge_result: { success: true }
  }));
  process.stdout.write(JSON.stringify({ baseline_mode: "openclaw_real_replay", answers }));
});
""".strip()
            + "\n",
            encoding="utf8",
        )
        self.env_patcher = patch.dict(
            os.environ,
            {
                "FEISHU_TASK_WIKI_BENCHMARK_BUILDER_MODEL_BACKEND": "fixture",
                "OPENCLAW_BENCHMARK_REPLAY_COMMAND": f"node {fake_replay}",
            },
            clear=False,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def _run_cli(self, argv: list[str]) -> dict[str, object]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())

    def _run_cli_error(self, argv: list[str]) -> str:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                main(argv)
        self.assertEqual(ctx.exception.code, 2)
        return stderr.getvalue()

    def test_phase1_spec_generation_prints_artifacts_and_updates_active_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "spec-generation",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "11",
                    "--family-id",
                    "anti_interference",
                ]
            )
            self.assertEqual(result["stage"], "spec-generation")
            case_spec = next(artifact["artifact"] for artifact in result["artifacts"] if artifact["artifact_path"].endswith("case_spec.json"))
            self.assertEqual(case_spec["case_id"], "case_0011_anti_interference")
            self.assertTrue(Path(result["model_call_log_path"]).exists())
            self.assertTrue(Path(result["active_case_path"]).exists())
            artifact_paths = [artifact["artifact_path"] for artifact in result["artifacts"]]
            self.assertTrue(any(path.endswith("input/case_context.json") for path in artifact_paths))
            self.assertTrue(any(path.endswith("case_spec.json") for path in artifact_paths))
            active_case = read_json(Path(tmpdir) / "active_case.json")
            self.assertEqual(active_case["last_completed_stage"], "spec-generation")

    def test_spec_generation_without_seed_generates_distinct_case_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "spec-generation",
                    "--dataset-root",
                    tmpdir,
                    "--family-id",
                    "anti_interference",
                ]
            )
            second = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "spec-generation",
                    "--dataset-root",
                    tmpdir,
                    "--family-id",
                    "anti_interference",
                ]
            )
            self.assertNotEqual(first["case_dir"], second["case_dir"])
            active_case = read_json(Path(tmpdir) / "active_case.json")
            self.assertEqual(active_case["case_dir"], second["case_dir"])
            self.assertEqual(active_case["last_completed_stage"], "spec-generation")

    def test_legacy_aggregate_phase1_stages_are_not_public_cli_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for legacy_stage in ("case-context", "story-plan"):
                with self.subTest(stage=legacy_stage):
                    error_text = self._run_cli_error(
                        ["phase1-step", "--stage", legacy_stage, "--dataset-root", tmpdir]
                    )
                    self.assertIn("invalid choice", error_text)

    def test_step_by_step_phase1_matches_compile_phase1_completed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as step_tmpdir, tempfile.TemporaryDirectory() as aggregate_tmpdir:
            spec = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "spec-generation",
                    "--dataset-root",
                    step_tmpdir,
                    "--seed",
                    "21",
                    "--difficulty",
                    "medium",
                    "--family-id",
                    "contradiction_update",
                ]
            )
            case_dir = spec["case_dir"]
            step_results = [spec]
            for stage in PHASE1_STAGE_ORDER[1:]:
                step_results.append(self._run_cli(["phase1-step", "--stage", stage, "--case-dir", case_dir]))
            self.assertEqual([result["stage"] for result in step_results], list(PHASE1_STAGE_ORDER))

            aggregate = compile_phase1(
                dataset_root=aggregate_tmpdir,
                seed=21,
                difficulty="medium",
                family_id="contradiction_update",
                comparison_target="default_memory_architectures",
            )
            self.assertEqual(aggregate["completed_stages"], list(PHASE1_STAGE_ORDER))

            step_case_dir = Path(case_dir)
            aggregate_case_dir = Path(aggregate["case_dir"])
            self.assertEqual(
                read_json(step_case_dir / "case_spec.json"),
                read_json(aggregate_case_dir / "case_spec.json"),
            )
            self.assertEqual(
                read_jsonl(step_case_dir / "input" / "command_plan.jsonl"),
                read_jsonl(aggregate_case_dir / "input" / "command_plan.jsonl"),
            )
            self.assertEqual(
                read_json(step_case_dir / "checks" / "pre_annotation_validation_report.json"),
                read_json(aggregate_case_dir / "checks" / "pre_annotation_validation_report.json"),
            )

    def test_command_plan_requires_conversation_plan_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "spec-generation",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "33",
                    "--family-id",
                    "anti_interference",
                ]
            )
            case_dir = spec["case_dir"]
            error_text = self._run_cli_error(
                ["phase1-step", "--stage", "command-plan", "--case-dir", case_dir]
            )
            self.assertIn("command-plan 缺少前置 artifact", error_text)
            self.assertIn("input/conversation_plan.json", error_text)

    def test_phase2_step_semantic_gold_can_run_from_active_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run_cli(
                [
                    "phase1",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "53",
                    "--family-id",
                    "private_info_in_official_file",
                ]
            )
            annotation = self._run_cli(["phase2-step", "--stage", "annotation-gold", "--dataset-root", tmpdir])
            semantic = self._run_cli(
                [
                    "phase2-step",
                    "--stage",
                    "semantic-gold",
                    "--semantic-gold",
                    "rule",
                    "--dataset-root",
                    tmpdir,
                ]
            )
            self.assertEqual(annotation["stage"], "annotation-gold")
            self.assertEqual(semantic["stage"], "semantic-gold")
            self.assertEqual(semantic["artifact"]["mode"], "rule")
            self.assertTrue(Path(semantic["artifact_path"]).exists())

    def test_phase2_and_phase3_can_resolve_active_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run_cli(
                [
                    "phase1",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "54",
                    "--family-id",
                    "anti_interference",
                ]
            )
            phase2 = self._run_cli(["phase2", "--semantic-gold", "rule", "--dataset-root", tmpdir])
            self.assertIn("case_dir", phase2)
            phase3 = self._run_cli(["phase3", "--dataset-root", tmpdir])
            self.assertEqual(phase3["case_dir"], phase2["case_dir"])
            active_case = read_json(Path(tmpdir) / "active_case.json")
            self.assertEqual(active_case["last_completed_stage"], "comparative-score")

    def test_aggregate_phase1_and_phase2_resume_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            phase1 = compile_phase1(
                dataset_root=tmpdir,
                seed=61,
                family_id="anti_interference",
                difficulty="medium",
            )
            case_dir = Path(phase1["case_dir"])
            model_log_path = case_dir / "logs" / "model_call_log.jsonl"
            model_log_before = read_jsonl(model_log_path)

            resumed_phase1 = compile_phase1(
                dataset_root=tmpdir,
                seed=61,
                family_id="anti_interference",
                difficulty="medium",
            )
            self.assertEqual(resumed_phase1["case_dir"], phase1["case_dir"])
            self.assertIn("spec-generation", resumed_phase1["skipped_stages"])
            self.assertIn("conversation-plan", resumed_phase1["skipped_stages"])
            self.assertEqual(read_jsonl(model_log_path), model_log_before)

            phase2 = compile_phase2(case_dir=case_dir, semantic_gold_mode="rule")
            phase2_model_log_before = read_jsonl(model_log_path)
            resumed_phase2 = compile_phase2(case_dir=case_dir, semantic_gold_mode="rule")
            self.assertEqual(resumed_phase2["case_dir"], phase2["case_dir"])
            self.assertEqual(set(resumed_phase2["skipped_stages"]), set(resumed_phase2["completed_stages"]))
            self.assertEqual(read_jsonl(model_log_path), phase2_model_log_before)
            self.assertTrue((case_dir / "runtime" / "builder_runs" / "latest.json").exists())

    def test_phase3_failure_writes_openclaw_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as replay_tmpdir:
            failing_replay = Path(replay_tmpdir) / "fail_openclaw_replay.mjs"
            failing_replay.write_text("process.stderr.write('fixture replay failed'); process.exit(7);\n", encoding="utf8")
            phase1 = compile_phase1(
                dataset_root=tmpdir,
                seed=62,
                family_id="anti_interference",
                difficulty="medium",
            )
            compile_phase2(case_dir=phase1["case_dir"], semantic_gold_mode="rule")
            case_dir = Path(phase1["case_dir"])
            with patch.dict(os.environ, {"OPENCLAW_BENCHMARK_REPLAY_COMMAND": f"node {failing_replay}"}, clear=False):
                with self.assertRaises(RuntimeError):
                    compile_phase3(case_dir=case_dir, force=True)

            self.assertTrue((case_dir / "runtime" / "openclaw_baseline" / "failure.json").exists())
            self.assertTrue((case_dir / "runtime" / "openclaw_baseline" / "replay_metadata.json").exists())
            self.assertTrue((case_dir / "reports" / "phase3_failure.json").exists())
            self.assertTrue((case_dir / "runtime" / "failures" / "phase3" / "openclaw-real-baseline-eval_latest.json").exists())
            self.assertTrue((case_dir / "runtime" / "builder_runs" / "latest.json").exists())

    def test_phase3_resume_skips_completed_openclaw_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as replay_tmpdir:
            failing_replay = Path(replay_tmpdir) / "fail_openclaw_replay.mjs"
            failing_replay.write_text("process.stderr.write('should not run'); process.exit(9);\n", encoding="utf8")
            phase1 = compile_phase1(
                dataset_root=tmpdir,
                seed=63,
                family_id="anti_interference",
                difficulty="medium",
            )
            compile_phase2(case_dir=phase1["case_dir"], semantic_gold_mode="rule")
            first_phase3 = compile_phase3(case_dir=phase1["case_dir"])
            self.assertIn("openclaw-real-baseline-eval", first_phase3["completed_stages"])

            with patch.dict(os.environ, {"OPENCLAW_BENCHMARK_REPLAY_COMMAND": f"node {failing_replay}"}, clear=False):
                resumed_phase3 = compile_phase3(case_dir=phase1["case_dir"])
            self.assertIn("openclaw-real-baseline-eval", resumed_phase3["skipped_stages"])
            self.assertIn("comparative-score", resumed_phase3["skipped_stages"])

    def test_failed_conversation_plan_writes_metadata_only_failure_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "spec-generation",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "46",
                    "--family-id",
                    "evidence_dependency_reasoning",
                ]
            )
            case_dir = Path(spec["case_dir"])
            for stage in PHASE1_STAGE_ORDER[1:9]:
                self._run_cli(["phase1-step", "--stage", stage, "--case-dir", str(case_dir)])
            with patch(
                "feishu_task_wiki_benchmark_builder.cli.generate_conversation_plan",
                side_effect=ModelBackendError(
                    "conversation-plan backend failed",
                    error_type="network_error",
                    error_code="network_error",
                    backend="openai",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    auth_source="repo_root_.env",
                    duration_ms=123,
                ),
            ):
                error_text = self._run_cli_error(
                    ["phase1-step", "--stage", "conversation-plan", "--case-dir", str(case_dir)]
                )
            self.assertIn("phase1-step::conversation-plan", error_text)
            model_calls = read_jsonl(case_dir / "logs" / "model_call_log.jsonl")
            self.assertEqual(model_calls[-1]["success"], False)
            self.assertEqual(model_calls[-1]["error_code"], "network_error")
            self.assertNotIn("system_prompt", model_calls[-1])


if __name__ == "__main__":
    unittest.main()
