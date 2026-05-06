from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world, generate_case_world_with_mode
from feishu_builder_agent.character_generator import generate_characters, generate_characters_with_mode
from feishu_builder_agent.conversation_plan_generator import (
    generate_conversation_plan,
    generate_conversation_plan_with_mode,
)
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint_with_mode
from feishu_builder_agent.spec_generator import generate_case_spec_with_mode
from feishu_builder_agent.state_trajectory_generator import generate_state_trajectory
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class _StaticJsonClient:
    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str):
        del system_prompt, user_prompt
        return self.payload


class LiveLlmGenerationTests(unittest.TestCase):
    def test_spec_generation_uses_live_llm_when_client_is_available(self) -> None:
        client = _StaticJsonClient(
            {
                "case_id": "case_feishu_001_v3",
                "task_id": "FEISHU-1",
                "selected_failure_modes": ["static_memory_stale_state"],
                "primary_failure_mode": "static_memory_stale_state",
            }
        )
        payload, mode = generate_case_spec_with_mode(
            scenario_profile="enterprise_task_memory",
            difficulty="medium",
            seed=999,
            user_hint="",
            llm_client=client,
        )
        self.assertEqual(mode, "llm")
        self.assertEqual(payload["task_id"], "FEISHU-999")
        self.assertEqual(payload["case_id"], "case_feishu_999_v3")

    def test_memory_failure_blueprint_uses_live_llm_when_client_is_available(self) -> None:
        case_spec, _ = generate_case_spec_with_mode(
            scenario_profile="enterprise_task_memory",
            difficulty="easy",
            seed=123,
            user_hint="",
            selected_failure_modes=["unverifiable_summary_claim"],
            primary_failure_mode="unverifiable_summary_claim",
        )
        client = _StaticJsonClient(
            {
                "traps": [
                    {
                        "trap_id": "trap_live_claim_001",
                        "failure_mode": "unverifiable_summary_claim",
                        "target_task_id": case_spec["task_id"],
                        "trap_mechanism": "把模糊说法和明确事实混在一起，诱发无证据总结。",
                        "common": {
                            "distractor_tasks": ["FEISHU-888"],
                            "shared_actors": ["finance_partner_1"],
                            "probe_queries": [f"现在说 {case_spec['task_id']} 被财务问题阻塞，这是谁明确说的？"],
                            "metric_targets": ["unsupported_claim_rate"],
                            "landing_requirements": {
                                "required_benchmark_roles": ["evidence_anchor_turn", "ambiguous_claim_turn"],
                                "required_state_fields": ["blocker"],
                                "required_evidence_messages_min": 2,
                                "required_probe_queries_min": 1,
                            },
                        },
                        "typed_payload": {
                            "target_claim": f"{case_spec['task_id']} 当前受财务问题阻塞",
                            "evidence_distribution": {
                                "verified_fact_turns": 1,
                                "ambiguous_turns": 1,
                                "hearsay_turns": 1,
                                "weak_commitment_turns": 0,
                                "no_event_turns": 1,
                            },
                        },
                        "expected_openclaw_failure": "Memory.md 可能把猜测写成确定事实。",
                        "expected_task_wiki_success": "Task Wiki 应回到证据层区分 verified 和 needs_review。",
                    }
                ]
            }
        )
        blueprint, mode = generate_memory_failure_blueprint_with_mode(case_spec, llm_client=client)
        self.assertEqual(mode, "llm")
        self.assertEqual(blueprint["traps"][0]["trap_id"], "trap_live_claim_001")

    def test_case_world_characters_and_conversation_can_use_live_llm(self) -> None:
        case_spec, _ = generate_case_spec_with_mode(
            scenario_profile="enterprise_task_memory",
            difficulty="medium",
            seed=456,
            user_hint="",
        )
        blueprint, _ = generate_memory_failure_blueprint_with_mode(case_spec)
        layout = generate_task_actor_layout(blueprint)

        world_scaffold = generate_case_world(case_spec, blueprint, layout)
        world_payload = dict(world_scaffold)
        world_payload["title"] = f"{case_spec['task_id']} 企业协作回放"
        world_payload["business_context"] = "这是一个跨产品、研发、运维、安全和财务协调的真实任务推进场景。"
        world_client = _StaticJsonClient(world_payload)
        case_world, world_mode = generate_case_world_with_mode(case_spec, blueprint, layout, llm_client=world_client)
        self.assertEqual(world_mode, "llm")

        characters_scaffold = generate_characters(layout, case_world)
        live_character_rows = []
        for row in characters_scaffold["characters"]:
            live_character_rows.append(
                {
                    "person_id": row["person_id"],
                    "name": f"{row['name']}-LLM",
                    "profile": f"{row['role']}，由 live LLM 生成更自然的角色画像。",
                    "simulated_open_id": "should_not_override",
                    "department": "should_not_override",
                }
            )
        characters_client = _StaticJsonClient({"case_id": characters_scaffold["case_id"], "characters": live_character_rows})
        characters, characters_mode = generate_characters_with_mode(layout, case_world, llm_client=characters_client)
        self.assertEqual(characters_mode, "llm")
        self.assertTrue(characters["characters"][0]["name"].endswith("-LLM"))
        self.assertTrue(characters["characters"][0]["simulated_open_id"].startswith("ou_sim_"))
        self.assertNotEqual(characters["characters"][0]["department"], "should_not_override")

        trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
        conversation_scaffold = generate_conversation_plan(case_world, characters, blueprint, trajectory)
        conversation_client = _StaticJsonClient(conversation_scaffold)
        conversation, conversation_mode = generate_conversation_plan_with_mode(
            case_world,
            characters,
            blueprint,
            trajectory,
            llm_client=conversation_client,
        )
        self.assertEqual(conversation_mode, "llm")
        self.assertTrue(conversation["turns"])


if __name__ == "__main__":
    unittest.main()
