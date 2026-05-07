from __future__ import annotations

from typing import Any

from ..config import FORMAL_FAMILY_IDS
from ..family_catalog import FAMILY_CATALOG, ordered_family_ids
from ..llm import (
    BuilderModelClient,
    ModelPayloadValidationError,
    build_model_call_log_entry,
    create_model_client,
)
from ..prompt_loader import build_stage_system_prompt
from ..schemas import ValidationError, validate_case_context
from .common import build_case_id, build_task_id, normalize_seed


def _build_case_context_user_payload(
    *,
    seed: int,
    requested_family_id: str | None,
    difficulty: str,
    comparison_target: str,
) -> dict[str, Any]:
    families = {}
    for family_id in ordered_family_ids():
        definition = FAMILY_CATALOG[family_id]
        families[family_id] = {
            "benchmark_requirement_name": definition.benchmark_requirement_name,
            "benchmark_requirement_summary": definition.benchmark_requirement_summary,
            "report_display_name": definition.report_display_name,
            "capability_under_test": definition.capability_under_test,
            "why_memory_systems_may_fail": definition.why_memory_systems_may_fail,
            "generation_rules": definition.generation_rules,
            "required_case_structure": definition.required_case_structure,
            "probe_strategy": definition.probe_strategy,
            "expected_good_system_behavior": definition.expected_good_system_behavior,
        }
    return {
        "seed": seed,
        "requested_family_id": requested_family_id,
        "difficulty": difficulty,
        "comparison_target": comparison_target,
        "formal_families": families,
        "output_contract": {
            "must_include": [
                "family_id",
                "benchmark_requirement_name",
                "benchmark_requirement_summary",
                "report_display_name",
                "capability_under_test",
                "why_memory_systems_may_fail",
                "generation_rules",
                "required_case_structure",
                "probe_strategy",
                "expected_good_system_behavior",
                "organization",
                "team",
                "business_goal",
                "scenario_summary",
                "family_fit_explanation",
            ]
        },
    }


def _merge_model_case_context_with_system_fields(
    *,
    model_payload: dict[str, Any],
    seed: int,
    difficulty: str,
    comparison_target: str,
) -> dict[str, Any]:
    family_id_value = model_payload.get("family_id")
    if not isinstance(family_id_value, str) or not family_id_value.strip():
        raise ValidationError("case_context.family_id must be a non-empty string")
    family_id = family_id_value.strip()
    if family_id not in FORMAL_FAMILY_IDS:
        raise ValidationError("case_context.family_id must be a formal family id")
    merged = dict(model_payload)
    merged["case_id"] = build_case_id(seed, family_id)
    merged["task_id"] = build_task_id(seed)
    merged["seed"] = seed
    merged["difficulty"] = difficulty
    merged["comparison_target"] = comparison_target
    return merged


def generate_case_context(
    *,
    seed: int | None,
    requested_family_id: str | None,
    difficulty: str,
    comparison_target: str,
    model_client: BuilderModelClient | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    client = model_client or create_model_client()
    normalized_seed = normalize_seed(seed)
    system_prompt = build_stage_system_prompt(
        "spec-generation",
        family_id=requested_family_id,
        difficulty=difficulty,
    )
    user_payload = _build_case_context_user_payload(
        seed=normalized_seed,
        requested_family_id=requested_family_id,
        difficulty=difficulty,
        comparison_target=comparison_target,
    )
    result = client.complete_json(
        stage="case-context",
        system_prompt=system_prompt,
        user_payload=user_payload,
    )
    try:
        validated = validate_case_context(
            _merge_model_case_context_with_system_fields(
                model_payload=result.payload,
                seed=normalized_seed,
                difficulty=difficulty,
                comparison_target=comparison_target,
            )
        )
    except ValidationError as exc:
        raise ModelPayloadValidationError(
            f"case-context payload validation failed: {exc}",
            stage="case-context",
            payload=result.payload,
            backend=result.backend,
            model=result.model,
            base_url=result.base_url,
            duration_ms=result.duration_ms,
        ) from exc
    return validated, [
        build_model_call_log_entry(
            stage="case-context",
            result=result,
            case_id=str(validated["case_id"]),
            artifact_path="input/case_context.json",
        )
    ]


def build_case_context(
    *,
    seed: int | None,
    requested_family_id: str | None,
    difficulty: str,
    comparison_target: str,
    model_client: BuilderModelClient | None = None,
) -> dict[str, Any]:
    artifact, _ = generate_case_context(
        seed=seed,
        requested_family_id=requested_family_id,
        difficulty=difficulty,
        comparison_target=comparison_target,
        model_client=model_client,
    )
    return artifact
