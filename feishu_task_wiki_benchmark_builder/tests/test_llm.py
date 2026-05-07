from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_task_wiki_benchmark_builder import llm


class LlmTests(unittest.TestCase):
    def test_resolve_openai_runtime_config_reads_repo_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "OPENAI_API_KEY=sk-from-dotenv",
                        "OPENAI_API_BASE_URL=https://example-proxy.test/v1",
                        "FEISHU_BUILDER_MODEL=deepseek-chat",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(llm, "REPO_DOTENV_PATH", dotenv_path):
                config = llm.resolve_openai_runtime_config()
            self.assertEqual(config.api_key, "sk-from-dotenv")
            self.assertEqual(config.base_url, "https://example-proxy.test/v1")
            self.assertEqual(config.model, "deepseek-chat")
            self.assertEqual(config.auth_source, llm.REPO_DOTENV_AUTH_SOURCE)

    def test_resolve_openai_runtime_config_ignores_shell_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "OPENAI_API_KEY=sk-from-dotenv",
                        "OPENAI_API_BASE_URL=https://dotenv-only.test/v1",
                        "FEISHU_BUILDER_MODEL=deepseek-chat",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "sk-from-shell",
                    "OPENAI_API_BASE_URL": "https://shell-env.test/v1",
                    "FEISHU_BUILDER_MODEL": "gpt-shell-env",
                },
                clear=False,
            ):
                with patch.object(llm, "REPO_DOTENV_PATH", dotenv_path):
                    config = llm.resolve_openai_runtime_config()
            self.assertEqual(config.api_key, "sk-from-dotenv")
            self.assertEqual(config.base_url, "https://dotenv-only.test/v1")
            self.assertEqual(config.model, "deepseek-chat")

    def test_resolve_openai_runtime_config_reports_missing_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / ".env"
            with patch.object(llm, "REPO_DOTENV_PATH", missing_path):
                with self.assertRaises(llm.ModelBackendError) as ctx:
                    llm.resolve_openai_runtime_config()
            self.assertEqual(ctx.exception.error_code, "missing_dotenv")

    def test_build_model_call_log_entry_is_metadata_only(self) -> None:
        result = llm.ModelCallResult(
            payload={"ignored": True},
            backend="fixture",
            model="fixture-model",
            base_url="fixture://local",
            duration_ms=7,
        )
        entry = llm.build_model_call_log_entry(
            stage="story-plan",
            result=result,
            case_id="case_0001_anti_interference",
            artifact_path="input/story_plan.json",
        )
        self.assertEqual(entry["stage"], "story-plan")
        self.assertEqual(entry["success"], True)
        self.assertNotIn("system_prompt", entry)
        self.assertNotIn("user_payload", entry)
        self.assertNotIn("response_payload", entry)
        self.assertNotIn("raw_response_text", entry)

    def test_build_model_call_validation_failure_log_entry_includes_raw_payload(self) -> None:
        error = llm.ModelPayloadValidationError(
            "story-plan payload validation failed: story_plan.task is required",
            stage="story-plan",
            payload={"story_id": "story_x", "task": ["bad"]},
            backend="openai",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            duration_ms=12,
        )
        entry = llm.build_model_call_validation_failure_log_entry(
            stage="story-plan",
            error=error,
            case_id="case_0001_contradiction_update",
            artifact_path="input/story_plan.json",
        )
        self.assertEqual(entry["success"], False)
        self.assertEqual(entry["error_type"], "validation_error")
        self.assertEqual(entry["error_code"], "schema_validation_failed")
        self.assertIn("raw_payload", entry)
        self.assertEqual(entry["raw_payload"]["story_id"], "story_x")

    def test_max_tokens_cover_conversation_plan_repair_stage(self) -> None:
        self.assertEqual(llm._max_tokens_for_stage("conversation-plan"), 20000)
        self.assertEqual(llm._max_tokens_for_stage("conversation-plan-repair"), 20000)
        self.assertIsNone(llm._max_tokens_for_stage("story-plan"))


if __name__ == "__main__":
    unittest.main()
