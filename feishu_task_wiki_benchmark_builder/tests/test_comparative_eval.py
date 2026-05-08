from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.llm import ModelCallResult
from feishu_task_wiki_benchmark_builder.stages.comparative_eval import build_comparative_eval


class FakePhase3ModelClient:
    def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, object]) -> ModelCallResult:
        if stage == "phase3-task-wiki-answer":
            events = user_payload["task_wiki_runtime"]["candidate_verified_events"]  # type: ignore[index]
            return ModelCallResult(
                payload={
                    "answer": "正式窗口已确认，个人偏好不影响任务。",
                    "supporting_message_ids": ["om_official"],
                    "supporting_event_ids": [events[0]["event_id"]],  # type: ignore[index]
                    "confidence": 0.9,
                },
                backend="fixture",
                model="fake-phase3",
                base_url="fixture://phase3",
                duration_ms=0,
            )
        if stage == "phase3-answer-judge":
            system_output = user_payload["system_output"]  # type: ignore[index]
            answer = str(system_output["answer"])  # type: ignore[index]
            ids = system_output["evidence_message_ids"]  # type: ignore[index]
            return ModelCallResult(
                payload={
                    "answer_correct": "正式窗口" in answer and "om_official" in ids,
                    "evidence_supports_answer": "om_official" in ids,
                    "private_info_leak": "om_private" in ids,
                    "stale_value": False,
                    "reasons": ["fake judge"],
                },
                backend="fixture",
                model="fake-phase3",
                base_url="fixture://phase3",
                duration_ms=0,
            )
        raise AssertionError(f"unexpected stage {stage}")


