from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.io_utils import write_json, write_jsonl
from feishu_builder_agent.memory_md_baseline_runner import run_memory_md_baseline
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_memory_failure_blueprint,
    sample_state_trajectory,
)


class MemoryMdBaselineRunnerTests(unittest.TestCase):
    def test_baseline_report_contains_answer_citation_and_traceability(self) -> None:
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
            report = run_memory_md_baseline(case_dir=case_dir)
            self.assertEqual(report["baseline_mode"], "openclaw_real")
            self.assertTrue(report["queries"])
            self.assertIn("traceability_message_ids", report["queries"][0])


if __name__ == "__main__":
    unittest.main()
