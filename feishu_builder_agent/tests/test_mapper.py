from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.conversation_plan_generator import generate_conversation_plan
from feishu_builder_agent.message_realizer import realize_messages
from feishu_builder_agent.plan_mapper import build_execution_plan, build_execution_plan_from_realized_messages
from feishu_builder_agent.story_generator import generate_story
from feishu_builder_agent.timeline_planner import generate_timeline
from feishu_builder_agent.utterance_generator import generate_utterance_plan


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

    def test_v2_mapper_builds_multi_session_execution_plan(self) -> None:
        story = generate_story(CASE_SPEC)
        characters = generate_characters(CASE_SPEC, story)
        case_world = generate_case_world(
            {
                **CASE_SPEC,
                "domain": "enterprise_product_launch",
                "complexity_profile": {
                    "session_count_target": 3,
                    "source_session_count_target": 3,
                    "message_count_target": 18,
                    "topic_count_target": 3,
                    "thread_reply_depth_target": 3,
                    "state_transition_target": 4,
                    "supersession_target": 1,
                    "cross_source_revision_target": 1,
                    "event_family_target": 5,
                },
            }
        )
        conversation_plan = generate_conversation_plan(
            {
                **CASE_SPEC,
                "domain": "enterprise_product_launch",
                "complexity_profile": {
                    "session_count_target": 3,
                    "source_session_count_target": 3,
                    "message_count_target": 18,
                    "topic_count_target": 3,
                    "thread_reply_depth_target": 3,
                    "state_transition_target": 4,
                    "supersession_target": 1,
                    "cross_source_revision_target": 1,
                    "event_family_target": 5,
                },
            },
            case_world,
            characters,
        )
        utterance_plan = generate_utterance_plan(conversation_plan, characters)
        realized_messages = realize_messages(utterance_plan, characters)
        plan = build_execution_plan_from_realized_messages(characters, conversation_plan, realized_messages)
        create_chat_actions = [action for action in plan["actions"] if action["action_type"] == "create_chat"]
        thread_actions = [action for action in plan["actions"] if action["action_type"] == "reply_in_thread"]
        self.assertGreaterEqual(len(create_chat_actions), 2)
        self.assertGreaterEqual(len(thread_actions), 1)
        self.assertTrue(any(action["action_type"] == "fetch_thread_messages" for action in plan["actions"]))
        self.assertTrue(any(action["action_type"] == "fetch_chat_messages" for action in plan["actions"]))


if __name__ == "__main__":
    unittest.main()
