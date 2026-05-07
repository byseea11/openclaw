from __future__ import annotations

import unittest
from typing import Any

from feishu_task_wiki_benchmark_builder.llm import ModelCallResult, ModelPayloadValidationError
from feishu_task_wiki_benchmark_builder.stages.story_plan import generate_story_plan


CASE_CONTEXT = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "difficulty": "hard",
}


def _valid_story_plan() -> dict[str, Any]:
    return {
        "story_id": "story_case_001_anti_interference",
        "case_id": "case_001_anti_interference",
        "family_id": "anti_interference",
        "task": {"task_id": "FEISHU-201", "task_name": "发布准备", "role": "target_task"},
        "actors": [
            {
                "actor_id": "alice",
                "display_name": "Alice",
                "role": "target_owner",
            }
        ],
        "task_actor_layout": {
            "target_task_id": "FEISHU-201",
            "shared_actors": ["alice"],
            "actor_task_roles": [
                {"actor_id": "alice", "task_id": "FEISHU-201", "role": "target_owner"}
            ],
        },
        "state_changes": [
            {
                "task_id": "FEISHU-201",
                "field": "owner",
                "sequence": [{"value": "Alice", "status": "current"}],
            }
        ],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "purpose": "establish_current_owner",
                "speaker_actor_id": "alice",
                "session_id": "main_chat",
                "message_intent": "FEISHU-201 当前由 Alice 负责。",
            }
        ],
        "planned_probe_queries": [
            {
                "query": "FEISHU-201 当前由谁负责？",
                "expected_good_behavior": "回答 Alice 是当前负责人，并引用目标任务证据。",
            }
        ],
    }


class SequenceClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.stages: list[str] = []
        self.user_payloads: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> ModelCallResult:
        self.stages.append(stage)
        self.user_payloads.append(user_payload)
        payload = self.payloads.pop(0)
        return ModelCallResult(
            payload=payload,
            backend="fake",
            model="fake-model",
            base_url="fake://local",
            duration_ms=1,
        )


class StoryPlanTests(unittest.TestCase):
    def test_repair_pass_fixes_missing_task_payload(self) -> None:
        invalid_payload = {
            "story_id": "story_case_001_anti_interference",
            "case_id": "case_001_anti_interference",
            "family_id": "anti_interference",
            "actors": _valid_story_plan()["actors"],
            "task_actor_layout": _valid_story_plan()["task_actor_layout"],
        }
        client = SequenceClient([invalid_payload, _valid_story_plan()])

        artifact, logs = generate_story_plan(case_context=CASE_CONTEXT, model_client=client)

        self.assertEqual(artifact["task"]["task_id"], "FEISHU-201")
        self.assertEqual(client.stages, ["story-plan", "story-plan-repair"])
        self.assertEqual([entry["stage"] for entry in logs], ["story-plan", "story-plan-repair"])
        repair_context = client.user_payloads[1]["repair_context"]
        self.assertIn("story_plan.task is required", repair_context["validation_error"])
        self.assertEqual(repair_context["invalid_payload"], invalid_payload)

    def test_repair_failure_raises_payload_validation_error_with_both_payloads(self) -> None:
        initial_invalid = {"story_id": "story_case_001_anti_interference"}
        repair_invalid = {
            **_valid_story_plan(),
            "message_beats": [
                {
                    "beat_id": "beat_001",
                    "purpose": "bad speaker",
                    "speaker_actor_id": "missing_actor",
                    "session_id": "main_chat",
                    "message_intent": "FEISHU-201 当前由 Alice 负责。",
                }
            ],
        }
        client = SequenceClient([initial_invalid, repair_invalid])

        with self.assertRaises(ModelPayloadValidationError) as ctx:
            generate_story_plan(case_context=CASE_CONTEXT, model_client=client)

        self.assertIn("story-plan payload validation failed after repair", str(ctx.exception))
        self.assertEqual(client.stages, ["story-plan", "story-plan-repair"])
        self.assertEqual(ctx.exception.payload["initial_invalid_payload"], initial_invalid)
        self.assertEqual(ctx.exception.payload["repair_invalid_payload"], repair_invalid)
        self.assertIn("story_plan.task is required", ctx.exception.payload["initial_validation_error"])
        self.assertIn("speaker_actor_id", ctx.exception.payload["repair_validation_error"])


if __name__ == "__main__":
    unittest.main()
