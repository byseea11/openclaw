from __future__ import annotations

import unittest

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.qa_evaluator import evaluate_qa
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_coverage_spec,
    sample_memory_failure_blueprint,
    sample_prediction_events,
    sample_state_trajectory,
    sample_story_beats,
    sample_task_wiki_state,
)


class QaEvaluatorV3Tests(unittest.TestCase):
    def test_returns_deterministic_and_semantic_judge_outputs(self) -> None:
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            coverage_spec=sample_coverage_spec(),
            story_beats=sample_story_beats(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=sample_collected_messages(),
        )
        _, session_events = sample_prediction_events()
        report = evaluate_qa(
            case_id="case_fixture_v3",
            query_benchmark=gold["query_benchmark"],
            session_events=session_events,
            task_wiki_state=sample_task_wiki_state(),
        )
        self.assertEqual(report["case_id"], "case_fixture_v3")
        self.assertTrue(report["queries"])
        self.assertIn("judge_mode", report)
        self.assertIn("answer_point_coverage", report["overall"])


if __name__ == "__main__":
    unittest.main()
