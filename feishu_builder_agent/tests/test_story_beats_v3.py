from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.story_beats_generator import generate_story_beats
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class StoryBeatsTests(unittest.TestCase):
    def test_each_beat_maps_back_to_a_trap(self) -> None:
        case_spec = generate_case_spec(scenario_profile="enterprise_task_memory", difficulty="medium", seed=51)
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        case_world = generate_case_world(case_spec, blueprint, layout)
        beats = generate_story_beats(blueprint, case_world)
        trap_ids = {trap["trap_id"] for trap in blueprint["traps"]}
        self.assertTrue(beats["beats"])
        self.assertTrue(all(beat["trap_id"] in trap_ids for beat in beats["beats"]))


if __name__ == "__main__":
    unittest.main()
