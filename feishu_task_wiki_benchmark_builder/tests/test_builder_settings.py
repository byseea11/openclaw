from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.builder_settings import (
    load_builder_settings,
    resolve_default_difficulty,
    resolve_difficulty_settings,
    resolve_family_constraints,
    resolve_prompt_slots,
)
from feishu_task_wiki_benchmark_builder.prompt_settings_renderer import render_prompt_settings_summary


class BuilderSettingsTests(unittest.TestCase):
    def test_builder_settings_loads_all_formal_profiles(self) -> None:
        settings = load_builder_settings()
        self.assertEqual(settings["default_difficulty"], "hard")
        self.assertIn("difficulty_profiles", settings)
        self.assertIn("family_constraints", settings)

    def test_medium_profile_exposes_scale_controls(self) -> None:
        profile = resolve_difficulty_settings("medium")
        self.assertEqual(profile["department_count"], 12)
        self.assertEqual(profile["character_count_min"], 16)
        self.assertEqual(profile["character_count_max"], 22)
        self.assertEqual(profile["recommended_actor_count"], 18)
        self.assertEqual(profile["recommended_department_count"], 12)
        self.assertEqual(profile["recommended_session_count"], 6)

    def test_default_difficulty_resolves_from_yml(self) -> None:
        self.assertEqual(resolve_default_difficulty(), "hard")

    def test_family_constraints_cover_every_formal_family(self) -> None:
        anti = resolve_family_constraints("anti_interference")
        self.assertEqual(anti["min_shared_actors"], 3)
        self.assertEqual(anti["min_interference_context_blocks"], 4)

        contradiction = resolve_family_constraints("contradiction_update")
        self.assertEqual(contradiction["min_state_tracks"], 4)
        self.assertEqual(contradiction["min_stale_states"], 3)

        evidence = resolve_family_constraints("evidence_dependency_reasoning")
        self.assertEqual(evidence["min_dependency_hops"], 3)
        self.assertEqual(evidence["min_cross_source_updates"], 2)

    def test_resolved_prompt_slots_expose_stage_and_family_contracts(self) -> None:
        slots = resolve_prompt_slots(
            stage="story-plan",
            difficulty="hard",
            family_id="evidence_dependency_reasoning",
        )
        self.assertEqual(slots["difficulty_slots"]["recommended_actor_count"], 28)
        self.assertEqual(slots["difficulty_slots"]["recommended_department_count"], 16)
        self.assertEqual(slots["stage_slots"]["recommended_session_count"], 8)
        self.assertEqual(slots["family_numeric_slots"]["min_dependency_hops"], 3)
        self.assertEqual(slots["family_numeric_slots"]["min_cross_source_updates"], 2)

    def test_resolved_prompt_slots_cover_phase1_fine_grained_stages(self) -> None:
        expected_stages = [
            "spec-generation",
            "task-actor-layout",
            "case-world",
            "characters",
            "state-trajectory",
            "coverage-spec",
            "story-beats",
            "conversation-plan",
            "command-plan",
            "execute",
            "collect",
            "pre-annotation-validate",
        ]
        for stage in expected_stages:
            with self.subTest(stage=stage):
                slots = resolve_prompt_slots(
                    stage=stage,
                    difficulty="hard",
                    family_id="anti_interference",
                )
                self.assertEqual(slots["difficulty_slots"]["recommended_actor_count"], 28)
                self.assertEqual(slots["stage_slots"]["recommended_session_count"], 8)
                self.assertEqual(slots["family_numeric_slots"]["min_shared_actors"], 3)

        command_slots = resolve_prompt_slots(
            stage="command-plan",
            difficulty="hard",
            family_id="anti_interference",
        )
        self.assertIn("send_message", command_slots["stage_slots"]["required_action_types"])
        self.assertTrue(command_slots["stage_slots"]["require_lark_cli_command_preview"])

        collect_slots = resolve_prompt_slots(
            stage="collect",
            difficulty="hard",
            family_id="anti_interference",
        )
        self.assertTrue(collect_slots["stage_slots"]["real_fetch_only"])

    def test_story_plan_settings_summary_matches_settings_values(self) -> None:
        summary = render_prompt_settings_summary(
            stage="story-plan",
            difficulty="hard",
            family_id="evidence_dependency_reasoning",
        )
        self.assertIn("Skill Runtime Constraints", summary)
        self.assertIn("Resolved Slot Contract", summary)
        self.assertIn("\"recommended_actor_count\": 28", summary)
        self.assertIn("\"recommended_department_count\": 16", summary)
        self.assertIn("\"recommended_session_count\": 8", summary)
        self.assertIn("\"family_numeric_slots\"", summary)


if __name__ == "__main__":
    unittest.main()
