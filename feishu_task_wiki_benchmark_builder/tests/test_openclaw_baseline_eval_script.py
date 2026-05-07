from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "amem_docs" / "scripts" / "feishu-openclaw-baseline-eval.mjs"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf8",
    )


def _message_row(*, message_id: str, text: str, create_time: int, session_id: str) -> dict[str, object]:
    return {
        "message": {
            "message_id": message_id,
            "chat_id": "oc_fixture",
            "thread_id": "",
            "root_id": "",
            "create_time": str(create_time),
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        "benchmark_trace": {
            "source_type": "chat",
            "source_ref": f"chat:{session_id}",
        },
    }


def _collected_row(
    *,
    message_id: str,
    text: str,
    beat_id: str,
    turn_id: str,
    official_file_ref: str = "",
    private_info_ref: str = "",
    boundary: str = "",
) -> dict[str, object]:
    return {
        "case_id": "case_fixture_private_info",
        "task_id": "FEISHU-666",
        "message_id": message_id,
        "beat_id": beat_id,
        "turn_id": turn_id,
        "turn_kind": "event_bearing",
        "session_id": "main_chat",
        "message_text": text,
        "content_text": text,
        "observed_text_without_prefix": text,
        "annotation_target": True,
        "event_bearing": True,
        "official_file_ref": official_file_ref,
        "private_info_ref": private_info_ref,
        "task_relevance_boundary": boundary,
        "simulated_speaker": {"name": "林晨"},
    }


def _create_fixture_case(root: Path) -> Path:
    case_dir = root / "cases" / "case_fixture_private_info"
    case_context = {
        "family_id": "private_info_in_official_file",
        "benchmark_requirement_name": "Private Info In Official File",
        "benchmark_requirement_summary": "区分正式纪要和个人偏好。",
        "report_display_name": "Private info fixture",
        "capability_under_test": "任务状态记忆",
        "why_memory_systems_may_fail": "默认摘要可能混入个人偏好。",
        "generation_rules": ["必须包含正式纪要和个人偏好干扰。"],
        "required_case_structure": ["正式结论", "个人备注", "纠偏消息"],
        "probe_strategy": ["询问正式窗口、blocker 和回滚计划。"],
        "expected_good_system_behavior": ["以正式纪要为准，不把个人偏好当任务状态。"],
        "case_id": "case_fixture_private_info",
        "task_id": "FEISHU-666",
        "seed": 7,
        "difficulty": "medium",
        "comparison_target": "openclaw_original",
        "organization": "OpenClaw Test Org",
        "team": "QA",
        "business_goal": "发布准备",
        "scenario_summary": "正式纪要与个人偏好混杂。",
        "family_fit_explanation": "验证 private info boundary。",
    }
    story_plan = {
        "story_id": "story_fixture",
        "case_id": "case_fixture_private_info",
        "family_id": "private_info_in_official_file",
        "task": {"task_id": "FEISHU-666", "title": "发布准备"},
        "actors": [
            {"actor_id": "alice", "display_name": "林晨", "role": "项目负责人"},
            {"actor_id": "carol", "display_name": "陈雪", "role": "研发协作者"},
        ],
        "task_actor_layout": {"owner": "alice"},
        "state_changes": [{"state_id": "state_001", "summary": "正式窗口已确认。"}],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "speaker_actor_id": "alice",
                "session_id": "main_chat",
                "message_intent": "正式纪要确认升级窗口、blocker 和回滚计划。",
                "purpose": "正式结论",
            },
            {
                "beat_id": "beat_002",
                "speaker_actor_id": "carol",
                "session_id": "main_chat",
                "message_intent": "个人面试偏好干扰。",
                "purpose": "个人偏好",
            },
            {
                "beat_id": "beat_003",
                "speaker_actor_id": "alice",
                "session_id": "main_chat",
                "message_intent": "重申以正式纪要为准。",
                "purpose": "正式结论优先",
            },
        ],
        "planned_probe_queries": [
            {
                "query": "FEISHU-666 的正式升级窗口、blocker 和回滚计划是什么？Carol 的个人偏好是否影响任务？",
                "expected_good_behavior": "回答正式升级窗口是2026-05-10 22:00 UTC，blocker 是 network config drift，回滚计划已批；Carol 的个人面试偏好不影响任务。",
            }
        ],
    }
    collected_rows = [
        _collected_row(
            message_id="om_official",
            text="正式纪要确认升级窗口2026-05-10 22:00 UTC，blocker为network config drift，回滚计划已批。",
            beat_id="beat_001",
            turn_id="turn_001",
            official_file_ref="official_file_001",
            boundary="正式结论",
        ),
        _collected_row(
            message_id="om_private",
            text="Carol 周四有个人面试，希望窗口挪到周三前。",
            beat_id="beat_002",
            turn_id="turn_002",
            private_info_ref="private_info_001",
            boundary="个人偏好，不影响任务",
        ),
        _collected_row(
            message_id="om_correction",
            text="以正式纪要为准，个人时间不调整任务窗口。",
            beat_id="beat_003",
            turn_id="turn_003",
            official_file_ref="official_file_001",
            boundary="正式结论优先",
        ),
    ]
    ingress_rows = [
        _message_row(
            message_id="om_official",
            text=str(collected_rows[0]["message_text"]),
            create_time=1,
            session_id="main_chat",
        ),
        _message_row(
            message_id="om_private",
            text=str(collected_rows[1]["message_text"]),
            create_time=2,
            session_id="main_chat",
        ),
        _message_row(
            message_id="om_correction",
            text=str(collected_rows[2]["message_text"]),
            create_time=3,
            session_id="main_chat",
        ),
    ]
    _write_json(case_dir / "input" / "case_context.json", case_context)
    _write_json(case_dir / "input" / "story_plan.json", story_plan)
    _write_json(
        case_dir / "checks" / "pre_annotation_validation_report.json",
        {"case_id": "case_fixture_private_info", "is_valid": True, "checks": []},
    )
    _write_jsonl(case_dir / "data" / "collected_messages.jsonl", collected_rows)
    _write_jsonl(case_dir / "data" / "openclaw_message_ingress.jsonl", ingress_rows)
    _write_json(
        case_dir / "runtime" / "task_wiki_replay" / "layer_metrics.json",
        {
            "overall": {"status": "passed", "health_score": 91},
            "layer1_task_binding": {"status": "passed", "binding_total": 3},
            "layer2_event_verification": {"status": "passed", "verified_event_count": 2},
            "layer3_wiki_projection": {"status": "passed", "projected_task_count": 1},
        },
    )
    return case_dir


