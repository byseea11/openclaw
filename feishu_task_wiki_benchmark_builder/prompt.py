from __future__ import annotations

from .builder_settings import resolve_default_difficulty
from .prompt_loader import build_stage_system_prompt


def build_case_context_system_prompt(
    *,
    family_id: str | None = None,
    difficulty: str | None = None,
) -> str:
    if difficulty is None:
        difficulty = resolve_default_difficulty()
    return build_stage_system_prompt("case-context", family_id=family_id, difficulty=difficulty)


def build_story_plan_system_prompt(
    *,
    family_id: str | None = None,
    difficulty: str | None = None,
) -> str:
    if difficulty is None:
        difficulty = resolve_default_difficulty()
    return build_stage_system_prompt("story-plan", family_id=family_id, difficulty=difficulty)
