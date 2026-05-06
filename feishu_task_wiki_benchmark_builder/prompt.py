from __future__ import annotations

from .config import BUILDER_DEFAULT_DIFFICULTY
from .prompt_loader import build_stage_system_prompt


def build_case_context_system_prompt(
    *,
    family_id: str | None = None,
    difficulty: str = BUILDER_DEFAULT_DIFFICULTY,
) -> str:
    return build_stage_system_prompt("case-context", family_id=family_id, difficulty=difficulty)


def build_story_plan_system_prompt(
    *,
    family_id: str | None = None,
    difficulty: str = BUILDER_DEFAULT_DIFFICULTY,
) -> str:
    return build_stage_system_prompt("story-plan", family_id=family_id, difficulty=difficulty)
