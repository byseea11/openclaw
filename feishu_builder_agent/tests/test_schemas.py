from __future__ import annotations

import unittest

from feishu_builder_agent.schemas import ValidationError, validate_case_spec


class SchemaTests(unittest.TestCase):
    def test_case_spec_requires_primary_failure_mode_inside_selected_modes(self) -> None:
        with self.assertRaises(ValidationError):
            validate_case_spec(
                {
                    "case_id": "case_feishu_1_v3",
                    "task_id": "FEISHU-1",
                    "difficulty": "medium",
                    "seed": 1,
                    "comparison_target": "openclaw_memory_md",
                    "selected_failure_modes": ["personal_memory_pollution"],
                    "primary_failure_mode": "static_memory_stale_state",
                }
            )


if __name__ == "__main__":
    unittest.main()
