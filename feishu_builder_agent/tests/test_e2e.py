from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from feishu_builder_agent.cli import (
    adapt_case,
    compile_case,
    execute_case,
    generate_case_spec_stage,
    generate_case_world_stage,
    generate_characters_stage,
    generate_command_plan_stage,
    generate_conversation_plan_stage,
    generate_gold_stage,
    generate_target_gold_stage,
    validate_case_stage,
)
from feishu_builder_agent.build_report import build_case_report
from feishu_builder_agent.collector import utc_now_iso
from feishu_builder_agent.io_utils import write_json, write_jsonl
from feishu_builder_agent.schemas import ValidationError


class EndToEndTests(unittest.TestCase):
    def test_generate_case_spec_stage_creates_minimal_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = generate_case_spec_stage(
                dataset_root=root / "dataset",
                scenario_profile="enterprise_release_coordination",
                difficulty="medium",
                seed=11,
                user_hint="需要重点覆盖安全、研发和客户同步压力",
            )
            case_spec = result["case_spec"]
            self.assertEqual(case_spec["difficulty"], "medium")
            self.assertEqual(case_spec["seed"], 11)
            self.assertEqual(case_spec["title"], "")
            self.assertEqual(case_spec["company_type"], "")
            self.assertEqual(case_spec["main_goal"], "")
            self.assertTrue(case_spec["department_hints"])
            self.assertTrue((Path(result["case_dir"]) / "case_spec.json").exists())

    def test_case_world_stage_generates_title_goal_and_departments_from_minimal_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_spec = {
                "case_id": "case_spec_first",
                "task_id": "REQ-500",
                "title": "",
                "company_type": "",
                "department_hints": ["法务", "数据"],
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "",
                "main_goal_hint": "",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 11,
            }
            case_spec_path = root / "case_spec.json"
            write_json(case_spec_path, case_spec)
            result = generate_case_world_stage(case_spec_path=case_spec_path, dataset_root=root / "dataset")
            case_seed = result["case_seed"]
            case_world = result["case_world"]
            self.assertFalse(case_seed["title_hint"])
            self.assertFalse(case_seed["main_goal_hint"])
            self.assertEqual(case_seed["department_hints"], ["法务", "数据"])
            self.assertTrue(case_world["title"])
            self.assertTrue(case_world["main_goal"])
            self.assertTrue(case_world["company_type"])
            self.assertGreaterEqual(len(case_world["departments"]), 6)
            self.assertIn("法务", case_world["departments"])
            self.assertIn("数据", case_world["departments"])

    def test_case_world_stage_only_writes_seed_and_world(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_spec = {
                "case_id": "case_stage_only",
                "task_id": "REQ-232",
                "title": "",
                "company_type": "",
                "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "阶段拆分验证",
                "main_goal_hint": "验证 case-world 阶段不会偷偷生成后续产物",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 9,
            }
            case_spec_path = root / "case_spec.json"
            write_json(case_spec_path, case_spec)
            result = generate_case_world_stage(case_spec_path=case_spec_path, dataset_root=root / "dataset")
            case_dir = Path(result["case_dir"])
            self.assertTrue((case_dir / "input" / "case_seed.json").exists())
            self.assertTrue((case_dir / "input" / "case_world.json").exists())
            self.assertFalse((case_dir / "case_spec.json").exists())
            self.assertFalse((case_dir / "input" / "conversation_plan.json").exists())
            self.assertFalse((case_dir / "input" / "utterance_plan.jsonl").exists())
            self.assertFalse((case_dir / "data" / "realized_messages.jsonl").exists())

    def test_command_plan_stage_requires_target_gold_prerequisite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_spec = {
                "case_id": "case_missing_prereq",
                "task_id": "REQ-233",
                "title": "",
                "company_type": "",
                "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "严格前置校验",
                "main_goal_hint": "验证 realize 缺少前置时会报清晰错误",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 10,
            }
            case_spec_path = root / "case_spec.json"
            write_json(case_spec_path, case_spec)
            generate_case_world_stage(case_spec_path=case_spec_path, dataset_root=root / "dataset")
            case_dir = root / "dataset" / "cases" / "case_missing_prereq"
            generate_characters_stage(case_dir_path=case_dir)
            generate_conversation_plan_stage(case_dir_path=case_dir)
            with self.assertRaises(ValidationError) as ctx:
                generate_command_plan_stage(case_dir_path=case_dir)
            self.assertIn("gold/target_state.json", str(ctx.exception))
            self.assertIn("target-gold", str(ctx.exception))

    def test_compile_and_adapt_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_spec = {
                "case_id": "case_smoke",
                "task_id": "REQ-231",
                "title": "",
                "company_type": "",
                "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "企业级 SSO 上线推进",
                "main_goal_hint": "评估并推动五月上旬完成上线",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 3,
            }
            case_spec_path = root / "case_spec.json"
            write_json(case_spec_path, case_spec)
            compiled = compile_case(case_spec_path=case_spec_path, dataset_root=root / "dataset")
            self.assertIn(compiled["llm_mode"], {"fallback", "mixed", "live"})
            self.assertIn("case_world", compiled["generation_modes"])
            self.assertIn("conversation_plan", compiled["generation_modes"])
            self.assertIn("command_plan", compiled["generation_modes"])
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "case_seed.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "case_world.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "conversation_plan.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "checks" / "conversation_plan_generation_log.json").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "input" / "command_plan.jsonl").exists())
            self.assertTrue((Path(compiled["case_dir"]) / "execution_plan.json").exists())
            case_dir = Path(compiled["case_dir"])
            first_message_step = next(
                row for row in compiled["command_plan"] if row["action_type"] in {"send_message", "reply_in_thread"}
            )
            execution_result = execute_case(case_dir_path=case_dir, dry_run=True)
            self.assertEqual(execution_result["status"], "success")
            write_json(
                case_dir / "execution_result.json",
                {
                    "case_id": "case_smoke",
                    "status": "success",
                    "operator_identity": "user",
                    "delivery_mode": "prefixed_single_operator",
                    "created_resources": {},
                    "thread_id_to_chat_id": {"omt_1": "oc_1"},
                    "action_status": execution_result["action_status"],
                    "preflight": {"auth_ok": True},
                },
            )
            write_jsonl(
                case_dir / "lark_fetch_records.jsonl",
                [
                    {
                        "record_id": "fetch-1",
                        "domain": "im",
                        "kind": "thread_messages_fetch",
                        "captured_at": utc_now_iso(),
                        "identity": "user",
                        "command": "lark-cli im +threads-messages-list",
                        "response": {
                            "data": {
                                "thread_id": "omt_1",
                                "messages": [
                                    {
                                        "message_id": "om_1",
                                        "content": "这个日期暂时不要对外说死。",
                                        "msg_type": "text",
                                        "create_time": "2026-04-26 13:07",
                                        "deleted": False,
                                        "sender": {"id": "ou_1", "sender_type": "user"},
                                    }
                                ],
                            }
                        },
                    }
                ],
            )
            write_jsonl(
                case_dir / "data" / "collected_messages.jsonl",
                [
                    {
                        "turn_id": first_message_step["step_id"],
                        "sequence_no": first_message_step["sequence_no"],
                        "session_id": first_message_step["session_id"],
                        "source_type": first_message_step["source_type"],
                        "source_ref": first_message_step["source_ref"],
                        "chat_ref": first_message_step["chat_ref"],
                        "speaker_ref": first_message_step["speaker_ref"],
                        "topic_key": first_message_step["topic_key"],
                        "turn_purpose": first_message_step["turn_purpose"],
                        "supports_event_types": first_message_step["supports_event_types"],
                        "references_previous_turns": [],
                        "state_transition": first_message_step["state_transition"],
                        "semantic_payload": first_message_step["semantic_payload"],
                        "root_turn_id": first_message_step["root_turn_id"],
                        "content_text": first_message_step["params"]["content_text"],
                        "message_id": "om_1",
                        "collect_source": "fetch_records",
                        "actual_sender": {
                            "open_id": "ou_1",
                            "name": "",
                            "sender_type": "user",
                        },
                        "simulated_speaker": next(
                            {
                                "speaker_ref": item["person_id"],
                                "open_id": item["simulated_open_id"],
                                "name": item["name"],
                                "department": item["department"],
                                "role": item["role"],
                                "stance": item["stance"],
                            }
                            for item in compiled["characters"]["characters"]
                            if item["person_id"] == first_message_step["speaker_ref"]
                        ),
                        "normalized_actor_id": first_message_step["speaker_ref"],
                        "speaker_resolution_mode": "command_plan_only",
                        "prefix_speaker_hint": {
                            "speaker_ref": "",
                            "name": "",
                            "department": "",
                        },
                    }
                ],
            )
            gold = generate_gold_stage(case_dir_path=case_dir)
            validated = validate_case_stage(case_dir_path=case_dir)
            self.assertTrue((case_dir / "gold" / "expected_events.jsonl").exists())
            self.assertTrue((case_dir / "checks" / "conversation_complexity_report.json").exists())
            self.assertIn("gold", gold)
            self.assertIn("dataset_validation_report", validated)
            adapted = adapt_case(case_dir_path=case_dir)
            self.assertEqual(adapted["adapter_report"]["output_events"], 1)
            self.assertTrue((case_dir / "openclaw_message_ingress.jsonl").exists())
            self.assertTrue((case_dir / "build_report.json").exists())

    def test_validate_detects_simulated_open_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_spec = {
                "case_id": "case_openid_mismatch",
                "task_id": "REQ-234",
                "title": "",
                "company_type": "",
                "department_hints": ["产品", "研发", "安全", "运维", "销售", "客户成功"],
                "scenario_profile": "enterprise_release_coordination",
                "title_hint": "模拟工号校验",
                "main_goal_hint": "验证 validate 会检查 simulated_open_id 是否来自角色映射表",
                "main_goal": "",
                "difficulty": "medium",
                "seed": 4,
            }
            case_spec_path = root / "case_spec.json"
            write_json(case_spec_path, case_spec)
            compiled = compile_case(case_spec_path=case_spec_path, dataset_root=root / "dataset")
            case_dir = Path(compiled["case_dir"])
            first_message_step = next(
                row for row in compiled["command_plan"] if row["action_type"] in {"send_message", "reply_in_thread"}
            )
            execute_case(case_dir_path=case_dir, dry_run=True)
            write_json(
                case_dir / "execution_result.json",
                {
                    "case_id": "case_openid_mismatch",
                    "status": "success",
                    "operator_identity": "user",
                    "delivery_mode": "prefixed_single_operator",
                    "created_resources": {},
                    "thread_id_to_chat_id": {"omt_1": "oc_1"},
                    "action_status": [],
                    "preflight": {"auth_ok": True},
                },
            )
            write_jsonl(
                case_dir / "lark_fetch_records.jsonl",
                [
                    {
                        "record_id": "fetch-1",
                        "domain": "im",
                        "kind": "thread_messages_fetch",
                        "captured_at": utc_now_iso(),
                        "identity": "user",
                        "command": "lark-cli im +threads-messages-list",
                        "response": {
                            "data": {
                                "thread_id": "omt_1",
                                "messages": [
                                    {
                                        "message_id": "om_1",
                                        "content": "这个日期暂时不要对外说死。",
                                        "msg_type": "text",
                                        "create_time": "2026-04-26 13:07",
                                        "deleted": False,
                                        "sender": {"id": "ou_1", "sender_type": "user"},
                                    }
                                ],
                            }
                        },
                    }
                ],
            )
            simulated_speaker = next(
                {
                    "speaker_ref": item["person_id"],
                    "open_id": "ou_sim_wrong_actor",
                    "name": item["name"],
                    "department": item["department"],
                    "role": item["role"],
                    "stance": item["stance"],
                }
                for item in compiled["characters"]["characters"]
                if item["person_id"] == first_message_step["speaker_ref"]
            )
            write_jsonl(
                case_dir / "data" / "collected_messages.jsonl",
                [
                    {
                        "turn_id": first_message_step["step_id"],
                        "sequence_no": first_message_step["sequence_no"],
                        "session_id": first_message_step["session_id"],
                        "source_type": first_message_step["source_type"],
                        "source_ref": first_message_step["source_ref"],
                        "chat_ref": first_message_step["chat_ref"],
                        "speaker_ref": first_message_step["speaker_ref"],
                        "topic_key": first_message_step["topic_key"],
                        "turn_purpose": first_message_step["turn_purpose"],
                        "supports_event_types": first_message_step["supports_event_types"],
                        "references_previous_turns": [],
                        "state_transition": first_message_step["state_transition"],
                        "semantic_payload": first_message_step["semantic_payload"],
                        "root_turn_id": first_message_step["root_turn_id"],
                        "content_text": first_message_step["params"]["content_text"],
                        "message_id": "om_1",
                        "collect_source": "fetch_records",
                        "actual_sender": {
                            "open_id": "ou_1",
                            "name": "",
                            "sender_type": "user",
                        },
                        "simulated_speaker": simulated_speaker,
                        "normalized_actor_id": first_message_step["speaker_ref"],
                        "speaker_resolution_mode": "command_plan_only",
                        "prefix_speaker_hint": {
                            "speaker_ref": "",
                            "name": "",
                            "department": "",
                        },
                    }
                ],
            )
            generate_gold_stage(case_dir_path=case_dir)
            validated = validate_case_stage(case_dir_path=case_dir)
            self.assertFalse(validated["dataset_validation_report"]["passed"])
            self.assertTrue(
                any(
                    "simulated_speaker.open_id must match characters.json simulated_open_id" in error
                    for error in validated["dataset_validation_report"]["errors"]
                )
            )


if __name__ == "__main__":
    unittest.main()
