from __future__ import annotations

import unittest
from typing import Any

from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.complexity_validator import build_complexity_report
from feishu_builder_agent.conversation_plan_generator import (
    _fallback_conversation_plan,
    generate_conversation_plan,
    generate_conversation_plan_with_mode,
)
from feishu_builder_agent.spec_generator import build_complexity_profile
from feishu_builder_agent.story_generator import generate_story
from feishu_builder_agent.timeline_planner import generate_timeline


CASE_SPEC = {
    "case_id": "case_live_language",
    "task_id": "REQ-998",
    "title": "",
    "company_type": "",
    "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
    "scenario_profile": "enterprise_release_coordination",
    "title_hint": "飞书协作上线口径收敛",
    "main_goal_hint": "围绕五月初上线目标形成统一口径",
    "main_goal": "",
    "difficulty": "medium",
    "seed": 9,
}


CASE_SEED = {
    "case_id": CASE_SPEC["case_id"],
    "task_id": CASE_SPEC["task_id"],
    "domain": "enterprise_product_launch",
    "company_type_hint": CASE_SPEC["company_type"],
    "department_hints": CASE_SPEC["department_hints"],
    "scenario_profile": CASE_SPEC["scenario_profile"],
    "title_hint": CASE_SPEC["title_hint"],
    "main_goal_hint": CASE_SPEC["main_goal_hint"],
    "difficulty": CASE_SPEC["difficulty"],
    "seed": CASE_SPEC["seed"],
    "complexity_profile": build_complexity_profile(CASE_SPEC["difficulty"]),
}


class _EnglishLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return dict(self.payload)


