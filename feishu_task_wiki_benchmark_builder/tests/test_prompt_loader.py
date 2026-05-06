from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.prompt import (
    build_case_context_system_prompt,
    build_story_plan_system_prompt,
)
from feishu_task_wiki_benchmark_builder.prompt_loader import list_stage_prompt_sources


class PromptLoaderTests(unittest.TestCase):
    def test_case_context_prompt_assembles_multiple_skill_sources(self) -> None:
        prompt = build_case_context_system_prompt(difficulty="hard")
        self.assertIn("family-selection.md", prompt)
        self.assertIn("capability-brief.md", prompt)
        self.assertIn("case-world.md", prompt)
        self.assertIn("anti-interference-context.md", prompt)
        self.assertIn("contradiction-update-context.md", prompt)
        self.assertIn("evidence-dependency-context.md", prompt)
        self.assertIn("职责", prompt)
        self.assertIn("硬规则", prompt)
        self.assertIn("禁止", prompt)
        self.assertIn("JSON 示例", prompt)
        self.assertIn("story_id", prompt)
        self.assertIn("message_beats", prompt)
        self.assertIn("planned_probe_queries", prompt)
        self.assertIn("Builder Settings Summary", prompt)
        self.assertIn("department_count", prompt)
        self.assertIn("character_count_min/max", prompt)
        self.assertIn("session_blueprint", prompt)
        self.assertIn("main_chat, handoff_thread, customer_sync_chat, risk_review_thread, exec_sync_chat", prompt)

    def test_story_plan_prompt_assembles_story_plan_skill(self) -> None:
        prompt = build_story_plan_system_prompt(
            family_id="evidence_dependency_reasoning",
            difficulty="medium",
        )
        self.assertIn("story-plan.md", prompt)
        self.assertIn("`task`", prompt)
        self.assertIn("唯一正式 task", prompt)
        self.assertIn("planned_probe_queries", prompt)
        self.assertIn(
            "## Skill Source: feishu_task_wiki_benchmark_builder/skills/evidence-dependency-context.md",
            prompt,
        )
        self.assertNotIn(
            "## Skill Source: feishu_task_wiki_benchmark_builder/skills/anti-interference-context.md",
            prompt,
        )
        self.assertIn("JSON 示例", prompt)
        self.assertIn("dependency_context_blocks", prompt)
        self.assertIn("verified_anchor", prompt)
        self.assertIn("hearsay_channel", prompt)
        self.assertIn("ambiguous_channel", prompt)
        self.assertIn("downstream_impact", prompt)
        self.assertIn("依据来自谁、哪条消息", prompt)
        self.assertIn("min_dependency_hops", prompt)
        self.assertIn("min_cross_source_updates", prompt)
        self.assertIn("required_evidence_roles", prompt)
        self.assertIn("character_count_min/max", prompt)

    def test_story_plan_prompt_carries_hard_case_signals_for_all_families(self) -> None:
        anti_prompt = build_story_plan_system_prompt(family_id="anti_interference", difficulty="medium")
        self.assertIn("interference_context_blocks", anti_prompt)
        self.assertIn("shared_actor_noise", anti_prompt)
        self.assertIn("这不是目标任务 owner 变更", anti_prompt)
        self.assertIn("min_shared_actors", anti_prompt)

        contradiction_prompt = build_story_plan_system_prompt(
            family_id="contradiction_update",
            difficulty="medium",
        )
        self.assertIn("revision_context_blocks", contradiction_prompt)
        self.assertIn("supersession_clues", contradiction_prompt)
        self.assertIn("release_window", contradiction_prompt)
        self.assertIn("min_state_tracks", contradiction_prompt)

        evidence_prompt = build_story_plan_system_prompt(
            family_id="evidence_dependency_reasoning",
            difficulty="medium",
        )
        self.assertIn("dependency_context_blocks", evidence_prompt)
        self.assertIn("verified_anchor", evidence_prompt)
        self.assertIn("hearsay_channel", evidence_prompt)

    def test_stage_prompt_source_list_is_stable(self) -> None:
        self.assertEqual(
            [path.name for path in list_stage_prompt_sources("case-context")],
            [
                "workflow.md",
                "family-selection.md",
                "capability-brief.md",
                "case-world.md",
                "anti-interference-context.md",
                "contradiction-update-context.md",
                "evidence-dependency-context.md",
            ],
        )
        self.assertEqual(
            [path.name for path in list_stage_prompt_sources("story-plan", family_id="anti_interference")],
            ["workflow.md", "story-plan.md", "anti-interference-context.md"],
        )