class ComparativeEvalTests(unittest.TestCase):
    def _base_payload(self) -> dict[str, object]:
        return {
            "case_id": "case_001",
            "family_id": "private_info_in_official_file",
            "query_benchmark": {
                "queries": [
                    {
                        "query_id": "query_001",
                        "query": "正式任务状态是什么？",
                        "supporting_message_ids": ["om_official"],
                    }
                ]
            },
            "semantic_gold": {
                "expected_query_answers": [
                    {
                        "query_id": "query_001",
                        "required_supporting_message_ids": ["om_official"],
                    }
                ]
            },
            "collected_messages": [
                {
                    "message_id": "om_official",
                    "message_text": "正式纪要确认当前窗口。",
                    "official_file_ref": "file_001",
                    "task_relevance_boundary": "正式结论",
                },
                {
                    "message_id": "om_private",
                    "message_text": "Carol 的个人偏好不影响任务。",
                    "private_info_ref": "private_001",
                    "task_relevance_boundary": "个人偏好，不影响任务",
                },
            ],
            "task_wiki_metrics": {"overall": {"status": "passed"}},
            "task_wiki_predictions": {
                "verification_results": [
                    {
                        "verified_events": [
                            {
                                "event_id": "event_001",
                                "core_entry_id": "om_official",
                                "evidence_quote": "正式纪要确认当前窗口。",
                                "claim": "正式纪要确认当前窗口。",
                            }
                        ]
                    }
                ]
            },
            "openclaw_answers": {
                "answers": [
                    {
                        "query_id": "query_001",
                        "answer": "正式窗口已确认。",
                        "supporting_message_ids": ["om_official"],
                        "judge_result": {"success": True},
                    }
                ]
            },
            "openclaw_baseline_report": {"baseline_mode": "openclaw_real_replay"},
        }

    def test_evidence_precision_and_recall_are_scored(self) -> None:
        payload = self._base_payload()
        artifact = build_comparative_eval(**payload, model_client=FakePhase3ModelClient())  # type: ignore[arg-type]
        self.assertEqual(artifact["score_artifact"], "phase3_score")
        self.assertIn("aggregate_scores", artifact)
        self.assertIn("raw_scores", artifact)
        self.assertIn("analysis_scores", artifact)
        self.assertFalse(artifact["baseline_fairness"]["query_context_injected"])
        self.assertIn("per_query_scores", artifact)
        self.assertIn("evidence_metrics", artifact)
        task_result = artifact["query_results"][0]["systems"]["task_wiki_3_layer"]
        self.assertNotEqual(task_result["answer_text"], "Task Wiki runtime projection uses verified events and wiki evidence refs.")
        self.assertTrue(task_result["answer_correct"])
        self.assertEqual(task_result["evidence"]["evidence_precision"], 1.0)
        self.assertEqual(task_result["evidence"]["evidence_recall"], 1.0)
        self.assertEqual(task_result["task_wiki_answer_adapter"]["supporting_event_ids"], ["event_001"])

    def test_no_evidence_output_is_explicit_failure(self) -> None:
        payload = self._base_payload()
        payload["openclaw_answers"] = {
            "answers": [
                {
                    "query_id": "query_001",
                    "answer": "正式窗口已确认。",
                    "supporting_message_ids": [],
                    "judge_result": {"success": True},
                }
            ]
        }
        artifact = build_comparative_eval(**payload, model_client=FakePhase3ModelClient())  # type: ignore[arg-type]
        openclaw_result = artifact["query_results"][0]["systems"]["openclaw_original"]
        self.assertIn("no_evidence_output", openclaw_result["failure_reasons"])
        self.assertEqual(artifact["systems"]["openclaw_original"]["metrics"]["evidence_output_rate"], 0.0)

    def test_private_info_as_evidence_is_unsafe(self) -> None:
        payload = self._base_payload()
        payload["openclaw_answers"] = {
            "answers": [
                {
                    "query_id": "query_001",
                    "answer": "正式窗口已确认。",
                    "supporting_message_ids": ["om_private"],
                    "judge_result": {"success": True},
                }
            ]
        }
        artifact = build_comparative_eval(**payload, model_client=FakePhase3ModelClient())  # type: ignore[arg-type]
        openclaw_result = artifact["query_results"][0]["systems"]["openclaw_original"]
        self.assertIn("private_info_leak", openclaw_result["failure_reasons"])
        self.assertFalse(openclaw_result["evidence"]["evidence_private_info_safety"])

    def test_invalid_task_wiki_evidence_id_is_filtered(self) -> None:
        class InvalidEvidenceModelClient(FakePhase3ModelClient):
            def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, object]) -> ModelCallResult:
                if stage == "phase3-task-wiki-answer":
                    return ModelCallResult(
                        payload={
                            "answer": "正式窗口已确认。",
                            "supporting_message_ids": ["om_not_verified"],
                            "supporting_event_ids": ["event_001"],
                            "confidence": 0.8,
                        },
                        backend="fixture",
                        model="fake-phase3",
                        base_url="fixture://phase3",
                        duration_ms=0,
                    )
                return super().complete_json(stage=stage, system_prompt=system_prompt, user_payload=user_payload)

        payload = self._base_payload()
        artifact = build_comparative_eval(**payload, model_client=InvalidEvidenceModelClient())  # type: ignore[arg-type]
        task_result = artifact["query_results"][0]["systems"]["task_wiki_3_layer"]
        self.assertEqual(task_result["evidence"]["output_message_ids"], ["om_official"])
        self.assertIn(
            "invalid_task_wiki_evidence_id:om_not_verified",
            task_result["task_wiki_answer_adapter"]["validation_warnings"],
        )

    def test_task_wiki_answer_llm_failure_falls_back_to_verified_events(self) -> None:
        class BrokenAnswerModelClient(FakePhase3ModelClient):
            def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, object]) -> ModelCallResult:
                if stage == "phase3-task-wiki-answer":
                    raise ValueError("bad json")
                return super().complete_json(stage=stage, system_prompt=system_prompt, user_payload=user_payload)

        payload = self._base_payload()
        artifact = build_comparative_eval(**payload, model_client=BrokenAnswerModelClient())  # type: ignore[arg-type]
        task_result = artifact["query_results"][0]["systems"]["task_wiki_3_layer"]
        self.assertIn("正式纪要确认当前窗口", task_result["answer_text"])
        self.assertEqual(task_result["evidence"]["output_message_ids"], ["om_official"])
        self.assertIn(
            "task_wiki_answer_llm_failed:ValueError",
            task_result["task_wiki_answer_adapter"]["validation_warnings"],
        )

    def _contradiction_payload(self) -> dict[str, object]:
        return {
            "case_id": "case_contradiction",
            "family_id": "contradiction_update",
            "query_benchmark": {
                "queries": [
                    {
                        "query_id": "query_owner_history",
                        "query": "FEISHU-726 有哪些历史负责人？",
                        "expected_good_behavior": "列出 Carol、Alice，并说明 Xavier 是当前负责人。",
                        "supporting_message_ids": ["om_initial", "om_handoff", "om_current"],
                    },
                    {
                        "query_id": "query_window",
                        "query": "FEISHU-726 的发布窗口是哪天？",
                        "expected_good_behavior": "说明 5月10日 -> 5月12日 -> 5月15日，旧窗口已作废。",
                        "supporting_message_ids": ["om_initial", "om_handoff", "om_current", "om_obsolete"],
                    },
                    {
                        "query_id": "query_status",
                        "query": "FEISHU-726 当前状态如何？",
                        "expected_good_behavior": "说明当前已暂停，原因是组件升级延迟。",
                        "supporting_message_ids": ["om_status", "om_dependency", "om_current"],
                    },
                ]
            },
            "semantic_gold": {
                "expected_task_facts": [
                    {
                        "claim": "FEISHU-726 当前负责人是苏禾（Xavier）。",
                        "required_supporting_message_ids": ["om_current"],
                    },
                    {
                        "claim": "FEISHU-726 的发布窗口当前为5月15日，旧窗口（5月10日、5月12日）已作废。",
                        "required_supporting_message_ids": ["om_current", "om_obsolete"],
                    },
                    {
                        "claim": "FEISHU-726 当前状态为已暂停，因组件升级延迟。",
                        "required_supporting_message_ids": ["om_status", "om_dependency"],
                    },
                    {
                        "claim": "FEISHU-726 的历史负责人包括陈雪（Carol）和林晨（Alice）。",
                        "required_supporting_message_ids": ["om_initial", "om_handoff"],
                    },
                ]
            },
            "collected_messages": [
                {"message_id": "om_initial", "message_text": "FEISHU-726 我负责，窗口定5月10日。"},
                {"message_id": "om_handoff", "message_text": "Carol转交给我负责，窗口改5月12日。"},
                {"message_id": "om_current", "message_text": "我来负责FEISHU-726，窗口推迟到5月15日，旧日期作废。"},
                {"message_id": "om_obsolete", "message_text": "确认旧窗口5月10日和12日都已作废。"},
                {"message_id": "om_status", "message_text": "FEISHU-726状态改为已暂停，等组件升级完成。"},
                {"message_id": "om_dependency", "message_text": "当前blocker是依赖组件升级延迟。"},
            ],
            "task_wiki_metrics": {"overall": {"status": "passed"}},
            "task_wiki_predictions": {
                "verified_events": [
                    {
                        "event_id": "evt_initial_owner",
                        "event_type": "commitment_event",
                        "core_entry_id": "om_initial",
                        "owner": "陈雪",
                        "claim": "FEISHU-726 我负责，窗口定5月10日。",
                        "evidence_quote": "FEISHU-726 我负责，窗口定5月10日。",
                    },
                    {
                        "event_id": "evt_handoff_owner",
                        "event_type": "commitment_event",
                        "core_entry_id": "om_handoff",
                        "owner": "林晨",
                        "claim": "Carol转交给我负责，窗口改5月12日。",
                        "evidence_quote": "Carol转交给我负责，窗口改5月12日。",
                    },
                    {
                        "event_id": "evt_current_owner",
                        "event_type": "commitment_event",
                        "core_entry_id": "om_current",
                        "owner": "苏禾",
                        "claim": "我来负责FEISHU-726，窗口推迟到5月15日，旧日期作废。",
                        "evidence_quote": "我来负责FEISHU-726",
                    },
                    {
                        "event_id": "evt_window_12",
                        "event_type": "time_event",
                        "core_entry_id": "om_handoff",
                        "time_value": "5月12日",
                        "claim": "Carol转交给我负责，窗口改5月12日。",
                        "evidence_quote": "窗口改5月12日",
                    },
                    {
                        "event_id": "evt_window_15",
                        "event_type": "time_event",
                        "core_entry_id": "om_current",
                        "time_value": "5月15日",
                        "claim": "我来负责FEISHU-726，窗口推迟到5月15日，旧日期作废。",
                        "evidence_quote": "窗口推迟到5月15日",
                    },
                    {
                        "event_id": "evt_obsolete",
                        "event_type": "status_event",
                        "core_entry_id": "om_obsolete",
                        "status": "作废",
                        "claim": "确认旧窗口5月10日和12日都已作废。",
                        "evidence_quote": "确认旧窗口5月10日和12日都已作废。",
                    },
                    {
                        "event_id": "evt_status",
                        "event_type": "status_event",
                        "core_entry_id": "om_status",
                        "status": "已暂停",
                        "claim": "FEISHU-726状态改为已暂停，等组件升级完成。",
                        "evidence_quote": "FEISHU-726状态改为已暂停",
                    },
                    {
                        "event_id": "evt_dependency",
                        "event_type": "constraint_event",
                        "core_entry_id": "om_dependency",
                        "claim": "当前blocker是依赖组件升级延迟。",
                        "evidence_quote": "当前blocker是依赖组件升级延迟",
                    },
                ]
            },
            "openclaw_answers": {
                "answers": [
                    {
                        "query_id": "query_owner_history",
                        "answer": "历史负责人包括 Carol、Alice，Xavier 是当前负责人。",
                        "supporting_message_ids": ["om_current"],
                        "judge_result": {"success": True},
                    },
                    {
                        "query_id": "query_window",
                        "answer": "当前窗口是5月15日。",
                        "supporting_message_ids": ["om_current"],
                        "judge_result": {"success": True},
                    },
                    {
                        "query_id": "query_status",
                        "answer": "当前已暂停。",
                        "supporting_message_ids": ["om_status"],
                        "judge_result": {"success": True},
                    },
                ]
            },
            "openclaw_baseline_report": {"baseline_mode": "openclaw_real_replay"},
            "task_wiki_artifacts": {"task_wiki_markdown": "# Task Wiki"},
        }

    def test_contradiction_adapter_builds_owner_and_window_chains_without_bob(self) -> None:
        class ContradictionJudge:
            def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, object]) -> ModelCallResult:
                if stage == "phase3-task-wiki-answer":
                    raise AssertionError("contradiction_update should use deterministic Task Wiki answer")
                if stage == "phase3-answer-judge":
                    system_output = user_payload["system_output"]  # type: ignore[index]
                    answer = str(system_output["answer"])  # type: ignore[index]
                    return ModelCallResult(
                        payload={
                            "answer_correct": "Bob" not in answer
                            and (
                                ("Carol" in answer and "Alice" in answer and "Xavier" in answer)
                                or ("5月10" in answer and "5月12" in answer and "5月15" in answer)
                                or ("已暂停" in answer and "组件升级" in answer)
                            ),
                            "evidence_supports_answer": True,
                            "private_info_leak": False,
                            "stale_value": False,
                            "reasons": ["contradiction fixture judge"],
                        },
                        backend="fixture",
                        model="fake-phase3",
                        base_url="fixture://phase3",
                        duration_ms=0,
                    )
                raise AssertionError(f"unexpected stage {stage}")

        artifact = build_comparative_eval(**self._contradiction_payload(), model_client=ContradictionJudge())  # type: ignore[arg-type]
        task_results = [
            item["systems"]["task_wiki_3_layer"]
            for item in artifact["query_results"]
        ]
        self.assertEqual(artifact["systems"]["task_wiki_3_layer"]["metrics"]["query_success_rate"], 1.0)
        self.assertGreater(
            artifact["systems"]["task_wiki_3_layer"]["metrics"]["evidence_recall"],
            artifact["systems"]["openclaw_original"]["metrics"]["evidence_recall"],
        )
        owner_answer = task_results[0]["answer_text"]
        window_answer = task_results[1]["answer_text"]
        status_answer = task_results[2]["answer_text"]
        self.assertNotIn("Bob", owner_answer)
        self.assertIn("Xavier", owner_answer)
        self.assertNotIn("Carol、Alice", owner_answer)
        self.assertIn("5月10", window_answer)
        self.assertIn("5月12", window_answer)
        self.assertIn("5月15", window_answer)
        self.assertIn("已暂停", status_answer)
        self.assertIn("组件升级", status_answer)
        self.assertIn("evt_status", task_results[2]["task_wiki_answer_adapter"]["supporting_event_ids"])

    def test_contradiction_adapter_uses_current_case_task_id(self) -> None:
        def replace_task_id(value):
            if isinstance(value, str):
                return value.replace("FEISHU-726", "FEISHU-335")
            if isinstance(value, list):
                return [replace_task_id(item) for item in value]
            if isinstance(value, dict):
                return {key: replace_task_id(item) for key, item in value.items()}
            return value

        class AlwaysCorrectJudge:
            def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, object]) -> ModelCallResult:
                if stage == "phase3-task-wiki-answer":
                    raise AssertionError("contradiction_update should use deterministic Task Wiki answer")
                if stage == "phase3-answer-judge":
                    return ModelCallResult(
                        payload={
                            "answer_correct": True,
                            "evidence_supports_answer": True,
                            "private_info_leak": False,
                            "stale_value": False,
                            "reasons": ["task id guard"],
                        },
                        backend="fixture",
                        model="fake-phase3",
                        base_url="fixture://phase3",
                        duration_ms=0,
                    )
                raise AssertionError(f"unexpected stage {stage}")

        payload = replace_task_id(self._contradiction_payload())
        artifact = build_comparative_eval(**payload, model_client=AlwaysCorrectJudge())  # type: ignore[arg-type]
        answers = [
            item["systems"]["task_wiki_3_layer"]["answer_text"]
            for item in artifact["query_results"]
        ]
        self.assertTrue(answers)
        for answer in answers:
            self.assertIn("FEISHU-335", answer)
            self.assertNotIn("FEISHU-726", answer)

    def test_contradiction_adapter_uses_message_order_for_current_state(self) -> None:
        payload = self._contradiction_payload()
        payload["collected_messages"] = [
            {"message_id": "om_initial", "turn_id": "turn_001", "message_text": "FEISHU-726 我负责，窗口定5月10日。"},
            {"message_id": "om_handoff", "turn_id": "turn_002", "message_text": "Carol转交给我负责，窗口改5月12日。"},
            {"message_id": "om_current", "turn_id": "turn_003", "message_text": "我来负责FEISHU-726，窗口推迟到5月15日，旧日期作废。"},
            {"message_id": "om_status", "turn_id": "turn_004", "message_text": "FEISHU-726状态改为已暂停，等组件升级完成。"},
        ]
        # Runtime verified event order is not guaranteed to match transcript order.
        payload["task_wiki_predictions"]["verified_events"] = list(reversed(payload["task_wiki_predictions"]["verified_events"]))  # type: ignore[index]

        class AlwaysCorrectJudge:
            def complete_json(self, *, stage: str, system_prompt: str, user_payload: dict[str, object]) -> ModelCallResult:
                if stage == "phase3-task-wiki-answer":
                    raise AssertionError("contradiction_update should use deterministic Task Wiki answer")
                if stage == "phase3-answer-judge":
                    return ModelCallResult(
                        payload={
                            "answer_correct": True,
                            "evidence_supports_answer": True,
                            "private_info_leak": False,
                            "stale_value": False,
                            "reasons": ["message order guard"],
                        },
                        backend="fixture",
                        model="fake-phase3",
                        base_url="fixture://phase3",
                        duration_ms=0,
                    )
                raise AssertionError(f"unexpected stage {stage}")

        artifact = build_comparative_eval(**payload, model_client=AlwaysCorrectJudge())  # type: ignore[arg-type]
        answers = [
            item["systems"]["task_wiki_3_layer"]["answer_text"]
            for item in artifact["query_results"]
        ]
        self.assertIn("5月15", answers[1])
        self.assertNotIn("当前截止/窗口时间是5月12", answers[1])
        self.assertIn("已暂停", answers[2])


if __name__ == "__main__":
    unittest.main()
