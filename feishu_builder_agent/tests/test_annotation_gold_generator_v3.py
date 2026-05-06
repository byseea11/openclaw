from __future__ import annotations

import unittest

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_memory_failure_blueprint,
    sample_state_trajectory,
)


class AnnotationGoldGeneratorV3Tests(unittest.TestCase):
    def test_generates_positive_negative_and_review_annotations(self) -> None:
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=sample_collected_messages(),
        )
        rows = gold["event_annotations"]
        verdicts = {row["evidence_message_id"]: (row["annotation_kind"], row["expected_verdict"]) for row in rows}
        self.assertEqual(verdicts["m1"], ("positive_event", "verified"))
        self.assertEqual(verdicts["m4"], ("review_event", "needs_review"))
        self.assertEqual(verdicts["m5"], ("negative_no_event", "no_event"))
        self.assertEqual(verdicts["m6"], ("review_event", "rejected"))

    def test_ordinary_ack_role_does_not_force_negative_when_text_has_event(self) -> None:
        rows = sample_collected_messages()
        rows[4]["content_text"] = "收到，最终负责人就是 xzy。"
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=rows,
        )
        verdicts = {row["evidence_message_id"]: row for row in gold["event_annotations"]}
        self.assertEqual(verdicts["m5"]["annotation_kind"], "positive_event")


if __name__ == "__main__":
    unittest.main()
