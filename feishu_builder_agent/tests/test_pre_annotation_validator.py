from __future__ import annotations

import unittest

from feishu_builder_agent.case_world_generator import generate_case_world
from feishu_builder_agent.character_generator import generate_characters
from feishu_builder_agent.collected_message_builder import build_collected_messages
from feishu_builder_agent.command_plan_generator import generate_command_plan
from feishu_builder_agent.conversation_plan_generator import generate_conversation_plan
from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint
from feishu_builder_agent.plan_mapper import build_execution_plan_from_command_plan
from feishu_builder_agent.pre_annotation_validator import build_pre_annotation_validation_report
from feishu_builder_agent.spec_generator import generate_case_spec
from feishu_builder_agent.state_trajectory_generator import generate_state_trajectory
from feishu_builder_agent.task_actor_layout_generator import generate_task_actor_layout


class PreAnnotationValidatorTests(unittest.TestCase):
    def test_validator_audits_trap_landing(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="easy",
            seed=71,
            selected_failure_modes=["static_memory_stale_state"],
            primary_failure_mode="static_memory_stale_state",
        )
        blueprint = generate_memory_failure_blueprint(case_spec)
        layout = generate_task_actor_layout(blueprint)
        case_world = generate_case_world(case_spec, blueprint, layout)
        characters = generate_characters(layout, case_world)
        trajectory = generate_state_trajectory(blueprint, layout, case_world, characters)
        conversation_plan = generate_conversation_plan(case_world, characters, blueprint, trajectory)
        command_plan = generate_command_plan(case_spec, conversation_plan, characters)
        execution_plan = build_execution_plan_from_command_plan(command_plan)
        execution_result = {
            "case_id": case_spec["case_id"],
            "status": "success",
            "operator_identity": "user",
            "delivery_mode": "prefixed_single_operator",
            "created_resources": {
                row["output_ref"]: {
                    "message_id": f"om_{row['step_id']}",
                    "thread_id": f"omt_{row['step_id']}",
                    "chat_id": f"oc_{row['chat_ref']}",
                }
                for row in command_plan
                if row["action_type"] in {"send_message", "reply_in_thread"} and row["output_ref"]
            },
            "thread_id_to_chat_id": {},
            "action_status": [],
            "preflight": {},
        }
        fetch_records = [
            {
                "response": {
                    "data": {
                        "messages": [
                            {
                                "message_id": f"om_{row['step_id']}",
                                "content": row["params"]["content_text"],
                                "sender": {"id": "ou_real", "name": "真实用户", "sender_type": "user"},
                            }
                        ]
                    }
                }
            }
            for row in command_plan
            if row["action_type"] in {"send_message", "reply_in_thread"}
        ]
        collected_messages = build_collected_messages(
            characters,
            command_plan,
            execution_plan,
            execution_result,
            fetch_records,
        )
        report = build_pre_annotation_validation_report(
            case_spec=case_spec,
            memory_failure_blueprint=blueprint,
            conversation_plan=conversation_plan,
            collected_messages=collected_messages,
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["traps"][0]["landed"])


if __name__ == "__main__":
    unittest.main()
