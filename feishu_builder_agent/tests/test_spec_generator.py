from __future__ import annotations

import unittest

from feishu_builder_agent.spec_generator import generate_case_spec_with_mode


class SpecGeneratorTests(unittest.TestCase):
    def test_case_spec_contains_v3_failure_mode_fields(self) -> None:
        payload, mode = generate_case_spec_with_mode(
            scenario_profile="enterprise_task_memory",
            difficulty="medium",
            seed=231,
            user_hint="重点覆盖旧状态修正、人员串台和模糊口径",
            selected_failure_modes=["static_memory_stale_state", "personal_memory_pollution"],
            primary_failure_mode="static_memory_stale_state",
        )
        self.assertEqual(mode, "fallback")
        self.assertEqual(payload["comparison_target"], "openclaw_memory_md")
        self.assertEqual(
            payload["selected_failure_modes"],
            ["static_memory_stale_state", "personal_memory_pollution"],
        )
        self.assertEqual(payload["primary_failure_mode"], "static_memory_stale_state")


if __name__ == "__main__":
    unittest.main()
