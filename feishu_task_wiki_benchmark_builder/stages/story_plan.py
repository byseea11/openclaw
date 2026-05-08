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
from .task_id_audit import validate_story_plan_task_ids


STORY_PLAN_REQUIRED_SECTIONS = [
    "story_id",
    "case_id",
    "family_id",
    "task",
    "actors",
    "task_actor_layout",
    "state_changes",
    "message_beats",
    "planned_probe_queries",
]


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


def _build_story_plan_output_contract(*, case_context: dict[str, Any]) -> dict[str, Any]:
    task_id = str(case_context["task_id"])
    case_id = str(case_context["case_id"])
    family_id = str(case_context["family_id"])
    return {
        "artifact_name": "story_plan",
        "return_format": "Return exactly one complete JSON object. Do not wrap it in markdown or a story_plan key.",
        "strict_required_top_level_fields": STORY_PLAN_REQUIRED_SECTIONS,
        "canonical_top_level_shape": {
            "story_id": f"story_{case_id}",
            "case_id": case_id,
            "family_id": family_id,
            "task": {
                "task_id": task_id,
                "task_name": "short enterprise task name",
                "role": "target_task",
            },
            "actors": [
                {
                    "actor_id": "stable_lowercase_id",
                    "display_name": "Human readable unique name",
                    "role": "role in the scenario",
                }
            ],
            "task_actor_layout": {
                "target_task_id": task_id,
                "shared_actors": ["actor_id values when applicable"],
                "actor_task_roles": [
                    {
                        "actor_id": "must reference actors[].actor_id",
                        "task_id": task_id,
                        "role": "task-specific role",
                    }
                ],
            },
            "state_changes": [
                {
                    "task_id": task_id,
                    "field": "owner_or_blocker_or_window_or_status",
                    "sequence": [{"value": "current or historical value", "status": "current"}],
                }
            ],
            "message_beats": [
                {
                    "beat_id": "beat_001",
                    "purpose": "why this evidence message exists",
                    "speaker_actor_id": "must reference actors[].actor_id",
                    "session_id": "stable session id such as main_chat or thread_release",
                    "message_intent": "the concrete planned evidence or distractor statement",
                }
            ],
            "planned_probe_queries": [
                {
                    "query": f"{task_id} current-state question being tested",
                    "expected_good_behavior": "specific answer behavior; must not duplicate query text",
                }
            ],
        },
        "validation_rules": [
            "task is mandatory; do not return only actors/task_actor_layout.",
            "actors, state_changes, message_beats, and planned_probe_queries must be non-empty arrays.",
            "Every message_beats[].speaker_actor_id must reference an actor_id from actors.",
            "Every planned_probe_queries[].query must explicitly mention the exact case_context.task_id.",
            "planned_probe_queries[].expected_good_behavior must describe the answer, not repeat the query.",
            "Use the exact case_id, family_id, and task_id from case_context.",
        ],
    }


def _build_story_plan_user_payload(*, case_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_context": case_context,
        "output_contract": _build_story_plan_output_contract(case_context=case_context),
    }


def _build_story_plan_repair_user_payload(
    *,
    case_context: dict[str, Any],
    invalid_payload: dict[str, Any],
    validation_error: ValidationError,
) -> dict[str, Any]:
    return {
        "case_context": case_context,
        "output_contract": _build_story_plan_output_contract(case_context=case_context),
        "repair_context": {
            "validation_error": str(validation_error),
            "invalid_payload": invalid_payload,
            "repair_instruction": (
                "Rewrite the invalid payload into a complete valid story_plan JSON object. "
                "Preserve any useful actors or task_actor_layout content, but add or correct every "
                "missing required top-level section. All target task references must use the exact "
                "case_context.task_id; do not invent or preserve a different FEISHU task id for the "
                "target task. Every planned_probe_queries[].query must mention case_context.task_id. "
                "Return only the repaired JSON object."
            ),
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
        validate_story_plan_task_ids(story_plan=validated, case_context=case_context)
    except ValidationError as exc:
        repair_payload = _build_story_plan_repair_user_payload(
            case_context=case_context,
            invalid_payload=result.payload,
            validation_error=exc,
        )
        repair_result = client.complete_json(
            stage="story-plan-repair",
            system_prompt=system_prompt,
            user_payload=repair_payload,
        )
        try:
            validated = validate_story_plan(repair_result.payload)
            validate_story_plan_task_ids(story_plan=validated, case_context=case_context)
        except ValidationError as repair_exc:
            raise ModelPayloadValidationError(
                f"story-plan payload validation failed after repair: {repair_exc}",
                stage="story-plan",
                payload={
                    "initial_validation_error": str(exc),
                    "initial_invalid_payload": result.payload,
                    "repair_validation_error": str(repair_exc),
                    "repair_invalid_payload": repair_result.payload,
                },
                backend=repair_result.backend,
                model=repair_result.model,
                base_url=repair_result.base_url,
                duration_ms=repair_result.duration_ms,
            ) from repair_exc
        return validated, [
            build_model_call_log_entry(
                stage="story-plan",
                result=result,
                case_id=str(case_context["case_id"]),
                artifact_path="input/story_plan.json",
            ),
            build_model_call_log_entry(
                stage="story-plan-repair",
                result=repair_result,
                case_id=str(case_context["case_id"]),
                artifact_path="input/story_plan.json",
            ),
        ]
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