class LiveLanguageFallbackTests(unittest.TestCase):
    def test_conversation_plan_repair_makes_hard_plan_pass_complexity_targets_for_fallback(self) -> None:
        hard_seed = {
            **CASE_SEED,
            "difficulty": "hard",
            "complexity_profile": build_complexity_profile("hard"),
        }
        world = generate_case_world(hard_seed)
        characters = generate_characters(world)
        plan = generate_conversation_plan(world, characters, llm_client=None)
        self.assertGreaterEqual(len(plan["turns"]), 28)
        thread_counts: dict[str, int] = {}
        session_map = {item["session_id"]: item for item in plan["sessions"]}
        for turn in plan["turns"]:
            session = session_map[turn["session_id"]]
            if session["source_type"] == "thread":
                thread_counts[session["source_ref"]] = thread_counts.get(session["source_ref"], 0) + 1
        self.assertGreaterEqual(max(thread_counts.values()), 5)
        collected_messages = [
            {
                "turn_id": turn["turn_id"],
                "sequence_no": turn["sequence_no"],
                "session_id": turn["session_id"],
                "source_type": session_map[turn["session_id"]]["source_type"],
                "source_ref": session_map[turn["session_id"]]["source_ref"],
                "chat_ref": session_map[turn["session_id"]]["chat_ref"],
                "speaker_ref": turn["speaker_ref"],
                "topic_key": turn["topic_key"],
                "turn_purpose": turn["turn_purpose"],
                "supports_event_types": turn["supports_event_types"],
                "references_previous_turns": turn["references_previous_turns"],
                "state_transition": turn["state_transition"],
                "semantic_payload": turn["semantic_payload"],
                "root_turn_id": session_map[turn["session_id"]].get("root_turn_id"),
                "content_text": f"【产品/林晨】{turn['semantic_payload']}",
                "message_id": f"om_{turn['turn_id']}",
                "collect_source": "test",
                "actual_sender": {"open_id": "ou_1", "name": "tester", "sender_type": "user"},
                "simulated_speaker": {
                    "speaker_ref": turn["speaker_ref"],
                    "open_id": "ou_sim_test",
                    "name": "林晨",
                    "department": "产品",
                    "role": "产品经理",
                    "stance": "保守推进",
                },
                "normalized_actor_id": turn["speaker_ref"],
                "speaker_resolution_mode": "command_plan_only",
                "prefix_speaker_hint": {"speaker_ref": turn["speaker_ref"], "name": "林晨", "department": "产品"},
            }
            for turn in plan["turns"]
        ]
        report = build_complexity_report(hard_seed, plan, collected_messages)
        self.assertGreaterEqual(report["metrics"]["message_count"], 28)
        self.assertGreaterEqual(report["metrics"]["thread_reply_depth"], 5)
        self.assertGreaterEqual(report["metrics"]["supersession_count"], 2)
        self.assertGreaterEqual(report["metrics"]["cross_source_revision_count"], 2)

    def test_conversation_plan_repair_makes_hard_plan_pass_complexity_targets_for_live_output(self) -> None:
        hard_seed = {
            **CASE_SEED,
            "difficulty": "hard",
            "complexity_profile": build_complexity_profile("hard"),
        }
        world = generate_case_world(hard_seed)
        characters = generate_characters(world)
        tiny_plan = _fallback_conversation_plan(world, characters)
        tiny_plan["turns"] = tiny_plan["turns"][:21]
        for session in tiny_plan["sessions"]:
            session["planned_turn_count"] = sum(1 for turn in tiny_plan["turns"] if turn["session_id"] == session["session_id"])
        completed_plan = generate_conversation_plan(world, characters, llm_client=None)

        class _TinyPlanLLM:
            def __init__(self) -> None:
                self._payloads = [tiny_plan, completed_plan]

            def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
                return self._payloads.pop(0)

        repaired_plan, mode, generation_log = generate_conversation_plan_with_mode(
            world,
            characters,
            llm_client=_TinyPlanLLM(),
        )
        self.assertEqual(mode, "live_retry")
        self.assertFalse(generation_log["degraded"])
        self.assertEqual(generation_log["final_mode"], "live_retry")
        self.assertEqual(len(generation_log["attempts"]), 4)
        self.assertGreaterEqual(len(repaired_plan["turns"]), 28)
        thread_counts: dict[str, int] = {}
        session_map = {item["session_id"]: item for item in repaired_plan["sessions"]}
        for turn in repaired_plan["turns"]:
            session = session_map[turn["session_id"]]
            if session["source_type"] == "thread":
                thread_counts[session["source_ref"]] = thread_counts.get(session["source_ref"], 0) + 1
        self.assertGreaterEqual(max(thread_counts.values()), 5)
        self.assertEqual(generation_log["attempts"][1]["mode"], "live_insufficient")
        self.assertEqual(generation_log["attempts"][1]["stage"], "plan_live_attempt_1")
        self.assertEqual(generation_log["attempts"][2]["mode"], "live_retry")
        self.assertEqual(generation_log["attempts"][2]["stage"], "plan_live_attempt_2")
        self.assertEqual(generation_log["attempts"][3]["stage"], "repair")

    def test_conversation_plan_logs_retry_insufficient_before_fallback_repair(self) -> None:
        hard_seed = {
            **CASE_SEED,
            "difficulty": "hard",
            "complexity_profile": build_complexity_profile("hard"),
        }
        world = generate_case_world(hard_seed)
        characters = generate_characters(world)
        tiny_plan = _fallback_conversation_plan(world, characters)
        tiny_plan["turns"] = tiny_plan["turns"][:21]
        for session in tiny_plan["sessions"]:
            session["planned_turn_count"] = sum(1 for turn in tiny_plan["turns"] if turn["session_id"] == session["session_id"])

        class _StillTinyPlanLLM:
            def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
                return tiny_plan

        repaired_plan, mode, generation_log = generate_conversation_plan_with_mode(
            world,
            characters,
            llm_client=_StillTinyPlanLLM(),
        )
        self.assertEqual(mode, "fallback_repaired")
        self.assertTrue(generation_log["degraded"])
        self.assertEqual(generation_log["attempts"][1]["mode"], "live_insufficient")
        self.assertEqual(generation_log["attempts"][2]["mode"], "retry_insufficient")
        self.assertEqual(generation_log["attempts"][-1]["stage"], "repair")
        self.assertGreaterEqual(len(repaired_plan["turns"]), 28)

    def test_conversation_plan_logs_explicit_fallback_when_live_output_is_invalid(self) -> None:
        hard_seed = {
            **CASE_SEED,
            "difficulty": "hard",
            "complexity_profile": build_complexity_profile("hard"),
        }
        world = generate_case_world(hard_seed)
        characters = generate_characters(world)
        tiny_plan = _fallback_conversation_plan(world, characters)
        tiny_plan["turns"] = tiny_plan["turns"][:8]
        tiny_plan["sessions"] = tiny_plan["sessions"][:2]

        class _InvalidPlanLLM:
            def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
                return tiny_plan

        repaired_plan, mode, generation_log = generate_conversation_plan_with_mode(
            world,
            characters,
            llm_client=_InvalidPlanLLM(),
        )
        self.assertEqual(mode, "fallback_repaired")
        self.assertTrue(generation_log["degraded"])
        self.assertEqual(generation_log["final_mode"], "fallback_repaired")
        self.assertEqual(generation_log["attempts"][1]["mode"], "live_invalid")
        self.assertEqual(generation_log["attempts"][-1]["stage"], "repair")
        self.assertGreaterEqual(len(repaired_plan["turns"]), 28)

    def test_case_world_pads_live_departments_and_topics_to_hard_targets(self) -> None:
        hard_seed = {
            **CASE_SEED,
            "difficulty": "hard",
            "complexity_profile": build_complexity_profile("hard"),
        }
        world = generate_case_world(
            hard_seed,
            llm_client=_EnglishLLM(
                {
                    "title": "高复杂度发布协调",
                    "company_type": "企业软件平台",
                    "departments": ["产品", "研发", "SRE", "安全", "销售"],
                    "main_goal": "围绕六月窗口形成统一口径",
                    "organization_background": "这是一个需要多团队协调的企业发布案例。",
                    "external_pressure": "客户和管理层都在同步预期。",
                    "stakeholders": ["产品需要统一口径。"],
                    "conflict_axes": ["是否先承诺上线日期。"],
                    "hidden_constraints": ["迁移窗口尚未锁定。"],
                    "reversal_points": ["乐观日期会被收紧。"],
                    "selected_topics": [
                        {
                            "topic_key": "release_window",
                            "topic_title": "发布时间口径",
                            "desired_event_types": ["conclusion_event"],
                            "state_transitions": ["先给乐观目标。"],
                            "turn_templates": [
                                {
                                    "session_id": "session_main_chat",
                                    "speaker_department": "产品",
                                    "turn_purpose": "提出目标",
                                    "supports_event_types": ["conclusion_event"],
                                    "state_transition": "形成初始目标",
                                    "semantic_payload_template": "先按六月上旬推进。",
                                }
                            ],
                        }
                    ],
                }
            ),
        )
        self.assertEqual(world["difficulty"], "hard")
        self.assertEqual(len(world["departments"]), 10)
        self.assertIn("站点可靠性工程", world["departments"])
        self.assertGreaterEqual(len(world["selected_topics"]), 5)

    def test_story_falls_back_when_live_output_is_not_chinese(self) -> None:
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(case_world)
        story = generate_story(
            case_world,
            characters,
            llm_client=_EnglishLLM(
                {
                    "case_id": CASE_SPEC["case_id"],
                    "task_id": CASE_SPEC["task_id"],
                    "title": "English title",
                    "background": "English background",
                    "business_pressure": "English pressure",
                    "project_goal": "English goal",
                    "initial_assumption": "English assumption",
                    "main_conflicts": ["English conflict"],
                    "in_scope": ["English scope"],
                    "out_of_scope": ["English out of scope"],
                }
            ),
        )
        self.assertIn(case_world["company_type"], story["background"])
        self.assertIn("团队", story["initial_assumption"])

    def test_characters_fall_back_when_live_output_is_not_chinese(self) -> None:
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(
            case_world,
            llm_client=_EnglishLLM(
                {
                    "case_id": CASE_SPEC["case_id"],
                    "characters": [
                        {
                            "person_id": "product_01",
                            "name": "Alice",
                            "department": "Product",
                            "role": "PM",
                            "responsibility": "Owns scope",
                            "communication_style": "Calm",
                            "conflict_bias": "Pushes early commitment",
                        }
                    ]
                    * 6,
                }
            ),
        )
        self.assertGreaterEqual(len(characters["characters"]), 6)
        self.assertTrue(all(any("\u4e00" <= ch <= "\u9fff" for ch in item["name"]) for item in characters["characters"]))

    def test_timeline_falls_back_when_live_output_is_not_chinese(self) -> None:
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(case_world)
        story = generate_story(case_world, characters)
        timeline = generate_timeline(
            case_world,
            story,
            characters,
            llm_client=_EnglishLLM(
                {
                    "case_id": CASE_SPEC["case_id"],
                    "timeline": [
                        {
                            "timeline_id": f"tl_{index:03d}",
                            "time_order": index,
                            "event_type": "event",
                            "description": "English description",
                            "actor_refs": [characters["characters"][0]["person_id"]],
                            "affected_topic": "English topic",
                            "state_effect": "English effect",
                            "should_surface_in_message": True,
                        }
                        for index in range(1, 7)
                    ],
                }
            ),
        )
        self.assertEqual(len(timeline["timeline"]), 6)
        self.assertTrue(all(any("\u4e00" <= ch <= "\u9fff" for ch in event["description"]) for event in timeline["timeline"]))


if __name__ == "__main__":
    unittest.main()
