from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.builder_settings import (
    load_builder_settings,
    resolve_default_difficulty,
    resolve_difficulty_settings,
    resolve_family_constraints,
    resolve_topology_defaults,
)
from feishu_task_wiki_benchmark_builder.prompt_settings_renderer import render_prompt_settings_summary


class BuilderSettingsTests(unittest.TestCase):
    def test_builder_settings_loads_all_formal_profiles(self) -> None:
        settings = load_builder_settings()
        self.assertIn("defaults", settings)
        self.assertIn("difficulty_profiles", settings)
        self.assertIn("family_constraints", settings)
        self.assertIn("topology_defaults", settings)

    def test_medium_profile_exposes_scale_controls(self) -> None:
        profile = resolve_difficulty_settings("medium")
        self.assertEqual(profile["department_count"], 7)
        self.assertEqual(profile["character_count_min"], 8)
        self.assertEqual(profile["character_count_max"], 10)
        self.assertEqual(
            profile["session_blueprint"],
            ["main_chat", "handoff_thread", "customer_sync_chat", "risk_review_thread"],
        )

    def test_default_difficulty_is_loaded_from_builder_settings(self) -> None:
        self.assertEqual(resolve_default_difficulty(), "medium")

    def test_family_constraints_cover_every_formal_family(self) -> None:
        anti = resolve_family_constraints("anti_interference")
        self.assertEqual(anti["min_shared_actors"], 2)
        self.assertIn("shared_actor_noise", anti["required_noise_types"])

        contradiction = resolve_family_constraints("contradiction_update")
        self.assertEqual(contradiction["min_state_tracks"], 3)
        self.assertIn("之前口径作废", contradiction["required_supersession_clues"])

        evidence = resolve_family_constraints("evidence_dependency_reasoning")
        self.assertEqual(evidence["min_dependency_hops"], 2)
        self.assertIn("verified_anchor", evidence["required_evidence_roles"])

    def test_topology_defaults_expose_org_and_side_channel_hints(self) -> None:
        topology = resolve_topology_defaults()
        self.assertIn("产品负责人", topology["shared_actor_slot_suggestions"])
        self.assertIn("供应商依赖", topology["external_context_types"])
        self.assertIn("risk_review_thread", topology["lateral_session_types"])

    def test_story_plan_settings_summary_matches_settings_values(self) -> None:
        summary = render_prompt_settings_summary(
            stage="story-plan",
            difficulty="hard",
            family_id="evidence_dependency_reasoning",
        )
        self.assertIn("department_count`: 9", summary)
        self.assertIn("character_count_min/max`: 10 / 12", summary)
        self.assertIn("main_chat, handoff_thread, customer_sync_chat, risk_review_thread, exec_sync_chat", summary)
        self.assertIn("min_dependency_hops`: 2", summary)
        self.assertIn("min_cross_source_updates`: 1", summary)


if __name__ == "__main__":
    unittest.main()
