from __future__ import annotations

from pathlib import Path

from .builder_settings import resolve_default_difficulty
from .config import FORMAL_FAMILY_IDS, SKILLS_DIR, WORKFLOW_SKILL
from .io import read_text
from .prompt_settings_renderer import render_prompt_settings_summary


BASE_STAGE_SKILL_PATHS: dict[str, tuple[Path, ...]] = {
    "case-context": (
        WORKFLOW_SKILL,
        SKILLS_DIR / "family-selection.md",
        SKILLS_DIR / "capability-brief.md",
        SKILLS_DIR / "case-world.md",
    ),
    "task-actor-layout": (
        WORKFLOW_SKILL,
        SKILLS_DIR / "task-actor-layout.md",
    ),
    "case-world": (
        WORKFLOW_SKILL,
        SKILLS_DIR / "case-world.md",
    ),
    "story-beats": (
        WORKFLOW_SKILL,
        SKILLS_DIR / "story-beats.md",
    ),
    "conversation-plan": (
        WORKFLOW_SKILL,
        SKILLS_DIR / "conversation-plan.md",
    ),
    "story-plan": (
        WORKFLOW_SKILL,
        SKILLS_DIR / "task-actor-layout.md",
        SKILLS_DIR / "case-world.md",
        SKILLS_DIR / "story-beats.md",
        SKILLS_DIR / "conversation-plan.md",
        SKILLS_DIR / "story-plan.md",
    ),
}

FAMILY_CONTEXT_SKILL_PATHS: dict[str, Path] = {
    "anti_interference": SKILLS_DIR / "anti-interference-context.md",
    "contradiction_update": SKILLS_DIR / "contradiction-update-context.md",
    "evidence_dependency_reasoning": SKILLS_DIR / "evidence-dependency-context.md",
}

def list_stage_prompt_sources(stage: str, family_id: str | None = None) -> tuple[Path, ...]:
    try:
        base_paths = BASE_STAGE_SKILL_PATHS[stage]
    except KeyError as exc:
        raise ValueError(f"Unsupported prompt stage: {stage}") from exc
    if family_id is not None and family_id not in FORMAL_FAMILY_IDS:
        raise ValueError(f"Unsupported family_id for prompt stage: {family_id}")
    if stage == "case-context":
        if family_id is not None:
            return base_paths + (FAMILY_CONTEXT_SKILL_PATHS[family_id],)
        return base_paths + tuple(FAMILY_CONTEXT_SKILL_PATHS[family] for family in FORMAL_FAMILY_IDS)
    if stage == "story-plan" and family_id is not None:
        return base_paths + (FAMILY_CONTEXT_SKILL_PATHS[family_id],)
    if stage == "story-plan":
        return base_paths + tuple(FAMILY_CONTEXT_SKILL_PATHS[family] for family in FORMAL_FAMILY_IDS)
    return base_paths


def build_stage_system_prompt(
    stage: str,
    family_id: str | None = None,
    *,
    difficulty: str | None = None,
) -> str:
    if difficulty is None:
        difficulty = resolve_default_difficulty()
    sections = [
        f"你正在运行 Feishu Task Wiki benchmark builder 的 {stage} 阶段。",
        "以下内容来自 code-side skills，是当前阶段唯一的运行时约束来源。",
    ]
    for path in list_stage_prompt_sources(stage, family_id=family_id):
        sections.append(f"## Skill Source: {path.as_posix()}")
        sections.append(read_text(path))
    sections.append(render_prompt_settings_summary(stage=stage, difficulty=difficulty, family_id=family_id))
    return "\n\n".join(sections).strip()
