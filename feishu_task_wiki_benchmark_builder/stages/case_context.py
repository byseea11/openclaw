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
from .task_id_audit import extract_task_ids


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
        "canonical_case_fields": {
            "case_id_by_family": {
                family_id: build_case_id(seed, family_id)
                for family_id in ordered_family_ids()
            },
            "task_id": build_task_id(seed),
        },
        "formal_families": families,
        "output_contract": {
            "artifact_name": "case_context",
            "return_format": "Return exactly one complete JSON object. Do not wrap it in markdown or a case_context key.",
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
            ],
            "validation_rules": [
                "If requested_family_id is set, family_id must equal requested_family_id.",
                "Use canonical_case_fields.task_id whenever the scenario mentions the target FEISHU task.",
                "Copy benchmark/capability fields from formal_families[family_id] exactly.",
                "organization, team, business_goal, scenario_summary, and family_fit_explanation must be non-empty.",
            ],
        },
    }


def _build_case_context_repair_user_payload(
    *,
    base_payload: dict[str, Any],
    invalid_payload: dict[str, Any],
    validation_error: ValidationError,
) -> dict[str, Any]:
    return {
        **base_payload,
        "repair_context": {
            "validation_error": str(validation_error),
            "invalid_payload": invalid_payload,
            "repair_instruction": (
                "Rewrite the invalid case context into a complete valid JSON object. "
                "Preserve the chosen family and scenario if they are compatible with the request, "
                "copy missing benchmark/capability fields from formal_families[family_id], and "
                "replace any target-task FEISHU id with canonical_case_fields.task_id. "
                "return only the repaired JSON object."
            ),
        },
    }


def _validate_case_context_task_ids(case_context: dict[str, Any]) -> dict[str, Any]:
    target_task_id = str(case_context["task_id"])
    scenario_ids = extract_task_ids(case_context.get("scenario_summary") or "")
    if scenario_ids and target_task_id not in scenario_ids:
        raise ValidationError(f"case_context.scenario_summary must mention target task_id {target_task_id}")
    family_id = str(case_context["family_id"])
    if family_id in {"private_info_in_official_file", "contradiction_update"}:
        all_ids = extract_task_ids(case_context)
        invalid_ids = sorted(task_id for task_id in all_ids if task_id != target_task_id)
        if invalid_ids:
            raise ValidationError(f"case_context contains undeclared non-target task ids: {invalid_ids}")
    return case_context


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
    model_call_entries = [
        build_model_call_log_entry(
            stage="case-context",
            result=result,
            case_id=build_case_id(normalized_seed, str(result.payload.get("family_id") or "unknown")),
            artifact_path="input/case_context.json",
        )
    ]
    try:
        validated = _validate_case_context_task_ids(
            validate_case_context(
                _merge_model_case_context_with_system_fields(
                    model_payload=result.payload,
                    seed=normalized_seed,
                    difficulty=difficulty,
                    comparison_target=comparison_target,
                )
            )
        )
    except ValidationError as exc:
        repair_payload = _build_case_context_repair_user_payload(
            base_payload=user_payload,
            invalid_payload=result.payload,
            validation_error=exc,
        )
        repair_result = client.complete_json(
            stage="case-context-repair",
            system_prompt=system_prompt,
            user_payload=repair_payload,
        )
        model_call_entries.append(
            build_model_call_log_entry(
                stage="case-context-repair",
                result=repair_result,
                case_id=build_case_id(normalized_seed, str(repair_result.payload.get("family_id") or "unknown")),
                artifact_path="input/case_context.json",
            )
        )
        try:
            validated = _validate_case_context_task_ids(
                validate_case_context(
                    _merge_model_case_context_with_system_fields(
                        model_payload=repair_result.payload,
                        seed=normalized_seed,
                        difficulty=difficulty,
                        comparison_target=comparison_target,
                    )
                )
            )
        except ValidationError as repair_exc:
            raise ModelPayloadValidationError(
                f"case-context payload validation failed after repair: {repair_exc}",
                stage="case-context",
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
    return validated, model_call_entries


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
