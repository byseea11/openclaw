from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.io_utils import write_json
from feishu_builder_agent.report_builder import build_reports


class ReportBuilderV3Tests(unittest.TestCase):
    def test_builds_final_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir)
            write_json(case_dir / "reports" / "event_alignment.json", {"case_id": "case_fixture_v3", "alignments": [], "summary": {}, "target_prediction_source": "session_events"})
            write_json(case_dir / "reports" / "event_eval.json", {"case_id": "case_fixture_v3", "overall": {"verified_recall": 1.0}, "by_failure_mode": {}})
            write_json(
                case_dir / "reports" / "block_eval.json",
                {
                    "case_id": "case_fixture_v3",
                    "overall": {"topic_hit_rate": 1.0},
                    "by_failure_mode": {},
                    "block_eval_on_all_gold_events": {},
                    "block_eval_on_aligned_events_only": {},
                },
            )
            write_json(case_dir / "reports" / "qa_eval.json", {"case_id": "case_fixture_v3", "overall": {"faithfulness": 1.0}, "by_failure_mode": {}, "queries": [], "judge_mode": "heuristic_fallback"})
            write_json(case_dir / "reports" / "value_eval.json", {"case_id": "case_fixture_v3", "baseline_mode": "openclaw_real", "systems": {}, "overall": {}, "by_failure_mode": {}, "by_query_family": {}})
            report = build_reports(case_dir)
            self.assertIn("overall_eval", report)
            self.assertIn("final_benchmark_report", report)


if __name__ == "__main__":
    unittest.main()
