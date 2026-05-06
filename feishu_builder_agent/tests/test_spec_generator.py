from __future__ import annotations

from unittest.mock import patch
import unittest

from feishu_builder_agent.spec_generator import generate_case_spec_with_mode, normalize_seed


class _StaticJsonClient:
    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str):
        del system_prompt, user_prompt
        return self.payload


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
        self.assertNotIn("title_hint", payload)
        self.assertNotIn("main_goal_hint", payload)
        self.assertNotIn("scenario_profile", payload)

    def test_live_llm_cannot_override_system_owned_ids(self) -> None:
        payload, mode = generate_case_spec_with_mode(
            scenario_profile="enterprise_task_memory",
            difficulty="medium",
            seed=999,
            user_hint="",
            llm_client=_StaticJsonClient(
                {
                    "case_id": "case_feishu_001_v3",
                    "task_id": "FEISHU-1",
                    "selected_failure_modes": ["static_memory_stale_state"],
                    "primary_failure_mode": "static_memory_stale_state",
                }
            ),
        )
        self.assertEqual(mode, "llm")
        self.assertEqual(payload["task_id"], "FEISHU-999")
        self.assertEqual(payload["case_id"], "case_feishu_999_v3")

    def test_normalize_seed_uses_subsecond_precision_when_seed_missing(self) -> None:
        with patch("feishu_builder_agent.spec_generator.datetime") as mocked_datetime:
            mocked_datetime.now.side_effect = [
                __import__("datetime").datetime(2026, 5, 6, 9, 30, 1, 123456, tzinfo=__import__("datetime").timezone.utc),
                __import__("datetime").datetime(2026, 5, 6, 9, 30, 1, 654321, tzinfo=__import__("datetime").timezone.utc),
            ]
            first = normalize_seed()
            second = normalize_seed()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(str(first)), 12)


if __name__ == "__main__":
    unittest.main()
