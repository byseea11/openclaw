from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder.cli import (
    compile_phase1_batch,
    compile_phase2_batch,
    compile_phase3_batch,
    main,
)
from feishu_task_wiki_benchmark_builder.config import FORMAL_FAMILY_IDS
from feishu_task_wiki_benchmark_builder.io import read_json


class BatchModeTests(unittest.TestCase):
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

    def test_phase1_batch_generates_round_robin_families_under_batch_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = compile_phase1_batch(
                dataset_root=tmpdir,
                batch_size=4,
                batch_id="batch_unit_001",
                seed=700,
                difficulty="easy",
                families="all",
            )
            batch_dir = Path(result["batch_dir"])
            self.assertEqual(batch_dir, Path(tmpdir) / "batches" / "batch_unit_001")
            self.assertEqual(result["completed_case_count"], 4)
            manifest = read_json(batch_dir / "batch_manifest.json")
            self.assertEqual([case["family_id"] for case in manifest["cases"]], list(FORMAL_FAMILY_IDS))
            self.assertEqual([case["seed"] for case in manifest["cases"]], [700, 701, 702, 703])
            for case in manifest["cases"]:
                case_dir = Path(case["case_dir"])
                self.assertEqual(case_dir.parent, batch_dir / "cases")
                self.assertTrue((case_dir / "case_spec.json").exists())
                self.assertEqual(case["status"], "completed")
                self.assertEqual(case["phase1"]["status"], "completed")
            active_batch = read_json(Path(tmpdir) / "active_batch.json")
            self.assertEqual(active_batch["batch_id"], "batch_unit_001")
            self.assertEqual(Path(active_batch["batch_dir"]), batch_dir)
            self.assertEqual(active_batch["last_completed_phase"], "phase1")

    def test_phase2_and_phase3_batch_consume_cases_and_write_batch_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            phase1 = compile_phase1_batch(
                dataset_root=tmpdir,
                batch_size=2,
                batch_id="batch_unit_002",
                seed=710,
                difficulty="easy",
                families="anti_interference,contradiction_update",
            )
            phase2 = compile_phase2_batch(
                batch_dir=phase1["batch_dir"],
                semantic_gold_mode="rule",
            )
            self.assertEqual(phase2["completed_case_count"], 2)
            self.assertTrue(Path(phase2["batch_phase2_summary_path"]).exists())
            phase3 = compile_phase3_batch(batch_dir=phase1["batch_dir"])
            self.assertEqual(phase3["completed_case_count"], 2)
            score_path = Path(phase3["batch_phase3_score_path"])
            self.assertTrue(score_path.exists())
            batch_score = read_json(score_path)
            self.assertEqual(batch_score["scored_case_count"], 2)
            self.assertIn("anti_interference", batch_score["family_level_scores"])
            self.assertIn("contradiction_update", batch_score["family_level_scores"])
            manifest = read_json(Path(phase1["batch_dir"]) / "batch_manifest.json")
            self.assertTrue(all(case["phase2"]["status"] == "completed" for case in manifest["cases"]))
            self.assertTrue(all(case["phase3"]["status"] == "completed" for case in manifest["cases"]))

    def test_phase2_and_phase3_default_to_active_case_even_when_active_batch_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            phase1 = self._run_cli(
                [
                    "phase1",
                    "--dataset-root",
                    tmpdir,
                    "--batch-size",
                    "1",
                    "--batch-id",
                    "batch_unit_003",
                    "--seed",
                    "720",
                    "--difficulty",
                    "easy",
                    "--families",
                    "anti_interference",
                ]
            )
            self.assertEqual(phase1["batch_id"], "batch_unit_003")
            single_phase1 = self._run_cli([
                "phase1",
                "--dataset-root",
                tmpdir,
                "--seed",
                "730",
                "--difficulty",
                "easy",
                "--family-id",
                "anti_interference",
            ])
            self.assertIn("case_dir", single_phase1)
            phase2 = self._run_cli(["phase2", "--dataset-root", tmpdir, "--semantic-gold", "rule"])
            self.assertEqual(phase2["completed_stages"][-1], "replay-eval")
            self.assertNotIn("batch_id", phase2)
            self.assertEqual(Path(str(phase2["case_dir"])), Path(str(single_phase1["case_dir"])))
            phase3 = self._run_cli(["phase3", "--dataset-root", tmpdir])
            self.assertEqual(phase3["completed_stages"][-1], "comparative-score")
            self.assertNotIn("batch_id", phase3)
            self.assertEqual(Path(str(phase3["case_dir"])), Path(str(single_phase1["case_dir"])))
            phase2_batch = self._run_cli([
                "phase2",
                "--dataset-root",
                tmpdir,
                "--batch-dir",
                phase1["batch_dir"],
                "--semantic-gold",
                "rule",
            ])
            self.assertEqual(phase2_batch["batch_id"], "batch_unit_003")
            phase3_batch = self._run_cli([
                "phase3",
                "--dataset-root",
                tmpdir,
                "--batch-dir",
                phase1["batch_dir"],
            ])
            self.assertEqual(phase3_batch["batch_id"], "batch_unit_003")
            current = self._run_cli(["current-batch", "--dataset-root", tmpdir])
            self.assertEqual(current["batch_id"], "batch_unit_003")

    def test_case_dir_and_batch_dir_conflict_is_readable(self) -> None:
        error_text = self._run_cli_error(
            ["phase2", "--case-dir", "some-case", "--batch-dir", "some-batch"]
        )
        self.assertIn("--case-dir 不能和 --batch-dir 同时使用", error_text)
        error_text = self._run_cli_error(
            ["phase3", "--case-dir", "some-case", "--batch-dir", "some-batch"]
        )
        self.assertIn("--case-dir 不能和 --batch-dir 同时使用", error_text)

    def test_phase_scripts_help_mentions_batch_mode(self) -> None:
        for script in (
            "amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh",
            "amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh",
            "amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh",
        ):
            with self.subTest(script=script):
                completed = subprocess.run(
                    ["bash", script, "--help"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0)
                self.assertIn("--batch", completed.stdout)


if __name__ == "__main__":
    unittest.main()
