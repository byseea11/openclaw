from __future__ import annotations

import unittest

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.block_evaluator import evaluate_blocks
from feishu_builder_agent.event_alignment import align_events
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_memory_failure_blueprint,
    sample_prediction_events,
    sample_state_trajectory,
    sample_task_wiki_state,
)


class BlockEvaluatorV3Tests(unittest.TestCase):
    def test_reports_all_gold_and_aligned_only_metrics(self) -> None:
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=sample_collected_messages(),
        )
        _, session_events = sample_prediction_events()
        session_alignment = align_events(
            case_id="case_fixture_v3",
            event_annotations=gold["event_annotations"],
            predictions=session_events,
            prediction_source="session_events",
        )
        report = evaluate_blocks(
            case_id="case_fixture_v3",
            block_annotations=gold["block_annotations"],
            event_alignment=session_alignment,
            task_wiki_state=sample_task_wiki_state(),
        )
        self.assertIn("block_eval_on_all_gold_events", report)
        self.assertIn("block_eval_on_aligned_events_only", report)


if __name__ == "__main__":
    unittest.main()
