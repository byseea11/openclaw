from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.case_profiles import sample_case_seed_components, sample_topic_templates
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.command_plan_generator import generate_command_plan
from feishu_builder_agent.conversation_plan_generator import generate_conversation_plan
from feishu_builder_agent.plan_mapper import build_execution_plan, build_execution_plan_from_command_plan
from feishu_builder_agent.story_generator import generate_story
from feishu_builder_agent.target_gold_generator import generate_target_state
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


CASE_SEED = {
    **CASE_SPEC,
    "scenario_profile": "enterprise_release_coordination",
    **sample_case_seed_components(
        task_id=CASE_SPEC["task_id"],
        difficulty=CASE_SPEC["difficulty"],
        seed=CASE_SPEC["seed"],
        profile_id="enterprise_release_coordination",
        department_hints=CASE_SPEC["departments"],
        title_hint=CASE_SPEC["title"],
        main_goal_hint=CASE_SPEC["main_goal"],
        company_type_hint=CASE_SPEC["company_type"],
    ),
}


class MapperTests(unittest.TestCase):
    def test_mapper_is_deterministic(self) -> None:
        story = generate_story(CASE_SPEC)
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(CASE_SPEC, CASE_SEED, case_world, story)
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
        case_world = generate_case_world(CASE_SEED)
        characters = generate_characters(CASE_SPEC, CASE_SEED, case_world, story)
        conversation_plan = generate_conversation_plan(CASE_SEED, case_world, characters)
        expected_topics = {
            item["topic_key"]
            for item in sample_topic_templates(
                seed=CASE_SEED["seed"],
                difficulty=CASE_SEED["difficulty"],
                profile_id=CASE_SEED["scenario_profile"],
            )
        }
        self.assertEqual({item["topic_key"] for item in conversation_plan["topic_registry"]}, expected_topics)
        self.assertEqual(
            {item["session_id"] for item in conversation_plan["sessions"]},
            {"session_main_chat", "session_launch_window_thread", "session_customer_sync_chat"},
        )
        target_state = generate_target_state(conversation_plan)
        command_plan = generate_command_plan(CASE_SEED, conversation_plan, characters, target_state=target_state)
        plan = build_execution_plan_from_command_plan(command_plan)
        create_chat_actions = [action for action in plan["actions"] if action["action_type"] == "create_chat"]
        thread_actions = [action for action in plan["actions"] if action["action_type"] == "reply_in_thread"]
        self.assertGreaterEqual(len(create_chat_actions), 2)
        self.assertGreaterEqual(len(thread_actions), 1)
        self.assertTrue(any(action["action_type"] == "fetch_thread_messages" for action in plan["actions"]))
        self.assertTrue(any(action["action_type"] == "fetch_chat_messages" for action in plan["actions"]))


if __name__ == "__main__":
    unittest.main()