class OpenClawBaselineEvalScriptTests(unittest.TestCase):
    def test_script_generates_phase2_gold_and_baseline_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case_dir = _create_fixture_case(Path(tmpdir))
            result = subprocess.run(
                [
                    "node",
                    str(SCRIPT_PATH),
                    "--case-dir",
                    str(case_dir),
                    "--semantic-gold",
                    "rule",
                    "--json",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            summary = json.loads(result.stdout)
            self.assertEqual(summary["baseline_mode"], "openclaw_original_adapter")
            self.assertEqual(summary["ingress_count"], 3)
            self.assertEqual(summary["query_count"], 1)

            self.assertTrue((case_dir / "gold" / "annotation_gold.jsonl").exists())
            self.assertTrue((case_dir / "gold" / "task_wiki_semantic_gold.json").exists())
            self.assertTrue((case_dir / "gold" / "query_benchmark.json").exists())

            answers = json.loads((case_dir / "runtime" / "openclaw_baseline" / "answers.json").read_text())
            self.assertEqual(answers["baseline_mode"], "openclaw_original_adapter")
            self.assertEqual(len(answers["answers"]), 1)
            answer = answers["answers"][0]
            self.assertIn("answer", answer)
            self.assertIn("supporting_message_ids", answer)
            self.assertIn("judge_result", answer)

            report = json.loads((case_dir / "reports" / "openclaw_baseline_eval.json").read_text())
            self.assertEqual(report["baseline_mode"], "openclaw_original_adapter")
            self.assertEqual(report["gold_generation"]["generated_stages"], ["annotation-gold", "semantic-gold", "query-benchmark"])
            self.assertIn("private_info_leak_rate", report["metrics"])

            comparison = (case_dir / "reports" / "openclaw_vs_task_wiki_comparison.md").read_text(encoding="utf8")
            self.assertIn("openclaw_original", comparison)
            self.assertIn("task_wiki_3_layer", comparison)
            self.assertIn("synthetic baseline", comparison)

    def test_script_does_not_import_three_layer_runtime_modules(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf8")
        self.assertNotIn("task-banding", source)
        self.assertNotIn("task-events", source)
        self.assertNotIn("task-wiki/projector", source)
        self.assertNotIn("task-wiki/lint", source)


if __name__ == "__main__":
    unittest.main()
