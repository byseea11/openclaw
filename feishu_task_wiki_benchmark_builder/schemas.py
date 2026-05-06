from __future__ import annotations

from typing import Any

from .config import BASELINE_MODES, FORMAL_FAMILY_IDS


class ValidationError(ValueError):
    """Raised when an artifact does not match the expected schema."""


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be an object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{path} must be a list")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path} must be a non-empty string")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{path} must be a boolean")
    return value


def _require_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{path} must be a number")
    return value


def validate_family_selection(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "family_selection")
    family_id = _require_string(obj.get("family_id"), "family_selection.family_id")
    if family_id not in FORMAL_FAMILY_IDS:
        raise ValidationError("family_selection.family_id must be a formal family id")
    return {
        "family_id": family_id,
        "selection_mode": _require_string(obj.get("selection_mode"), "family_selection.selection_mode"),
        "selection_reason": _require_string(obj.get("selection_reason"), "family_selection.selection_reason"),
        "seed": int(_require_number(obj.get("seed"), "family_selection.seed")),
    }


def validate_memory_capability_brief(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "memory_capability_brief")
    family_id = _require_string(obj.get("family_id"), "memory_capability_brief.family_id")
    if family_id not in FORMAL_FAMILY_IDS:
        raise ValidationError("memory_capability_brief.family_id must be a formal family id")
    return {
        "family_id": family_id,
        "benchmark_requirement_name": _require_string(
            obj.get("benchmark_requirement_name"),
            "memory_capability_brief.benchmark_requirement_name",
        ),
        "benchmark_requirement_summary": _require_string(
            obj.get("benchmark_requirement_summary"),
            "memory_capability_brief.benchmark_requirement_summary",
        ),
        "report_display_name": _require_string(
            obj.get("report_display_name"),
            "memory_capability_brief.report_display_name",
        ),
        "capability_under_test": _require_string(
            obj.get("capability_under_test"),
            "memory_capability_brief.capability_under_test",
        ),
        "why_memory_systems_may_fail": _require_string(
            obj.get("why_memory_systems_may_fail"),
            "memory_capability_brief.why_memory_systems_may_fail",
        ),
        "generation_rules": [
            _require_string(item, f"memory_capability_brief.generation_rules[{index}]")
            for index, item in enumerate(
                _require_list(obj.get("generation_rules"), "memory_capability_brief.generation_rules"),
                start=1,
            )
        ],
        "required_case_structure": [
            _require_string(item, f"memory_capability_brief.required_case_structure[{index}]")
            for index, item in enumerate(
                _require_list(
                    obj.get("required_case_structure"),
                    "memory_capability_brief.required_case_structure",
                ),
                start=1,
            )
        ],
        "probe_strategy": [
            _require_string(item, f"memory_capability_brief.probe_strategy[{index}]")
            for index, item in enumerate(
                _require_list(obj.get("probe_strategy"), "memory_capability_brief.probe_strategy"),
                start=1,
            )
        ],
        "expected_good_system_behavior": [
            _require_string(item, f"memory_capability_brief.expected_good_system_behavior[{index}]")
            for index, item in enumerate(
                _require_list(
                    obj.get("expected_good_system_behavior"),
                    "memory_capability_brief.expected_good_system_behavior",
                ),
                start=1,
            )
        ],
    }


def validate_case_spec(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "case_spec")
    family_id = _require_string(obj.get("family_id"), "case_spec.family_id")
    if family_id not in FORMAL_FAMILY_IDS:
        raise ValidationError("case_spec.family_id must be a formal family id")
    return {
        "case_id": _require_string(obj.get("case_id"), "case_spec.case_id"),
        "task_id": _require_string(obj.get("task_id"), "case_spec.task_id"),
        "seed": int(_require_number(obj.get("seed"), "case_spec.seed")),
        "difficulty": _require_string(obj.get("difficulty"), "case_spec.difficulty"),
        "comparison_target": _require_string(obj.get("comparison_target"), "case_spec.comparison_target"),
        "family_id": family_id,
    }


def validate_case_world(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "case_world")
    return {
        "case_id": _require_string(obj.get("case_id"), "case_world.case_id"),
        "family_id": _require_string(obj.get("family_id"), "case_world.family_id"),
        "organization": _require_string(obj.get("organization"), "case_world.organization"),
        "team": _require_string(obj.get("team"), "case_world.team"),
        "business_goal": _require_string(obj.get("business_goal"), "case_world.business_goal"),
        "scenario_summary": _require_string(obj.get("scenario_summary"), "case_world.scenario_summary"),
        "family_fit_explanation": _require_string(
            obj.get("family_fit_explanation"),
            "case_world.family_fit_explanation",
        ),
    }


