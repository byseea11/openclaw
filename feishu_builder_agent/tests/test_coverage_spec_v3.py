from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.coverage_spec_generator import generate_coverage_spec
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.state_trajectory_generator import generate_state_trajectory
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class CoverageSpecTests(unittest.TestCase):
    def test_coverage_spec_contains_trap_coverage(self) -> None:
        case_spec = generate_case_spec(scenario_profile="enterprise_task_memory", difficulty="medium", seed=41)
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        case_world = generate_case_world(case_spec, blueprint, layout)
        characters = generate_characters(layout, case_world)
        trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
        coverage = generate_coverage_spec(blueprint, trajectory)
        self.assertTrue(coverage["trap_coverage"]["required_traps"])
        self.assertTrue(coverage["required_benchmark_roles"])


if __name__ == "__main__":
    unittest.main()
