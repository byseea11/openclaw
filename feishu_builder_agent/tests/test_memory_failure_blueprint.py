from __future__ import annotations

import unittest

from feishu_builder_agent.memory_failure_blueprint_generator import generate_memory_failure_blueprint_with_mode
from feishu_builder_agent.spec_generator import generate_case_spec


class MemoryFailureBlueprintTests(unittest.TestCase):
    def test_blueprint_contains_selected_modes_and_probe_queries(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="hard",
            seed=505160829,
            user_hint="",
        )
        blueprint, mode = generate_memory_failure_blueprint_with_mode(case_spec)
        self.assertEqual(mode, "fallback")
        self.assertEqual(set(blueprint["selected_failure_modes"]), set(case_spec["selected_failure_modes"]))
        for trap in blueprint["traps"]:
            self.assertTrue(trap["common"]["probe_queries"])
            self.assertTrue(trap["common"]["metric_targets"])
            self.assertTrue(trap["common"]["landing_requirements"]["required_benchmark_roles"])

    def test_unverifiable_summary_claim_has_required_distribution(self) -> None:
        case_spec = generate_case_spec(
            scenario_profile="enterprise_task_memory",
            difficulty="easy",
            seed=12,
            user_hint="",
            selected_failure_modes=["unverifiable_summary_claim"],
            primary_failure_mode="unverifiable_summary_claim",
        )
        blueprint, _ = generate_memory_failure_blueprint_with_mode(case_spec)
        trap = blueprint["traps"][0]
        distribution = trap["typed_payload"]["evidence_distribution"]
        self.assertGreaterEqual(distribution["verified_fact_turns"], 1)
        self.assertGreaterEqual(distribution["ambiguous_turns"], 1)
        self.assertGreaterEqual(distribution["hearsay_turns"], 1)
        self.assertGreaterEqual(distribution["no_event_turns"], 1)


if __name__ == "__main__":
    unittest.main()
