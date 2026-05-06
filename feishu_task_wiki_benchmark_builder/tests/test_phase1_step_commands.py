from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder.cli import compile_phase1, main
from feishu_task_wiki_benchmark_builder.io import read_json, read_jsonl
from feishu_task_wiki_benchmark_builder.llm import ModelBackendError, ModelPayloadValidationError


class Phase1StepCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(
            os.environ,
            {"FEISHU_TASK_WIKI_BENCHMARK_BUILDER_MODEL_BACKEND": "fixture"},
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

    def test_phase1_case_context_prints_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "11",
                    "--family-id",
                    "anti_interference",
                ]
            )
            self.assertEqual(result["stage"], "case-context")
            self.assertTrue(Path(result["artifact_path"]).exists())
            self.assertEqual(result["artifact"]["family_id"], "anti_interference")
            self.assertTrue(Path(result["model_call_log_path"]).exists())
            self.assertTrue(Path(result["active_case_path"]).exists())

    def test_case_context_without_seed_generates_distinct_case_dirs_and_updates_active_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
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
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--family-id",
                    "anti_interference",
                ]
            )
            self.assertNotEqual(first["case_dir"], second["case_dir"])
            active_case = read_json(Path(tmpdir) / "active_case.json")
            self.assertEqual(active_case["case_dir"], second["case_dir"])
            self.assertEqual(active_case["last_completed_stage"], "case-context")

    def test_auth_check_success_returns_structured_json(self) -> None:
        with patch(
            "feishu_task_wiki_benchmark_builder.cli.run_auth_check",
            return_value={
                "backend": "openai",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "auth_source": "repo_root_.env",
                "ok": True,
            },
        ):
            result = self._run_cli(["auth-check"])
        self.assertEqual(result["backend"], "openai")
        self.assertEqual(result["ok"], True)

    def test_auth_check_invalid_key_returns_exit_code_two_without_traceback(self) -> None:
        stderr = io.StringIO()
        with patch(
            "feishu_task_wiki_benchmark_builder.cli.run_auth_check",
            side_effect=ModelBackendError(
                "invalid key",
                error_type="auth_error",
                error_code="invalid_api_key",
                http_status=401,
                backend="openai",
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                auth_source="repo_root_.env",
            ),
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    main(["auth-check"])
        self.assertEqual(ctx.exception.code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error_code"], "invalid_api_key")
        self.assertIn("repo 根 `.env`", payload["message"])
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_step_by_step_phase1_matches_compile_phase1_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as step_tmpdir, tempfile.TemporaryDirectory() as aggregate_tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
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
            case_dir = case_context["case_dir"]
            step_results = [
                case_context,
                self._run_cli(["phase1-step", "--stage", "story-plan", "--case-dir", case_dir]),
                self._run_cli(["phase1-step", "--stage", "command-plan", "--case-dir", case_dir]),
                self._run_cli(["phase1-step", "--stage", "execute", "--case-dir", case_dir]),
                self._run_cli(["phase1-step", "--stage", "collect", "--case-dir", case_dir]),
                self._run_cli(
                    ["phase1-step", "--stage", "pre-annotation-validate", "--case-dir", case_dir]
                ),
            ]
            self.assertEqual(
                [result["stage"] for result in step_results],
                [
                    "case-context",
                    "story-plan",
                    "command-plan",
                    "execute",
                    "collect",
                    "pre-annotation-validate",
                ],
            )
            self.assertIn("artifacts", step_results[4])
            self.assertEqual(len(step_results[4]["artifacts"]), 3)

            aggregate = compile_phase1(
                dataset_root=aggregate_tmpdir,
                seed=21,
                difficulty="medium",
                family_id="contradiction_update",
                comparison_target="default_memory_architectures",
            )
            step_case_dir = Path(case_dir)
            aggregate_case_dir = Path(aggregate["case_dir"])
            self.assertEqual(
                read_json(step_case_dir / "input" / "case_context.json"),
                read_json(aggregate_case_dir / "input" / "case_context.json"),
            )
            self.assertEqual(
                read_json(step_case_dir / "input" / "story_plan.json"),
                read_json(aggregate_case_dir / "input" / "story_plan.json"),
            )
            self.assertEqual(
                read_jsonl(step_case_dir / "input" / "command_plan.jsonl"),
                read_jsonl(aggregate_case_dir / "input" / "command_plan.jsonl"),
            )
            self.assertEqual(
                read_jsonl(step_case_dir / "runtime" / "executed_commands.jsonl"),
                read_jsonl(aggregate_case_dir / "runtime" / "executed_commands.jsonl"),
            )
            self.assertEqual(
                read_jsonl(step_case_dir / "data" / "collected_messages.jsonl"),
                read_jsonl(aggregate_case_dir / "data" / "collected_messages.jsonl"),
            )
            self.assertEqual(
                read_json(step_case_dir / "checks" / "pre_annotation_validation_report.json"),
                read_json(aggregate_case_dir / "checks" / "pre_annotation_validation_report.json"),
            )

    def test_story_plan_requires_case_context_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir) / "cases" / "case_9999_missing"
            error_text = self._run_cli_error(
                ["phase1-step", "--stage", "story-plan", "--case-dir", str(case_dir)]
            )
            self.assertIn("story-plan 缺少前置 artifact", error_text)
            self.assertIn("input/case_context.json", error_text)

    def test_story_plan_uses_active_case_when_case_dir_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "51",
                    "--family-id",
                    "contradiction_update",
                ]
            )
            result = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "story-plan",
                    "--dataset-root",
                    tmpdir,
                ]
            )
            self.assertEqual(result["case_dir"], case_context["case_dir"])
            self.assertIn("artifacts", result)
            artifact_paths = [artifact["artifact_path"] for artifact in result["artifacts"]]
            self.assertTrue(any(path.endswith("input/conversation_plan.json") for path in artifact_paths))
            active_case = read_json(Path(tmpdir) / "active_case.json")
            self.assertEqual(active_case["last_completed_stage"], "story-plan")

    def test_case_context_triggers_preflight_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("feishu_task_wiki_benchmark_builder.cli.preflight_model_backend") as mock_preflight:
                self._run_cli(
                    [
                        "phase1-step",
                        "--stage",
                        "case-context",
                        "--dataset-root",
                        tmpdir,
                        "--seed",
                        "41",
                        "--family-id",
                        "anti_interference",
                    ]
                )
        mock_preflight.assert_called_once_with()

    def test_story_plan_triggers_preflight_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "42",
                    "--family-id",
                    "contradiction_update",
                ]
            )
            with patch("feishu_task_wiki_benchmark_builder.cli.preflight_model_backend") as mock_preflight:
                self._run_cli(["phase1-step", "--stage", "story-plan", "--case-dir", case_context["case_dir"]])
        mock_preflight.assert_called_once_with()

    def test_non_model_stage_does_not_trigger_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "43",
                    "--family-id",
                    "anti_interference",
                ]
            )
            self._run_cli(["phase1-step", "--stage", "story-plan", "--case-dir", case_context["case_dir"]])
            with patch("feishu_task_wiki_benchmark_builder.cli.preflight_model_backend") as mock_preflight:
                self._run_cli(["phase1-step", "--stage", "command-plan", "--case-dir", case_context["case_dir"]])
        mock_preflight.assert_not_called()

    def test_phase1_and_build_all_only_preflight_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("feishu_task_wiki_benchmark_builder.cli.preflight_model_backend") as mock_preflight:
                self._run_cli(
                    [
                        "phase1",
                        "--dataset-root",
                        tmpdir,
                        "--seed",
                        "44",
                        "--family-id",
                        "anti_interference",
                    ]
                )
        self.assertEqual(mock_preflight.call_count, 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("feishu_task_wiki_benchmark_builder.cli.preflight_model_backend") as mock_preflight:
                self._run_cli(
                    [
                        "build-all",
                        "--dataset-root",
                        tmpdir,
                        "--seed",
                        "45",
                        "--family-id",
                        "contradiction_update",
                    ]
                )
        self.assertEqual(mock_preflight.call_count, 1)

    def test_command_plan_requires_story_plan_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "33",
                    "--family-id",
                    "anti_interference",
                ]
            )
            case_dir = case_context["case_dir"]
            error_text = self._run_cli_error(
                ["phase1-step", "--stage", "command-plan", "--case-dir", case_dir]
            )
            self.assertIn("command-plan 缺少前置 artifact", error_text)
            self.assertIn("input/conversation_plan.json", error_text)

    def test_collect_requires_execute_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "34",
                    "--family-id",
                    "evidence_dependency_reasoning",
                ]
            )
            case_dir = case_context["case_dir"]
            self._run_cli(["phase1-step", "--stage", "story-plan", "--case-dir", case_dir])
            self._run_cli(["phase1-step", "--stage", "command-plan", "--case-dir", case_dir])
            error_text = self._run_cli_error(["phase1-step", "--stage", "collect", "--case-dir", case_dir])
            self.assertIn("collect 缺少前置 artifact", error_text)
            self.assertIn("runtime/execution_result.json", error_text)

    def test_current_case_command_prints_active_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "52",
                    "--family-id",
                    "evidence_dependency_reasoning",
                ]
            )
            current = self._run_cli(["current-case", "--dataset-root", tmpdir])
            self.assertEqual(current["case_dir"], case_context["case_dir"])
            self.assertEqual(current["last_completed_stage"], "case-context")

    def test_phase2_and_phase3_can_resolve_active_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run_cli(
                [
                    "phase1",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "53",
                    "--family-id",
                    "anti_interference",
                ]
            )
            phase2 = self._run_cli(["phase2", "--dataset-root", tmpdir])
            self.assertIn("case_dir", phase2)
            phase3 = self._run_cli(["phase3", "--dataset-root", tmpdir])
            self.assertEqual(phase3["case_dir"], phase2["case_dir"])
            active_case = read_json(Path(tmpdir) / "active_case.json")
            self.assertEqual(active_case["last_completed_stage"], "report")

    def test_failed_story_plan_writes_metadata_only_failure_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "46",
                    "--family-id",
                    "evidence_dependency_reasoning",
                ]
            )
            case_dir = Path(case_context["case_dir"])
            with patch(
                "feishu_task_wiki_benchmark_builder.cli.generate_story_plan",
                side_effect=ModelBackendError(
                    "story-plan backend failed",
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
                    ["phase1-step", "--stage", "story-plan", "--case-dir", str(case_dir)]
                )
            self.assertIn("phase1-step::story-plan", error_text)
            model_calls = read_jsonl(case_dir / "logs" / "model_call_log.jsonl")
            self.assertEqual(model_calls[-1]["success"], False)
            self.assertEqual(model_calls[-1]["error_code"], "network_error")
            self.assertNotIn("system_prompt", model_calls[-1])

    def test_story_plan_validation_error_writes_raw_payload_failure_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_context = self._run_cli(
                [
                    "phase1-step",
                    "--stage",
                    "case-context",
                    "--dataset-root",
                    tmpdir,
                    "--seed",
                    "47",
                    "--family-id",
                    "contradiction_update",
                ]
            )
            case_dir = Path(case_context["case_dir"])
            with patch(
                "feishu_task_wiki_benchmark_builder.cli.generate_story_plan",
                side_effect=ModelPayloadValidationError(
                    "story-plan payload validation failed: story_plan.task is required",
                    stage="story-plan",
                    payload={"story_id": "story_case_47", "task": ["bad"]},
                    backend="openai",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com/v1",
                    duration_ms=56,
                ),
            ):
                error_text = self._run_cli_error(
                    ["phase1-step", "--stage", "story-plan", "--case-dir", str(case_dir)]
                )
            self.assertIn("phase1-step::story-plan", error_text)
            self.assertIn("story_plan.task", error_text)
            model_calls = read_jsonl(case_dir / "logs" / "model_call_log.jsonl")
            self.assertEqual(model_calls[-1]["success"], False)
            self.assertEqual(model_calls[-1]["error_type"], "validation_error")
            self.assertEqual(model_calls[-1]["raw_payload"]["story_id"], "story_case_47")


if __name__ == "__main__":
    unittest.main()
