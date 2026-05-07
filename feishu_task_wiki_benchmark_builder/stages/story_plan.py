from __future__ import annotations

from typing import Any

from ..config import SKILLS_DIR, WORKFLOW_SKILL
from ..io import read_text
from ..llm import (
    BuilderModelClient,
    ModelPayloadValidationError,
    build_model_call_log_entry,
    create_model_client,
)
from ..prompt_loader import FAMILY_CONTEXT_SKILL_PATHS
from ..prompt_settings_renderer import render_prompt_settings_summary
from ..schemas import ValidationError, validate_story_plan


def _build_internal_story_scaffold_system_prompt(*, family_id: str, difficulty: str) -> str:
    paths = [
        WORKFLOW_SKILL,
        SKILLS_DIR / "task-actor-layout.md",
        SKILLS_DIR / "case-world.md",
        SKILLS_DIR / "state-trajectory.md",
        SKILLS_DIR / "coverage-spec.md",
        SKILLS_DIR / "story-beats.md",
        SKILLS_DIR / "conversation-plan.md",
        FAMILY_CONTEXT_SKILL_PATHS[family_id],
    ]
    sections = [
        "你正在运行 Feishu Task Wiki benchmark builder 的内部 Phase 1 scaffold 生成器。",
        "这个内部生成器只服务细分 stage 的中间结构，不是公开 CLI stage。",
    ]
    for path in paths:
        sections.append(f"## Skill Source: {path.as_posix()}")
        sections.append(read_text(path))
    sections.append(render_prompt_settings_summary(stage="conversation-plan", difficulty=difficulty, family_id=family_id))
    return "\n\n".join(sections).strip()


def _build_story_plan_user_payload(*, case_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_context": case_context,
        "output_contract": {
            "must_include_sections": [
                "task",
                "actors",
                "task_actor_layout",
                "state_changes",
                "message_beats",
                "planned_probe_queries",
            ]
        },
    }


def generate_story_plan(
    *,
    case_context: dict[str, Any],
    model_client: BuilderModelClient | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    client = model_client or create_model_client()
    system_prompt = _build_internal_story_scaffold_system_prompt(
        family_id=str(case_context["family_id"]),
        difficulty=str(case_context["difficulty"]),
    )
    user_payload = _build_story_plan_user_payload(case_context=case_context)
    result = client.complete_json(
        stage="story-plan",
        system_prompt=system_prompt,
        user_payload=user_payload,
    )
    try:
        validated = validate_story_plan(result.payload)
    except ValidationError as exc:
        raise ModelPayloadValidationError(
            f"story-plan payload validation failed: {exc}",
            stage="story-plan",
            payload=result.payload,
            backend=result.backend,
            model=result.model,
            base_url=result.base_url,
            duration_ms=result.duration_ms,
        ) from exc
    return validated, [
        build_model_call_log_entry(
            stage="story-plan",
            result=result,
            case_id=str(case_context["case_id"]),
            artifact_path="input/story_plan.json",
        )
    ]


def build_story_plan(
    *,
    case_context: dict[str, Any],
    model_client: BuilderModelClient | None = None,
) -> dict[str, Any]:
    artifact, _ = generate_story_plan(case_context=case_context, model_client=model_client)
    return artifact
