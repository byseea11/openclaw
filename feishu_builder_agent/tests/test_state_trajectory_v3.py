from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.state_trajectory_generator import generate_state_trajectory
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class StateTrajectoryTests(unittest.TestCase):
    def test_static_memory_stale_state_generates_state_track(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="easy",
            seed=31,
            selected_failure_modes=["static_memory_stale_state"],
            primary_failure_mode="static_memory_stale_state",
        )
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        case_world = generate_case_world(case_spec, blueprint, layout)
        characters = generate_characters(layout, case_world)
        trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
        owner_transitions = [row for row in trajectory["transitions"] if row["state_field"] == "owner"]
        self.assertGreaterEqual(len(owner_transitions), 3)
        self.assertTrue(any(row["is_final_current_state"] for row in owner_transitions))


if __name__ == "__main__":
    unittest.main()
