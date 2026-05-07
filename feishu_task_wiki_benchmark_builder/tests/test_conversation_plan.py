from __future__ import annotations

import unittest
from typing import Any

from feishu_task_wiki_benchmark_builder.llm import ModelCallResult, ModelPayloadValidationError
from feishu_task_wiki_benchmark_builder.stages.conversation_plan import generate_conversation_plan


CASE_CONTEXT = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "difficulty": "easy",
}
CASE_WORLD = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "source_sessions": [
        {
            "session_id": "main_chat",
            "session_type": "chat",
            "title": "发布准备群",
            "session_purpose": "记录 FEISHU-201 当前状态",
        }
    ],
}
STORY_BEATS = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "beats": [
        {
            "beat_id": "beat_001",
            "target_session_id": "main_chat",
            "benchmark_role": "event_bearing",
            "description": "建立当前 owner",
        }
    ],
}
STORY_PLAN = {
    "story_id": "story_case_001_anti_interference",
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task": {"task_id": "FEISHU-201", "task_name": "发布准备", "role": "target_task"},
    "actors": [{"actor_id": "alice", "display_name": "Alice", "role": "target_owner"}],
    "message_beats": [],
    "planned_probe_queries": [],
}
CHARACTERS = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "characters": [
        {
            "person_id": "alice",
            "name": "Alice",
            "department": "研发",
            "title": "Owner",
            "communication_style": "直接",
            "task_relationship": "owner",
            "simulated_open_id": "ou_sim_alice",
        }
    ],
}
ACTOR_REGISTRY = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "actors": [
        {
            "person_id": "alice",
            "actor_slot_id": "alice",
            "name": "Alice",
            "simulated_open_id": "ou_sim_alice",
        }
    ],
}
OFFICIAL_FILE_PLAN = {
    "case_id": "case_001_anti_interference",
    "family_id": "anti_interference",
    "task_id": "FEISHU-201",
    "official_files": [],
}


def _turn(
    *,
    speaker_actor_id: str,
    turn_id: str,
    sequence_no: int,
    event_bearing: bool,
) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "beat_id": "beat_001" if event_bearing else "",
        "sequence_no": sequence_no,
        "session_id": "main_chat",
        "speaker_actor_id": speaker_actor_id,
        "speaker": "Alice",
        "planned_message_text": "FEISHU-201 当前由 Alice 负责。",
        "turn_kind": "event_bearing" if event_bearing else "context_support",
        "annotation_target": event_bearing,
        "event_bearing": event_bearing,
    }


def _payload(*, speaker_actor_id: str) -> dict[str, Any]:
    turns = [
        _turn(
            speaker_actor_id=speaker_actor_id,
            turn_id=f"turn_{index:03d}",
            sequence_no=index,
            event_bearing=index <= 6,
        )
        for index in range(1, 26)
    ]
    for index, turn in enumerate(turns, start=1):
        turn["planned_message_text"] = f"{turn['planned_message_text']} 第 {index} 条。"
    return {"turns": turns}


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
        return ModelCallResult(
            payload=self.payloads.pop(0),
            backend="fake",
            model="fake-model",
            base_url="fake://local",
            duration_ms=1,
        )


def _generate(client: SequenceClient) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return generate_conversation_plan(
        case_context=CASE_CONTEXT,
        case_world_artifact=CASE_WORLD,
        story_beats_artifact=STORY_BEATS,
        story_plan=STORY_PLAN,
        characters=CHARACTERS,
        actor_registry=ACTOR_REGISTRY,
        official_file_plan=OFFICIAL_FILE_PLAN,
        model_client=client,
    )


class ConversationPlanTests(unittest.TestCase):
    def test_repair_pass_fixes_unknown_speaker_actor_id(self) -> None:
        client = SequenceClient([_payload(speaker_actor_id="paula"), _payload(speaker_actor_id="alice")])

        artifact, logs = _generate(client)

        self.assertEqual(artifact["turns"][0]["speaker_actor_id"], "alice")
        self.assertEqual(client.stages, ["conversation-plan", "conversation-plan-repair"])
        self.assertEqual([entry["stage"] for entry in logs], ["conversation-plan", "conversation-plan-repair"])
        self.assertEqual(client.user_payloads[0]["output_contract"]["allowed_speaker_actor_ids"], ["alice"])
        repair_context = client.user_payloads[1]["repair_context"]
        self.assertIn("unknown person_id: paula", repair_context["validation_error"])

    def test_repair_failure_keeps_initial_and_repair_payloads(self) -> None:
        client = SequenceClient([_payload(speaker_actor_id="paula"), _payload(speaker_actor_id="paula")])

        with self.assertRaises(ModelPayloadValidationError) as ctx:
            _generate(client)

        self.assertIn("conversation-plan payload validation failed after repair", str(ctx.exception))
        self.assertEqual(client.stages, ["conversation-plan", "conversation-plan-repair"])
        self.assertEqual(ctx.exception.payload["initial_invalid_payload"], _payload(speaker_actor_id="paula"))
        self.assertEqual(ctx.exception.payload["repair_invalid_payload"], _payload(speaker_actor_id="paula"))


if __name__ == "__main__":
    unittest.main()
