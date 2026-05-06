from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.io_utils import write_json, write_jsonl
from feishu_builder_agent.memory_md_baseline_runner import run_memory_md_baseline
from feishu_builder_agent.raw_message_rag_runner import run_raw_message_rag
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_memory_failure_blueprint,
    sample_prediction_events,
    sample_state_trajectory,
    sample_task_wiki_state,
)
from feishu_builder_agent.value_evaluator import evaluate_value


class ValueEvaluatorV3Tests(unittest.TestCase):
    def test_value_eval_aggregates_three_systems(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir)
            write_json(case_dir / "case_spec.json", sample_case_spec())
            write_jsonl(case_dir / "data" / "collected_messages.jsonl", sample_collected_messages())
            gold = generate_annotation_gold(
                case_spec=sample_case_spec(),
                memory_failure_blueprint=sample_memory_failure_blueprint(),
                state_trajectory=sample_state_trajectory(),
                conversation_plan=sample_conversation_plan(),
                collected_messages=sample_collected_messages(),
            )
            write_json(case_dir / "gold" / "query_benchmark.json", gold["query_benchmark"])
            memory_report = run_memory_md_baseline(case_dir=case_dir)
            rag_report = run_raw_message_rag(case_dir=case_dir)
            _, session_events = sample_prediction_events()
            report = evaluate_value(
                case_id="case_fixture_v3",
                query_benchmark=gold["query_benchmark"],
                task_wiki_state=sample_task_wiki_state(),
                session_events=session_events,
                memory_md_baseline_report=memory_report,
                raw_message_rag_report=rag_report,
            )
            self.assertEqual(report["baseline_mode"], "openclaw_real")
            self.assertIn("task_wiki", report["overall"])
            self.assertIn("openclaw_memory_md", report["overall"])
            self.assertIn("raw_message_rag", report["overall"])


if __name__ == "__main__":
    unittest.main()
