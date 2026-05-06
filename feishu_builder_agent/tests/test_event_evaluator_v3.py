from __future__ import annotations

import unittest

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.event_alignment import align_events
from feishu_builder_agent.event_evaluator import evaluate_events
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_memory_failure_blueprint,
    sample_prediction_events,
    sample_state_trajectory,
)


class EventEvaluatorV3Tests(unittest.TestCase):
    def test_evaluates_verified_review_rejected_and_no_event_paths(self) -> None:
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=sample_collected_messages(),
        )
        candidate_events, session_events = sample_prediction_events()
        candidate_alignment = align_events(
            case_id="case_fixture_v3",
            event_annotations=gold["event_annotations"],
            predictions=candidate_events,
            prediction_source="candidate_events",
        )
        session_alignment = align_events(
            case_id="case_fixture_v3",
            event_annotations=gold["event_annotations"],
            predictions=session_events,
            prediction_source="session_events",
        )
        report = evaluate_events(
            case_id="case_fixture_v3",
            event_annotations=gold["event_annotations"],
            candidate_alignment=candidate_alignment,
            session_alignment=session_alignment,
            candidate_events=candidate_events,
            session_events=session_events,
        )
        self.assertGreaterEqual(report["overall"]["verified_recall"], 0.5)
        self.assertGreaterEqual(report["overall"]["needs_review_accuracy"], 0.5)
        self.assertGreaterEqual(report["overall"]["rejected_decision_accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
