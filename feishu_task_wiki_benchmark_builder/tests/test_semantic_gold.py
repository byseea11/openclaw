from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder.llm import (
    ModelBackendError,
    ModelCallResult,
    ModelPayloadValidationError,
)
from feishu_task_wiki_benchmark_builder.stages import semantic_gold


CASE_CONTEXT = {
    "case_id": "case_001",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "difficulty": "hard",
}
STORY_PLAN = {
    "planned_probe_queries": [
        {
            "query": "FEISHU-201 当前 blocker 是什么？",
            "expected_good_behavior": "回答当前 blocker，并引用 observed evidence。",
        }
    ]
}
ANNOTATION_ROWS = [
    {
        "annotation_id": "ann_001",
        "message_id": "om_001",
        "turn_id": "turn_001",
        "beat_id": "beat_001",
        "evidence_text": "FEISHU-201 当前 blocker 是支付风控回归未完成。",
        "session_id": "main_chat",
        "turn_kind": "event_bearing",
        "purpose": "记录 blocker",
    },
    {
        "annotation_id": "ann_002",
        "message_id": "om_002",
        "turn_id": "turn_002",
        "beat_id": "beat_002",
        "evidence_text": "不要把并行文档评审的 owner 混进 FEISHU-201。",
        "session_id": "thread_docs",
        "turn_kind": "context_support",
        "purpose": "排除干扰",
    },
]
COLLECTED_MESSAGES = [
    {"message_id": "om_001", "message_text": "FEISHU-201 当前 blocker 是支付风控回归未完成。"},
    {"message_id": "om_002", "message_text": "不要把并行文档评审的 owner 混进 FEISHU-201。"},
]


class SequenceClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.stages: list[str] = []

    def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, Any]) -> ModelCallResult:
        self.stages.append(stage)
        payload = self.payloads.pop(0)
        return ModelCallResult(
            payload=payload,
            backend="fake",
            model="fake-model",
            base_url="fake://local",
            duration_ms=1,
        )


def _generate(*, client: SequenceClient, mode: str = "auto") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return semantic_gold.generate_semantic_gold(
        case_context=CASE_CONTEXT,
        story_plan=STORY_PLAN,
        collected_messages=COLLECTED_MESSAGES,
        annotation_gold_rows=ANNOTATION_ROWS,
        mode=mode,
        model_client=client,
    )


class SemanticGoldTests(unittest.TestCase):
    def test_repair_pass_fixes_missing_supporting_message_ids(self) -> None:
        client = SequenceClient(
            [
                {
                    "expected_task_facts": [
                        {"fact_id": "fact_001", "claim": "FEISHU-201 blocker 是支付风控回归。"}
                    ]
                },
                {
                    "expected_task_facts": [
                        {
                            "fact_id": "fact_001",
                            "claim": "FEISHU-201 blocker 是支付风控回归未完成。",
                            "required_supporting_message_ids": ["om_001"],
                        }
                    ],
                    "expected_event_semantics": [],
                    "expected_query_answers": [],
                },
            ]
        )
        artifact, logs = _generate(client=client)
        self.assertEqual(artifact["mode"], "llm")
        self.assertEqual(artifact["expected_task_facts"][0]["required_supporting_message_ids"], ["om_001"])
        self.assertEqual(client.stages, ["semantic-gold", "semantic-gold-repair"])
        self.assertEqual([entry["stage"] for entry in logs], ["semantic-gold", "semantic-gold-repair"])

    def test_normalizer_maps_annotation_and_turn_aliases_to_observed_message_ids(self) -> None:
        client = SequenceClient(
            [
                {
                    "expected_task_facts": [
                        {
                            "claim": "FEISHU-201 blocker 是支付风控回归未完成。",
                            "annotation_id": "ann_001",
                        }
                    ],
                    "expected_event_semantics": [
                        {
                            "purpose": "排除并行文档 owner 干扰。",
                            "turn_id": "turn_002",
                        }
                    ],
                    "expected_query_answers": [
                        {
                            "query": "FEISHU-201 当前 blocker 是什么？",
                            "expected_answer_summary": "支付风控回归未完成。",
                            "supporting_message_ids": ["om_001"],
                        }
                    ],
                }
            ]
        )
        artifact, _ = _generate(client=client, mode="llm")
        self.assertEqual(artifact["expected_task_facts"][0]["required_supporting_message_ids"], ["om_001"])
        self.assertEqual(artifact["expected_event_semantics"][0]["required_supporting_message_ids"], ["om_002"])
        self.assertEqual(artifact["expected_query_answers"][0]["required_supporting_message_ids"], ["om_001"])
        self.assertEqual(client.stages, ["semantic-gold"])

    def test_repair_failure_raises_readable_payload_validation_error(self) -> None:
        client = SequenceClient(
            [
                {"expected_task_facts": [{"claim": "bad", "required_supporting_message_ids": ["missing"]}]},
                {"expected_task_facts": [{"claim": "still bad", "required_supporting_message_ids": ["missing"]}]},
            ]
        )
        with self.assertRaises(ModelPayloadValidationError) as ctx:
            _generate(client=client, mode="llm")
        self.assertIn("semantic-gold payload validation failed after repair", str(ctx.exception))
        self.assertEqual(client.stages, ["semantic-gold", "semantic-gold-repair"])

    def test_auto_without_model_config_uses_rule_gold(self) -> None:
        with patch(
            "feishu_task_wiki_benchmark_builder.stages.semantic_gold.create_model_client",
            side_effect=ModelBackendError(
                "missing config",
                error_type="auth_config_error",
                error_code="missing_dotenv",
            ),
        ):
            artifact, logs = semantic_gold.generate_semantic_gold(
                case_context=CASE_CONTEXT,
                story_plan=STORY_PLAN,
                collected_messages=COLLECTED_MESSAGES,
                annotation_gold_rows=ANNOTATION_ROWS,
                mode="auto",
            )
        self.assertEqual(artifact["mode"], "rule")
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
