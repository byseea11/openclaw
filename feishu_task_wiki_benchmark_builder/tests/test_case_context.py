from __future__ import annotations

import unittest
from typing import Any

from feishu_task_wiki_benchmark_builder.family_catalog import FAMILY_CATALOG
from feishu_task_wiki_benchmark_builder.llm import ModelCallResult, ModelPayloadValidationError
from feishu_task_wiki_benchmark_builder.stages.case_context import generate_case_context


def _valid_payload() -> dict[str, Any]:
    definition = FAMILY_CATALOG["anti_interference"]
    return {
        "family_id": "anti_interference",
        "benchmark_requirement_name": definition.benchmark_requirement_name,
        "benchmark_requirement_summary": definition.benchmark_requirement_summary,
        "report_display_name": definition.report_display_name,
        "capability_under_test": definition.capability_under_test,
        "why_memory_systems_may_fail": definition.why_memory_systems_may_fail,
        "generation_rules": definition.generation_rules,
        "required_case_structure": definition.required_case_structure,
        "probe_strategy": definition.probe_strategy,
        "expected_good_system_behavior": definition.expected_good_system_behavior,
        "organization": "Example Corp",
        "team": "发布协作组",
        "business_goal": "验证任务记忆边界",
        "scenario_summary": "共享人员在多个上下文中制造干扰。",
        "family_fit_explanation": "该场景要求系统不要把干扰任务状态写入目标任务。",
    }


class SequenceClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.stages: list[str] = []
        self.user_payloads: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        stage: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> ModelCallResult:
        self.stages.append(stage)
        self.user_payloads.append(user_payload)
        return ModelCallResult(
            payload=self.payloads.pop(0),
            backend="fake",
            model="fake-model",
            base_url="fake://local",
            duration_ms=1,
        )


def _generate(client: SequenceClient) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return generate_case_context(
        seed=2026050701,
        requested_family_id="anti_interference",
        difficulty="hard",
        comparison_target="task_wiki_3_layer",
        model_client=client,
    )


class CaseContextTests(unittest.TestCase):
    def test_repair_pass_fills_missing_family_catalog_fields(self) -> None:
        invalid_payload = {
            "family_id": "anti_interference",
            "organization": "Example Corp",
            "team": "发布协作组",
            "business_goal": "验证任务记忆边界",
            "scenario_summary": "共享人员在多个上下文中制造干扰。",
            "family_fit_explanation": "该场景要求系统不要把干扰任务状态写入目标任务。",
        }
        client = SequenceClient([invalid_payload, _valid_payload()])

        artifact, logs = _generate(client)

        self.assertEqual(artifact["family_id"], "anti_interference")
        self.assertEqual(artifact["case_id"], "case_2026050701_anti_interference")
        self.assertEqual(client.stages, ["case-context", "case-context-repair"])
        self.assertEqual([entry["stage"] for entry in logs], ["case-context", "case-context-repair"])
        repair_context = client.user_payloads[1]["repair_context"]
        self.assertIn("benchmark_requirement_name", repair_context["validation_error"])

    def test_repair_failure_keeps_initial_and_repair_payloads(self) -> None:
        invalid_payload = {"family_id": "anti_interference"}
        client = SequenceClient([invalid_payload, invalid_payload])

        with self.assertRaises(ModelPayloadValidationError) as ctx:
            _generate(client)

        self.assertIn("case-context payload validation failed after repair", str(ctx.exception))
        self.assertEqual(client.stages, ["case-context", "case-context-repair"])
        self.assertEqual(ctx.exception.payload["initial_invalid_payload"], invalid_payload)
        self.assertEqual(ctx.exception.payload["repair_invalid_payload"], invalid_payload)


if __name__ == "__main__":
    unittest.main()
