from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.llm import BuilderModelClient, FixtureModelClient, ModelCallResult
from feishu_task_wiki_benchmark_builder.schemas import validate_story_plan
from feishu_task_wiki_benchmark_builder.stages.case_context import build_case_context, generate_case_context
from feishu_task_wiki_benchmark_builder.stages.case_world import build_case_world_artifact
from feishu_task_wiki_benchmark_builder.stages.common import generate_default_seed, normalize_seed
from feishu_task_wiki_benchmark_builder.stages.command_plan import build_command_plan
from feishu_task_wiki_benchmark_builder.stages.conversation_plan import build_conversation_plan_artifact
from feishu_task_wiki_benchmark_builder.stages.story_plan import build_story_plan
from feishu_task_wiki_benchmark_builder.stages.story_beats import build_story_beats_artifact
from feishu_task_wiki_benchmark_builder.stages.task_actor_layout import build_task_actor_layout_artifact


class WeirdNamingCaseContextClient:
    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, object],
    ) -> ModelCallResult:
        return ModelCallResult(
            payload={
                "family_id": "contradiction_update",
                "benchmark_requirement_name": "矛盾更新测试",
                "benchmark_requirement_summary": "test summary",
                "report_display_name": "矛盾更新测试",
                "capability_under_test": "test capability",
                "why_memory_systems_may_fail": "test why",
                "generation_rules": ["rule 1"],
                "required_case_structure": ["structure 1"],
                "probe_strategy": ["probe 1"],
                "expected_good_system_behavior": ["behavior 1"],
                "case_id": "contra_001",
                "task_id": "TASK-123",
                "seed": 999,
                "difficulty": "hard",
                "comparison_target": "wrong_target",
                "organization": "Org",
                "team": "Team",
                "business_goal": "Goal",
                "scenario_summary": "Summary",
                "family_fit_explanation": "Reason",
            },
            backend="fixture",
            model="fixture-test",
            base_url="fixture://local",
            duration_ms=0,
        )


