from __future__ import annotations

from typing import Any

from ..llm import (
    BuilderModelClient,
    ModelPayloadValidationError,
    build_model_call_log_entry,
    create_model_client,
)
from ..prompt import build_story_plan_system_prompt
from ..schemas import ValidationError, validate_story_plan


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
    system_prompt = build_story_plan_system_prompt(
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
