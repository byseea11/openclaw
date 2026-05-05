from __future__ import annotations

import unittest

from feishu_builder_agent.catalog_generator import generate_case_profile_catalog_with_mode
from feishu_builder_agent.case_profiles import load_case_profile_catalog


class _CatalogLLM:
    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, *, system_prompt: str, user_prompt: str):
        return self.payload


class CatalogGeneratorTests(unittest.TestCase):
    def test_catalog_generator_accepts_valid_catalog_payload(self) -> None:
        current = load_case_profile_catalog()
        generated, mode = generate_case_profile_catalog_with_mode(
            llm_client=_CatalogLLM(current),
            current_catalog=current,
        )
        self.assertEqual(mode, "live")
        self.assertIn("scenario_profiles", generated)
        self.assertIn("enterprise_release_coordination", generated["scenario_profiles"])


if __name__ == "__main__":
    unittest.main()
