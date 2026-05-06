from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.conversation_plan_generator import generate_conversation_plan
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.state_trajectory_generator import generate_state_trajectory
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class ConversationPlanTests(unittest.TestCase):
    def test_conversation_plan_turns_include_v3_metadata(self) -> None:
        case_spec = generate_case_spec(scenario_profile="enterprise_task_memory", difficulty="medium", seed=61)
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        case_world = generate_case_world(case_spec, blueprint, layout)
        characters = generate_characters(layout, case_world)
        trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
        plan = generate_conversation_plan(case_world, characters, blueprint, trajectory)
        self.assertTrue(plan["turns"])
        row = plan["turns"][0]
        self.assertTrue(row["benchmark_role"])
        self.assertTrue(row["memory_failure_mode"])
        self.assertTrue(row["memory_trap"])
        self.assertTrue(row["expected_openclaw_memory_risk"])
        self.assertTrue(row["task_wiki_expected_handling"])


if __name__ == "__main__":
    unittest.main()
