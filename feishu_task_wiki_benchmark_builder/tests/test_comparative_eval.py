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


if __name__ == "__main__":
    unittest.main()
