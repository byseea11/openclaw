from __future__ import annotations

import unittest
from typing import Any

from feishu_builder_agent.case_profiles import sample_case_seed_components
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.story_generator import generate_story
from feishu_builder_agent.timeline_planner import generate_timeline


CASE_SPEC = {
    "case_id": "case_live_language",
    "task_id": "REQ-998",
    "title": "飞书协作上线口径收敛",
    "company_type": "企业级 SaaS",
    "departments": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
    "main_goal": "围绕五月初上线目标形成统一口径",
    "difficulty": "medium",
    "seed": 9,
}


CASE_SEED = {
    **CASE_SPEC,
    "scenario_profile": "enterprise_release_coordination",
    **sample_case_seed_components(
        task_id=CASE_SPEC["task_id"],
        difficulty=CASE_SPEC["difficulty"],
        seed=CASE_SPEC["seed"],
        profile_id="enterprise_release_coordination",
        department_hints=CASE_SPEC["departments"],
        title_hint=CASE_SPEC["title"],
        main_goal_hint=CASE_SPEC["main_goal"],
        company_type_hint=CASE_SPEC["company_type"],
    ),
}


class _EnglishLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return dict(self.payload)


class LiveLanguageFallbackTests(unittest.TestCase):
    def test_story_falls_back_when_live_output_is_not_chinese(self) -> None:
        story = generate_story(
            CASE_SPEC,
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
        self.assertIn("企业级", story["background"])
        self.assertIn("团队", story["initial_assumption"])

    def test_characters_fall_back_when_live_output_is_not_chinese(self) -> None:
        story = generate_story(CASE_SPEC)
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(
            CASE_SPEC,
            CASE_SEED,
            case_world,
            story,
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
        story = generate_story(CASE_SPEC)
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(CASE_SPEC, CASE_SEED, case_world, story)
        timeline = generate_timeline(
            CASE_SPEC,
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
