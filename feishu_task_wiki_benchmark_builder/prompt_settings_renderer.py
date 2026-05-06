from __future__ import annotations

import json

from .builder_settings import load_builder_settings, resolve_prompt_slots
from .config import BUILDER_DEFAULT_DIFFICULTY


def _render_runtime_constraints(resolved_slots: dict[str, object]) -> list[str]:
    difficulty_slots = dict(resolved_slots["difficulty_slots"])
    stage_slots = dict(resolved_slots["stage_slots"])
    return [
        "## Skill Runtime Constraints",
        "下方 `Resolved Slot Contract` 只提供当前 difficulty / family 的数字目标。",
        "session 类型、noise 类型、role/context/dependency 语义全部以 skills 正文为准，不从 builder_settings.yml 读取。",
        f"- 当前 difficulty: `{difficulty_slots['difficulty']}`",
        f"- actors 数量必须落在 `{difficulty_slots['character_count_min']}` 到 `{difficulty_slots['character_count_max']}` 之间。",
        f"- 推荐 actors 数量: `{difficulty_slots['recommended_actor_count']}`。",
        f"- 推荐覆盖部门数: `{difficulty_slots['recommended_department_count']}`。",
        f"- 推荐覆盖 session 数: `{difficulty_slots['recommended_session_count']}`。",
        f"- 当前阶段必须体现在这些输出字段里: `{', '.join(stage_slots['must_reflect_output_fields'])}`。",
    ]


def render_prompt_settings_summary(*, stage: str, difficulty: str, family_id: str | None = None) -> str:
    if not difficulty:
        difficulty = BUILDER_DEFAULT_DIFFICULTY
    load_builder_settings()
    resolved_slots = resolve_prompt_slots(stage=stage, difficulty=difficulty, family_id=family_id)
    sections = _render_runtime_constraints(resolved_slots)
    sections.extend(
        [
            "## Resolved Slot Contract",
            "```json",
            json.dumps(resolved_slots, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return "\n".join(sections)