class GenerationContractTests(unittest.TestCase):
    def test_default_seed_generation_is_unique_and_normalized(self) -> None:
        first = generate_default_seed()
        second = generate_default_seed()
        self.assertNotEqual(first, second)
        self.assertGreater(second, first)
        self.assertEqual(normalize_seed(17), 17)

    def test_case_context_contains_required_fields(self) -> None:
        case_context = build_case_context(
            seed=11,
            requested_family_id="contradiction_update",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        self.assertEqual(case_context["family_id"], "contradiction_update")
        self.assertEqual(case_context["benchmark_requirement_name"], "矛盾更新测试")
        self.assertTrue(case_context["benchmark_requirement_summary"])
        self.assertTrue(case_context["report_display_name"])
        self.assertTrue(case_context["generation_rules"])
        self.assertTrue(case_context["required_case_structure"])
        self.assertTrue(case_context["probe_strategy"])
        self.assertIn("这个场景", case_context["family_fit_explanation"])

    def test_case_context_ids_are_code_owned_not_model_named(self) -> None:
        case_context, _ = generate_case_context(
            seed=17,
            requested_family_id="contradiction_update",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=WeirdNamingCaseContextClient(),
        )
        self.assertEqual(case_context["case_id"], "case_0017_contradiction_update")
        self.assertEqual(case_context["task_id"], "FEISHU-217")
        self.assertEqual(case_context["seed"], 17)
        self.assertEqual(case_context["difficulty"], "medium")
        self.assertEqual(case_context["comparison_target"], "default_memory_architectures")

    def test_case_context_without_explicit_seed_does_not_fall_back_to_case_0001(self) -> None:
        case_context = build_case_context(
            seed=None,
            requested_family_id="anti_interference",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        self.assertNotEqual(case_context["seed"], 1)
        self.assertNotEqual(case_context["case_id"], "case_0001_anti_interference")
        self.assertTrue(case_context["case_id"].startswith("case_"))

    def test_story_plan_contains_formal_sections(self) -> None:
        case_context = build_case_context(
            seed=12,
            requested_family_id="evidence_dependency_reasoning",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        story_plan = build_story_plan(case_context=case_context, model_client=FixtureModelClient())
        self.assertIn("task", story_plan)
        self.assertIn("actors", story_plan)
        self.assertIn("task_actor_layout", story_plan)
        self.assertIn("state_changes", story_plan)
        self.assertIn("message_beats", story_plan)
        self.assertIn("planned_probe_queries", story_plan)
        self.assertEqual(story_plan["task"]["role"], "target_task")
        self.assertTrue(story_plan["planned_probe_queries"][0]["query"])
        self.assertNotEqual(
            story_plan["planned_probe_queries"][0]["query"],
            story_plan["planned_probe_queries"][0]["expected_good_behavior"],
        )
        probe = story_plan["planned_probe_queries"][0]["query"]
        self.assertIn("依据来自谁", probe)
        self.assertIn("影响", probe)
        message_texts = [beat["message_intent"] for beat in story_plan["message_beats"]]
        self.assertTrue(any("确认过" in text for text in message_texts))
        self.assertTrue(any("我听别人说" in text for text in message_texts))
        dependency_contexts = story_plan["task_actor_layout"]["dependency_context_blocks"]
        self.assertEqual(len(dependency_contexts), 4)
        dependency_roles = {context["dependency_role"] for context in dependency_contexts}
        self.assertIn("verified_anchor", dependency_roles)
        self.assertIn("hearsay_channel", dependency_roles)
        self.assertIn("ambiguous_channel", dependency_roles)
        self.assertIn("downstream_impact", dependency_roles)
        self.assertTrue(all("speaker_actor_id" in beat for beat in story_plan["message_beats"]))

    def test_story_plan_normalizes_casefolded_speaker_to_actor_id(self) -> None:
        normalized = validate_story_plan(
            {
                "story_id": "story_case_0001",
                "case_id": "case_0001_contradiction_update",
                "family_id": "contradiction_update",
                "task": {"task_id": "FEISHU-201", "task_name": "发布接入", "role": "target_task"},
                "actors": [
                    {"actor_id": "xavier", "display_name": "Xavier", "role": "current_owner"},
                    {"actor_id": "alice", "display_name": "Alice", "role": "reviewer"},
                ],
                "task_actor_layout": {"target_task_id": "FEISHU-201"},
                "state_changes": [{"task_id": "FEISHU-201", "field": "owner", "sequence": []}],
                "message_beats": [
                    {
                        "beat_id": "beat_001",
                        "speaker": "xavier",
                        "session_id": "main_chat",
                        "message_intent": "当前 owner 是 Xavier。",
                    }
                ],
                "planned_probe_queries": [
                    {
                        "query": "当前 owner 是谁？",
                        "tests_family": "contradiction_update",
                        "expected_good_behavior": "回答 Xavier 是当前 owner。",
                    }
                ],
            }
        )
        beat = normalized["message_beats"][0]
        self.assertEqual(beat["speaker_actor_id"], "xavier")
        self.assertEqual(beat["speaker"], "Xavier")

    def test_command_plan_compiles_from_conversation_plan_actor_refs(self) -> None:
        case_context = build_case_context(
            seed=13,
            requested_family_id="evidence_dependency_reasoning",
            difficulty="medium",
            comparison_target="default_memory_architectures",
            model_client=FixtureModelClient(),
        )
        story_plan = build_story_plan(case_context=case_context, model_client=FixtureModelClient())
        task_actor_layout_artifact = build_task_actor_layout_artifact(
            case_context=case_context,
            story_plan=story_plan,
        )
        case_world_artifact = build_case_world_artifact(
            case_context=case_context,
            task_actor_layout_artifact=task_actor_layout_artifact,
            story_plan=story_plan,
        )
        story_beats_artifact = build_story_beats_artifact(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_plan=story_plan,
        )
        conversation_plan = build_conversation_plan_artifact(
            case_context=case_context,
            case_world_artifact=case_world_artifact,
            story_beats_artifact=story_beats_artifact,
            story_plan=story_plan,
        )
        command_plan = build_command_plan(conversation_plan=conversation_plan)
        message_rows = [
            row
            for row in command_plan
            if row["action_type"] in {"send_message", "reply_in_thread"} and row["beat_id"]
        ]
        self.assertEqual(message_rows[0]["actor_id"], conversation_plan["turns"][0]["speaker_actor_id"])
        annotation_turns = [turn for turn in conversation_plan["turns"] if turn["annotation_target"]]
        self.assertEqual(message_rows[-1]["actor_id"], annotation_turns[-1]["speaker_actor_id"])
        self.assertTrue(all(row["lark_cli_command"].startswith("lark-cli im +") for row in command_plan))
        self.assertTrue(any(row["action_type"].startswith("fetch_") for row in command_plan))
        self.assertGreater(len(conversation_plan["turns"]), len(annotation_turns))

    def test_command_plan_uses_session_type_not_session_name_for_thread_detection(self) -> None:
        conversation_plan = {
            "case_id": "case_0013_anti_interference",
            "family_id": "anti_interference",
            "task_id": "FEISHU-213",
            "sessions": [
                {
                    "session_id": "thread_docs",
                    "session_type": "chat",
                    "title": "thread_docs 会话",
                    "session_purpose": "名字里有 thread，但正式类型仍是 chat。",
                }
            ],
            "turns": [
                {
                    "turn_id": "turn_001",
                    "beat_id": "beat_001",
                    "sequence_no": 1,
                    "session_id": "thread_docs",
                    "speaker_actor_id": "alice",
                    "speaker": "Alice",
                    "planned_message_text": "FEISHU-213 当前 owner 是 Alice。",
                }
            ],
        }
        command_plan = build_command_plan(conversation_plan=conversation_plan)
        self.assertTrue(any(row["action_type"] == "send_message" for row in command_plan))
        self.assertTrue(any(row["action_type"] == "fetch_chat_messages" for row in command_plan))
        self.assertFalse(any(row["action_type"] == "fetch_thread_messages" for row in command_plan))


if __name__ == "__main__":
    unittest.main()
