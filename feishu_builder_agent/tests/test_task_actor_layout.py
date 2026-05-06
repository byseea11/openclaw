from __future__ import annotations

import unittest

from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class TaskActorLayoutTests(unittest.TestCase):
    def test_personal_memory_pollution_generates_distractor_tasks_and_shared_actors(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="easy",
            seed=21,
            selected_failure_modes=["personal_memory_pollution"],
            primary_failure_mode="personal_memory_pollution",
        )
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        self.assertTrue(layout["distractor_tasks"])
        self.assertTrue(layout["shared_actor_slots"])
        self.assertTrue(layout["pollution_dimensions"])


if __name__ == "__main__":
    unittest.main()
