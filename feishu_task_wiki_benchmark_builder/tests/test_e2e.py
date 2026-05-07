from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder.cli import compile_phase1, compile_phase2, compile_phase3
from feishu_task_wiki_benchmark_builder.family_catalog import ordered_family_ids
from feishu_task_wiki_benchmark_builder.io import read_json, read_jsonl


class EndToEndTests(unittest.TestCase):
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

    def test_phase1_outputs_minimal_checkpoint_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compiled = compile_phase1(dataset_root=tmpdir, seed=21, difficulty="medium")
            case_dir = Path(compiled["case_dir"])
            self.assertTrue((case_dir / "input" / "case_context.json").exists())
            self.assertTrue((case_dir / "case_spec.json").exists())
            self.assertTrue((case_dir / "input" / "family_selection.json").exists())
            self.assertTrue((case_dir / "input" / "memory_capability_brief.json").exists())
            self.assertTrue((case_dir / "input" / "task_actor_layout.json").exists())
            self.assertTrue((case_dir / "input" / "case_world.json").exists())
            self.assertTrue((case_dir / "input" / "characters.json").exists())
            self.assertTrue((case_dir / "input" / "actor_registry.json").exists())
            self.assertTrue((case_dir / "input" / "state_trajectory.json").exists())
            self.assertTrue((case_dir / "input" / "coverage_spec.json").exists())
            self.assertTrue((case_dir / "input" / "story_beats.json").exists())
            self.assertTrue((case_dir / "input" / "conversation_plan.json").exists())
            self.assertTrue((case_dir / "input" / "command_plan.jsonl").exists())
            self.assertTrue((case_dir / "execution_plan.json").exists())
            self.assertTrue((case_dir / "runtime" / "executed_commands.jsonl").exists())
            self.assertTrue((case_dir / "runtime" / "execution_result.json").exists())
            self.assertTrue((case_dir / "data" / "collected_messages.jsonl").exists())
            self.assertTrue((case_dir / "checks" / "pre_annotation_validation_report.json").exists())
            self.assertTrue((case_dir / "logs" / "model_call_log.jsonl").exists())
            characters = read_json(case_dir / "input" / "characters.json")
            actor_registry = read_json(case_dir / "input" / "actor_registry.json")
            self.assertTrue(characters["characters"])
            first_actor = actor_registry["actors"][0]
            self.assertEqual(
                first_actor["simulated_open_id"],
                f"ou_sim_{first_actor['person_id']}",
            )
            command_rows = read_jsonl(case_dir / "input" / "command_plan.jsonl")
            message_rows = [
                row
                for row in command_rows
                if row["action_type"] in {"send_message", "reply_in_thread"} and row["beat_id"]
            ]
            self.assertTrue(message_rows)
            self.assertNotIn("【project_manager/Alice】", message_rows[0]["params"]["content_text"])
            self.assertNotIn("Alice", message_rows[0]["params"]["content_text"])
            self.assertIn("【", message_rows[0]["params"]["content_text"])
            collected_rows = read_jsonl(case_dir / "data" / "collected_messages.jsonl")
            ingress_rows = read_jsonl(case_dir / "data" / "openclaw_message_ingress.jsonl")
            first_event_collected = next(row for row in collected_rows if row["annotation_target"])
            self.assertEqual(first_event_collected["normalized_actor_id"], message_rows[0]["speaker_ref"])
            self.assertIn("actual_sender", first_event_collected)
            self.assertTrue(first_event_collected["simulated_speaker"]["open_id"].startswith("ou_sim_"))
            self.assertEqual(
                next(row for row in ingress_rows if row["benchmark_trace"]["annotation_target"])["sender"]["sender_id"]["open_id"],
                first_event_collected["simulated_speaker"]["open_id"],
            )
            self.assertNotIn("【", ingress_rows[0]["message"]["content"])
            self.assertNotIn("Alice", ingress_rows[0]["message"]["content"])
            self.assertEqual(len(ingress_rows), len(collected_rows))
            model_calls = read_jsonl(case_dir / "logs" / "model_call_log.jsonl")
            self.assertEqual(
                [row["stage"] for row in model_calls],
                ["case-context", "story-plan", "conversation-plan"],
            )
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
            self.assertTrue((case_dir / "reports" / "openclaw_baseline_eval.json").exists())
            self.assertTrue((case_dir / "reports" / "phase3_score.json").exists())

    def test_hard_phase1_builds_enterprise_scale_openclaw_ingress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compiled = compile_phase1(
                dataset_root=tmpdir,
                seed=23,
                difficulty="hard",
                family_id="anti_interference",
            )
            case_dir = Path(compiled["case_dir"])
            conversation_plan = read_json(case_dir / "input" / "conversation_plan.json")
            characters = read_json(case_dir / "input" / "characters.json")
            collected_rows = read_jsonl(case_dir / "data" / "collected_messages.jsonl")
            ingress_rows = read_jsonl(case_dir / "data" / "openclaw_message_ingress.jsonl")
            self.assertGreaterEqual(len(conversation_plan["turns"]), 80)
            self.assertLessEqual(len(conversation_plan["turns"]), 120)
            self.assertGreaterEqual(len(conversation_plan["sessions"]), 8)
            self.assertGreaterEqual(len(characters["characters"]), 24)
            self.assertGreaterEqual(len(ingress_rows), 80)
            self.assertEqual(len(ingress_rows), len(collected_rows))
            self.assertGreaterEqual(sum(1 for row in collected_rows if row["event_bearing"]), 18)
            self.assertGreaterEqual(sum(1 for row in collected_rows if not row["event_bearing"]), 30)
            compile_phase2(case_dir=compiled["case_dir"])
            annotation_gold = read_jsonl(case_dir / "gold" / "annotation_gold.jsonl")
            self.assertEqual(
                len(annotation_gold),
                sum(1 for row in collected_rows if row["annotation_target"] or row["event_bearing"]),
            )

    def test_private_info_official_file_family_lands_trace_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compiled = compile_phase1(
                dataset_root=tmpdir,
                seed=24,
                difficulty="hard",
                family_id="private_info_in_official_file",
            )
            case_dir = Path(compiled["case_dir"])
            official_file_plan = read_json(case_dir / "input" / "official_file_plan.json")
            conversation_plan = read_json(case_dir / "input" / "conversation_plan.json")
            collected_rows = read_jsonl(case_dir / "data" / "collected_messages.jsonl")
            ingress_rows = read_jsonl(case_dir / "data" / "openclaw_message_ingress.jsonl")
            validation_report = read_json(case_dir / "checks" / "pre_annotation_validation_report.json")

            self.assertEqual(official_file_plan["family_id"], "private_info_in_official_file")
            self.assertTrue(official_file_plan["official_files"][0]["private_info_items"])
            self.assertTrue(any(turn["official_file_ref"] for turn in conversation_plan["turns"]))
            self.assertTrue(any(turn["private_info_ref"] for turn in conversation_plan["turns"]))
            self.assertTrue(any(turn["task_relevance_boundary"] for turn in conversation_plan["turns"]))
            self.assertTrue(any(row["private_info_ref"] for row in collected_rows))
            self.assertTrue(any(row["benchmark_trace"]["official_file_ref"] for row in ingress_rows))
            check_ids = {check["check_id"]: check["passed"] for check in validation_report["checks"]}
            self.assertTrue(check_ids["official_file_references_landed"])
            self.assertTrue(check_ids["private_info_boundary_landed"])

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
                phase3_score = read_json(case_dir / "reports" / "phase3_score.json")
                self.assertIn("aggregate_scores", phase3_score)
                self.assertIn("per_query_scores", phase3_score)


if __name__ == "__main__":
    unittest.main()
