from __future__ import annotations

import unittest

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.event_alignment import align_events
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_coverage_spec,
    sample_memory_failure_blueprint,
    sample_prediction_events,
    sample_state_trajectory,
    sample_story_beats,
)


class EventAlignmentV3Tests(unittest.TestCase):
    def test_alignment_reports_exact_partial_and_unmatched(self) -> None:
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            coverage_spec=sample_coverage_spec(),
            story_beats=sample_story_beats(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=sample_collected_messages(),
        )
        candidate_events, _ = sample_prediction_events()
        report = align_events(
            case_id="case_fixture_v3",
            event_annotations=gold["event_annotations"],
            predictions=candidate_events,
            prediction_source="candidate_events",
        )
        alignment_types = {item["alignment_type"] for item in report["alignments"]}
        self.assertIn("exact", alignment_types)
        self.assertIn("unmatched", alignment_types)


if __name__ == "__main__":
    unittest.main()
