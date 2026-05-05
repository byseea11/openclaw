from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .case_profiles import CATALOG_PATH
from .llm_client import JsonLLMClient
from .schemas import ValidationError, validate_case_profile_catalog


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "case_profile_catalog_system.txt"
USER_PROMPT_PATH = PROMPTS_DIR / "case_profile_catalog_user.txt"


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def build_case_profile_catalog_prompt(*, current_catalog: dict[str, Any]) -> tuple[str, str]:
    system_prompt = _load_prompt(SYSTEM_PROMPT_PATH)
    user_template = _load_prompt(USER_PROMPT_PATH)
    user_prompt = user_template.format(
        current_catalog=json.dumps(current_catalog, ensure_ascii=False, indent=2),
        target_path=str(CATALOG_PATH),
    )
    return system_prompt, user_prompt


def generate_case_profile_catalog_with_mode(
    *,
    llm_client: JsonLLMClient | None,
    current_catalog: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if llm_client is None:
        raise RuntimeError("LLM client is required to generate case profile catalog")
    system_prompt, user_prompt = build_case_profile_catalog_prompt(current_catalog=current_catalog)
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_case_profile_catalog(payload), "live"
    except (Exception, ValidationError) as exc:
        raise RuntimeError(f"failed to generate valid case profile catalog: {exc}") from exc
