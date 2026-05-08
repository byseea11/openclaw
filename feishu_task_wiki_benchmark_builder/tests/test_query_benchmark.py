from __future__ import annotations

import unittest

from feishu_task_wiki_benchmark_builder.stages.query_benchmark import build_query_benchmark


class QueryBenchmarkTests(unittest.TestCase):
    def test_uses_query_specific_semantic_gold_support(self) -> None:
        story_plan = {
            "planned_probe_queries": [
                {"query": "窗口是什么？", "expected_good_behavior": "答正式窗口。"},
                {"query": "个人偏好是否影响？", "expected_good_behavior": "答不影响。"},
            ]
        }
        annotation_rows = [
            {"message_id": "om_window", "evidence_text": "正式窗口是 5月10日。", "official_file_ref": "file"},
            {"message_id": "om_private", "evidence_text": "个人偏好不影响任务。", "private_info_ref": "p"},
            {"message_id": "om_noise", "evidence_text": "无关 ack。"},
        ]
        semantic_gold = {
            "expected_query_answers": [
                {"query_id": "case_001_query_001", "required_supporting_message_ids": ["om_window"]},
                {"query_id": "case_001_query_002", "required_supporting_message_ids": ["om_private"]},
            ]
        }

        artifact = build_query_benchmark(
            case_id="case_001",
            family_id="private_info_in_official_file",
            story_plan=story_plan,
            annotation_gold_rows=annotation_rows,
            semantic_gold=semantic_gold,
        )

        self.assertEqual(artifact["queries"][0]["supporting_message_ids"], ["om_window"])
        self.assertEqual(artifact["queries"][1]["supporting_message_ids"], ["om_private"])
        self.assertNotEqual(
            artifact["queries"][0]["supporting_message_ids"],
            [row["message_id"] for row in annotation_rows],
        )

    def test_fallback_excludes_private_distractor_for_official_query(self) -> None:
        story_plan = {
            "planned_probe_queries": [
                {"query": "正式升级窗口是什么？", "expected_good_behavior": "答正式窗口。"}
            ]
        }
        annotation_rows = [
            {"message_id": "om_window", "evidence_text": "正式纪要确认升级窗口。", "official_file_ref": "file"},
            {"message_id": "om_private", "evidence_text": "Carol 个人偏好希望提前。", "private_info_ref": "p"},
        ]

        artifact = build_query_benchmark(
            case_id="case_001",
            family_id="private_info_in_official_file",
            story_plan=story_plan,
            annotation_gold_rows=annotation_rows,
        )

        self.assertEqual(artifact["queries"][0]["supporting_message_ids"], ["om_window"])
        self.assertEqual(artifact["queries"][0]["evidence_roles"]["om_window"], "official_current")


if __name__ == "__main__":
    unittest.main()
