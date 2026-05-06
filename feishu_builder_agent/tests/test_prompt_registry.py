from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.prompt_registry import (
    build_case_world_prompts,
    build_conversation_plan_prompts,
    build_character_prompts,
    build_memory_failure_blueprint_prompts,
    build_spec_generation_prompts,
)
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.state_trajectory_generator import generate_state_trajectory
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout
from feishu_builder_agent.conversation_plan_generator import generate_conversation_plan


class PromptRegistryTests(unittest.TestCase):
    def test_spec_generation_prompts_pin_contract_and_requested_modes(self) -> None:
        system_prompt, user_prompt = build_spec_generation_prompts(
            difficulty="hard",
            seed=505160829,
            comparison_target="openclaw_memory_md",
            selected_failure_modes=["static_memory_stale_state", "personal_memory_pollution"],
            primary_failure_mode="static_memory_stale_state",
            user_hint="请优先压测 current-state 相关失败。",
        )
        self.assertIn("case_spec", system_prompt)
        self.assertIn("selected_failure_modes", user_prompt)
        self.assertIn("primary_failure_mode", user_prompt)
        self.assertIn("static_memory_stale_state", user_prompt)
        self.assertIn("personal_memory_pollution", user_prompt)
        self.assertIn("不要输出 title_hint", user_prompt)
        self.assertIn("请优先压测 current-state 相关失败。", user_prompt)

    def test_memory_failure_blueprint_prompts_cover_selected_modes(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="hard",
            seed=101,
            selected_failure_modes=[
                "personal_memory_pollution",
                "static_memory_stale_state",
            ],
            primary_failure_mode="static_memory_stale_state",
        )
        system_prompt, user_prompt = build_memory_failure_blueprint_prompts(case_spec)
        self.assertIn("memory_failure_blueprint", system_prompt)
        self.assertIn("personal_memory_pollution", user_prompt)
        self.assertIn("static_memory_stale_state", user_prompt)

    def test_case_world_and_conversation_prompts_are_built_from_scaffolds(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="medium",
            seed=202,
        )
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        case_world = generate_case_world(case_spec, blueprint, layout)
        characters = generate_characters(layout, case_world)
        trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
        conversation = generate_conversation_plan(case_world, characters, blueprint, trajectory)

        world_system_prompt, world_user_prompt = build_case_world_prompts(case_spec, blueprint, layout, case_world)
        self.assertIn("case_world", world_system_prompt)
        self.assertIn(case_spec["task_id"], world_user_prompt)

        character_system_prompt, character_user_prompt = build_character_prompts(layout, case_world, characters)
        self.assertIn("character", character_system_prompt)
        self.assertIn("simulated_open_id", character_user_prompt)
        self.assertIn("name 和 profile", character_user_prompt)
        self.assertIn(layout["shared_actor_slots"][0]["actor_slot_id"], character_user_prompt)

        conversation_system_prompt, conversation_user_prompt = build_conversation_plan_prompts(
            case_world,
            characters,
            blueprint,
            trajectory,
            conversation,
        )
        self.assertIn("conversation_plan", conversation_system_prompt)
        self.assertIn("benchmark_role", conversation_user_prompt)
        self.assertIn(case_spec["task_id"], conversation_user_prompt)


if __name__ == "__main__":
    unittest.main()
