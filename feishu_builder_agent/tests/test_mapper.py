from __future__ import annotations

import unittest

from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.plan_mapper import build_execution_plan
from feishu_builder_agent.story_generator import generate_story
from feishu_builder_agent.timeline_planner import generate_timeline


CASE_SPEC = {
    "case_id": "case_release",
    "task_id": "REQ-231",
    "title": "企业级 SSO 上线推进",
    "company_type": "企业级 SaaS",
    "departments": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
    "main_goal": "评估并推动五月上旬完成上线",
    "difficulty": "medium",
    "seed": 7,
}


class MapperTests(unittest.TestCase):
    def test_mapper_is_deterministic(self) -> None:
        story = generate_story(CASE_SPEC)
        characters = generate_characters(CASE_SPEC, story)
        timeline = generate_timeline(CASE_SPEC, story, characters)
        plan_a = build_execution_plan(story, characters, timeline)
        plan_b = build_execution_plan(story, characters, timeline)
        self.assertEqual(plan_a, plan_b)
        self.assertEqual(plan_a["operator_identity"], "user")
        self.assertEqual(plan_a["delivery_mode"], "prefixed_single_operator")
        message_actions = [action for action in plan_a["actions"] if action["action_type"] in {"send_message", "reply_in_thread"}]
        self.assertTrue(message_actions)
        self.assertTrue(all("【" in action["params"]["content_text"] for action in message_actions))
        self.assertTrue(any("目标" in action["params"]["content_text"] or "日期" in action["params"]["content_text"] for action in message_actions))


if __name__ == "__main__":
    unittest.main()
