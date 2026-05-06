from __future__ import annotations

import unittest

from feishu_builder_agent.annotation_gold_generator import generate_annotation_gold
from feishu_builder_agent.gold_validator import validate_gold_against_observed_data
from feishu_builder_agent.schemas import ValidationError
from feishu_builder_agent.tests.v3_fixtures import (
    sample_case_spec,
    sample_collected_messages,
    sample_conversation_plan,
    sample_memory_failure_blueprint,
    sample_state_trajectory,
)


class GoldValidatorV3Tests(unittest.TestCase):
    def test_detects_evidence_quote_mismatch(self) -> None:
        messages = sample_collected_messages()
        gold = generate_annotation_gold(
            case_spec=sample_case_spec(),
            memory_failure_blueprint=sample_memory_failure_blueprint(),
            state_trajectory=sample_state_trajectory(),
            conversation_plan=sample_conversation_plan(),
            collected_messages=messages,
        )
        gold["event_annotations"][0]["evidence_quote"] = "不存在的证据"
        with self.assertRaises(ValidationError):
            validate_gold_against_observed_data(
                collected_messages=messages,
                event_annotations=gold["event_annotations"],
                block_annotations=gold["block_annotations"],
                query_benchmark=gold["query_benchmark"],
            )


if __name__ == "__main__":
    unittest.main()