def validate_story_plan(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "story_plan")
    tasks = _require_list(obj.get("tasks"), "story_plan.tasks")
    actors = _require_list(obj.get("actors"), "story_plan.actors")
    task_actor_layout = _require_dict(obj.get("task_actor_layout"), "story_plan.task_actor_layout")
    state_changes = _require_list(obj.get("state_changes"), "story_plan.state_changes")
    message_beats = _require_list(obj.get("message_beats"), "story_plan.message_beats")
    planned_probe_queries = _require_list(
        obj.get("planned_probe_queries"),
        "story_plan.planned_probe_queries",
    )
    if not tasks:
        raise ValidationError("story_plan.tasks must not be empty")
    if not actors:
        raise ValidationError("story_plan.actors must not be empty")
    if not state_changes:
        raise ValidationError("story_plan.state_changes must not be empty")
    if not message_beats:
        raise ValidationError("story_plan.message_beats must not be empty")
    if not planned_probe_queries:
        raise ValidationError("story_plan.planned_probe_queries must not be empty")
    for index, item in enumerate(planned_probe_queries, start=1):
        probe = _require_dict(item, f"story_plan.planned_probe_queries[{index}]")
        query = _require_string(probe.get("query"), f"story_plan.planned_probe_queries[{index}].query")
        expected = _require_string(
            probe.get("expected_good_behavior"),
            f"story_plan.planned_probe_queries[{index}].expected_good_behavior",
        )
        if query.strip() == expected.strip():
            raise ValidationError(
                "story_plan.planned_probe_queries expected_good_behavior must not duplicate the query"
            )
    return {
        "story_id": _require_string(obj.get("story_id"), "story_plan.story_id"),
        "case_id": _require_string(obj.get("case_id"), "story_plan.case_id"),
        "family_id": _require_string(obj.get("family_id"), "story_plan.family_id"),
        "tasks": tasks,
        "actors": actors,
        "task_actor_layout": task_actor_layout,
        "state_changes": state_changes,
        "message_beats": message_beats,
        "planned_probe_queries": planned_probe_queries,
    }


def validate_command_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValidationError("command_plan must not be empty")
    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        obj = _require_dict(row, f"command_plan[{index}]")
        validated.append(
            {
                "command_id": _require_string(obj.get("command_id"), f"command_plan[{index}].command_id"),
                "beat_id": _require_string(obj.get("beat_id"), f"command_plan[{index}].beat_id"),
                "actor_id": _require_string(obj.get("actor_id"), f"command_plan[{index}].actor_id"),
                "session_id": _require_string(obj.get("session_id"), f"command_plan[{index}].session_id"),
                "message_text": _require_string(obj.get("message_text"), f"command_plan[{index}].message_text"),
            }
        )
    return validated


def validate_pre_annotation_report(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "pre_annotation_validation_report")
    return {
        "case_id": _require_string(obj.get("case_id"), "pre_annotation_validation_report.case_id"),
        "is_valid": _require_bool(obj.get("is_valid"), "pre_annotation_validation_report.is_valid"),
        "checks": _require_list(obj.get("checks"), "pre_annotation_validation_report.checks"),
    }


def validate_annotation_gold_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValidationError("annotation_gold rows must not be empty")
    return rows


def validate_query_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "query_benchmark")
    queries = _require_list(obj.get("queries"), "query_benchmark.queries")
    if not queries:
        raise ValidationError("query_benchmark.queries must not be empty")
    return obj


def validate_replay_eval(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "replay_eval")
    metrics = _require_dict(obj.get("metrics"), "replay_eval.metrics")
    for key in ("query_success_rate", "evidence_trace_rate", "current_state_accuracy"):
        _require_number(metrics.get(key), f"replay_eval.metrics.{key}")
    return obj


def validate_baseline_eval(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "baseline_eval")
    rows = _require_list(obj.get("results"), "baseline_eval.results")
    if not rows:
        raise ValidationError("baseline_eval.results must not be empty")
    seen_modes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        item = _require_dict(row, f"baseline_eval.results[{index}]")
        mode = _require_string(item.get("baseline_mode"), f"baseline_eval.results[{index}].baseline_mode")
        if mode not in BASELINE_MODES:
            raise ValidationError("baseline_eval.results baseline_mode must be a formal baseline mode")
        seen_modes.add(mode)
    if seen_modes != set(BASELINE_MODES):
        raise ValidationError("baseline_eval.results must include every formal baseline mode")
    return obj


def validate_value_eval(payload: dict[str, Any]) -> dict[str, Any]:
    return _require_dict(payload, "value_eval")
