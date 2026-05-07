from __future__ import annotations

from .prompt_loader import build_stage_system_prompt


def build_conversation_plan_system_prompt(
    *,
    family_id: str | None = None,
    difficulty: str | None = None,
) -> str:
    return build_stage_system_prompt("conversation-plan", family_id=family_id, difficulty=difficulty)
