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


def default_simulated_open_id(person_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in person_id.strip())
    return f"ou_sim_{safe}"


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


def validate_case_context(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "case_context")
    family_id = _require_string(obj.get("family_id"), "case_context.family_id")
    if family_id not in FORMAL_FAMILY_IDS:
        raise ValidationError("case_context.family_id must be a formal family id")
    return {
        "family_id": family_id,
        "benchmark_requirement_name": _require_string(
            obj.get("benchmark_requirement_name"),
            "case_context.benchmark_requirement_name",
        ),
        "benchmark_requirement_summary": _require_string(
            obj.get("benchmark_requirement_summary"),
            "case_context.benchmark_requirement_summary",
        ),
        "report_display_name": _require_string(
            obj.get("report_display_name"),
            "case_context.report_display_name",
        ),
        "capability_under_test": _require_string(
            obj.get("capability_under_test"),
            "case_context.capability_under_test",
        ),
        "why_memory_systems_may_fail": _require_string(
            obj.get("why_memory_systems_may_fail"),
            "case_context.why_memory_systems_may_fail",
        ),
        "generation_rules": [
            _require_string(item, f"case_context.generation_rules[{index}]")
            for index, item in enumerate(
                _require_list(obj.get("generation_rules"), "case_context.generation_rules"),
                start=1,
            )
        ],
        "required_case_structure": [
            _require_string(item, f"case_context.required_case_structure[{index}]")
            for index, item in enumerate(
                _require_list(obj.get("required_case_structure"), "case_context.required_case_structure"),
                start=1,
            )
        ],
        "probe_strategy": [
            _require_string(item, f"case_context.probe_strategy[{index}]")
            for index, item in enumerate(
                _require_list(obj.get("probe_strategy"), "case_context.probe_strategy"),
                start=1,
            )
        ],
        "expected_good_system_behavior": [
            _require_string(item, f"case_context.expected_good_system_behavior[{index}]")
            for index, item in enumerate(
                _require_list(
                    obj.get("expected_good_system_behavior"),
                    "case_context.expected_good_system_behavior",
                ),
                start=1,
            )
        ],
        "case_id": _require_string(obj.get("case_id"), "case_context.case_id"),
        "task_id": _require_string(obj.get("task_id"), "case_context.task_id"),
        "seed": int(_require_number(obj.get("seed"), "case_context.seed")),
        "difficulty": _require_string(obj.get("difficulty"), "case_context.difficulty"),
        "comparison_target": _require_string(
            obj.get("comparison_target"),
            "case_context.comparison_target",
        ),
        "organization": _require_string(obj.get("organization"), "case_context.organization"),
        "team": _require_string(obj.get("team"), "case_context.team"),
        "business_goal": _require_string(obj.get("business_goal"), "case_context.business_goal"),
        "scenario_summary": _require_string(
            obj.get("scenario_summary"),
            "case_context.scenario_summary",
        ),
        "family_fit_explanation": _require_string(
            obj.get("family_fit_explanation"),
            "case_context.family_fit_explanation",
        ),
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


def _validate_session_roster(items: list[Any], path: str) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items, start=1):
        obj = _require_dict(item, f"{path}[{index}]")
        session_id = _require_string(obj.get("session_id"), f"{path}[{index}].session_id")
        if session_id in seen_ids:
            raise ValidationError(f"{path}[{index}].session_id must be unique")
        seen_ids.add(session_id)
        sessions.append(
            {
                "session_id": session_id,
                "session_type": _require_string(obj.get("session_type"), f"{path}[{index}].session_type"),
                "title": _require_string(obj.get("title"), f"{path}[{index}].title"),
                "session_purpose": _require_string(
                    obj.get("session_purpose"),
                    f"{path}[{index}].session_purpose",
                ),
            }
        )
    if not sessions:
        raise ValidationError(f"{path} must not be empty")
    return sessions


def validate_task_actor_layout_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "task_actor_layout_artifact")
    actors = _require_list(obj.get("actors"), "task_actor_layout_artifact.actors")
    seen_actor_ids: set[str] = set()
    seen_display_names: set[str] = set()
    validated_actors: list[dict[str, Any]] = []
    for index, item in enumerate(actors, start=1):
        actor = _require_dict(item, f"task_actor_layout_artifact.actors[{index}]")
        actor_id = _require_string(actor.get("actor_id"), f"task_actor_layout_artifact.actors[{index}].actor_id")
        display_name = _require_string(
            actor.get("display_name"),
            f"task_actor_layout_artifact.actors[{index}].display_name",
        )
        if actor_id in seen_actor_ids:
            raise ValidationError("task_actor_layout_artifact.actors actor_id must be unique")
        if display_name in seen_display_names:
            raise ValidationError("task_actor_layout_artifact.actors display_name must be unique")
        seen_actor_ids.add(actor_id)
        seen_display_names.add(display_name)
        validated_actors.append(actor)
    return {
        "case_id": _require_string(obj.get("case_id"), "task_actor_layout_artifact.case_id"),
        "family_id": _require_string(obj.get("family_id"), "task_actor_layout_artifact.family_id"),
        "task_id": _require_string(obj.get("task_id"), "task_actor_layout_artifact.task_id"),
        "actors": validated_actors,
        "task_actor_layout": _require_dict(
            obj.get("task_actor_layout"),
            "task_actor_layout_artifact.task_actor_layout",
        ),
    }


def validate_case_world_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "case_world_artifact")
    return {
        "case_id": _require_string(obj.get("case_id"), "case_world_artifact.case_id"),
        "family_id": _require_string(obj.get("family_id"), "case_world_artifact.family_id"),
        "task_id": _require_string(obj.get("task_id"), "case_world_artifact.task_id"),
        "organization": _require_string(obj.get("organization"), "case_world_artifact.organization"),
        "team": _require_string(obj.get("team"), "case_world_artifact.team"),
        "business_goal": _require_string(obj.get("business_goal"), "case_world_artifact.business_goal"),
        "scenario_summary": _require_string(
            obj.get("scenario_summary"),
            "case_world_artifact.scenario_summary",
        ),
        "family_fit_explanation": _require_string(
            obj.get("family_fit_explanation"),
            "case_world_artifact.family_fit_explanation",
        ),
        "source_sessions": _validate_session_roster(
            _require_list(obj.get("source_sessions"), "case_world_artifact.source_sessions"),
            "case_world_artifact.source_sessions",
        ),
    }


def validate_characters(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "characters")
    rows = _require_list(obj.get("characters"), "characters.characters")
    if not rows:
        raise ValidationError("characters.characters must not be empty")
    validated: list[dict[str, Any]] = []
    seen_person_ids: set[str] = set()
    seen_open_ids: set[str] = set()
    for index, item in enumerate(rows, start=1):
        row = _require_dict(item, f"characters.characters[{index}]")
        person_id = _require_string(row.get("person_id"), f"characters.characters[{index}].person_id")
        actor_slot_id = _require_string(
            row.get("actor_slot_id"),
            f"characters.characters[{index}].actor_slot_id",
        )
        simulated_open_id = _require_string(
            row.get("simulated_open_id"),
            f"characters.characters[{index}].simulated_open_id",
        )
        expected_open_id = default_simulated_open_id(person_id)
        if simulated_open_id != expected_open_id:
            raise ValidationError(
                f"characters.characters[{index}].simulated_open_id must be {expected_open_id}"
            )
        if person_id in seen_person_ids:
            raise ValidationError("characters.characters person_id must be unique")
        if simulated_open_id in seen_open_ids:
            raise ValidationError("characters.characters simulated_open_id must be unique")
        seen_person_ids.add(person_id)
        seen_open_ids.add(simulated_open_id)
        validated.append(
            {
                "person_id": person_id,
                "actor_slot_id": actor_slot_id,
                "simulated_open_id": simulated_open_id,
                "name": _require_string(row.get("name"), f"characters.characters[{index}].name"),
                "department": _require_string(row.get("department"), f"characters.characters[{index}].department"),
                "role": _require_string(row.get("role"), f"characters.characters[{index}].role"),
                "task_ids": [
                    _require_string(task_id, f"characters.characters[{index}].task_ids[{task_index}]")
                    for task_index, task_id in enumerate(
                        _require_list(row.get("task_ids"), f"characters.characters[{index}].task_ids"),
                        start=1,
                    )
                ],
                "default_channels": [
                    _require_string(channel, f"characters.characters[{index}].default_channels[{channel_index}]")
                    for channel_index, channel in enumerate(
                        _require_list(
                            row.get("default_channels"),
                            f"characters.characters[{index}].default_channels",
                        ),
                        start=1,
                    )
                ],
                "profile": _require_string(row.get("profile"), f"characters.characters[{index}].profile"),
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "characters.case_id"),
        "family_id": _require_string(obj.get("family_id"), "characters.family_id"),
        "task_id": _require_string(obj.get("task_id"), "characters.task_id"),
        "characters": validated,
    }


def validate_actor_registry(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "actor_registry")
    rows = _require_list(obj.get("actors"), "actor_registry.actors")
    if not rows:
        raise ValidationError("actor_registry.actors must not be empty")
    validated: list[dict[str, Any]] = []
    seen_person_ids: set[str] = set()
    for index, item in enumerate(rows, start=1):
        row = _require_dict(item, f"actor_registry.actors[{index}]")
        person_id = _require_string(row.get("person_id"), f"actor_registry.actors[{index}].person_id")
        simulated_open_id = _require_string(
            row.get("simulated_open_id"),
            f"actor_registry.actors[{index}].simulated_open_id",
        )
        expected_open_id = default_simulated_open_id(person_id)
        if simulated_open_id != expected_open_id:
            raise ValidationError(f"actor_registry.actors[{index}].simulated_open_id must be {expected_open_id}")
        if person_id in seen_person_ids:
            raise ValidationError("actor_registry.actors person_id must be unique")
        seen_person_ids.add(person_id)
        validated.append(
            {
                "person_id": person_id,
                "simulated_open_id": simulated_open_id,
                "name": _require_string(row.get("name"), f"actor_registry.actors[{index}].name"),
                "department": _require_string(row.get("department"), f"actor_registry.actors[{index}].department"),
                "role": _require_string(row.get("role"), f"actor_registry.actors[{index}].role"),
                "default_channels": [
                    _require_string(channel, f"actor_registry.actors[{index}].default_channels[{channel_index}]")
                    for channel_index, channel in enumerate(
                        _require_list(
                            row.get("default_channels"),
                            f"actor_registry.actors[{index}].default_channels",
                        ),
                        start=1,
                    )
                ],
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "actor_registry.case_id"),
        "family_id": _require_string(obj.get("family_id"), "actor_registry.family_id"),
        "task_id": str(obj.get("task_id") or ""),
        "actors": validated,
    }


def validate_story_beats_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "story_beats_artifact")
    beats = _require_list(obj.get("beats"), "story_beats_artifact.beats")
    if not beats:
        raise ValidationError("story_beats_artifact.beats must not be empty")
    validated_beats: list[dict[str, Any]] = []
    for index, item in enumerate(beats, start=1):
        beat = _require_dict(item, f"story_beats_artifact.beats[{index}]")
        validated_beats.append(
            {
                "beat_id": _require_string(beat.get("beat_id"), f"story_beats_artifact.beats[{index}].beat_id"),
                "target_session_id": _require_string(
                    beat.get("target_session_id"),
                    f"story_beats_artifact.beats[{index}].target_session_id",
                ),
                "benchmark_role": _require_string(
                    beat.get("benchmark_role"),
                    f"story_beats_artifact.beats[{index}].benchmark_role",
                ),
                "description": _require_string(
                    beat.get("description"),
                    f"story_beats_artifact.beats[{index}].description",
                ),
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "story_beats_artifact.case_id"),
        "family_id": _require_string(obj.get("family_id"), "story_beats_artifact.family_id"),
        "task_id": _require_string(obj.get("task_id"), "story_beats_artifact.task_id"),
        "beats": validated_beats,
    }


def validate_conversation_plan_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "conversation_plan_artifact")
    turns = _require_list(obj.get("turns"), "conversation_plan_artifact.turns")
    if not turns:
        raise ValidationError("conversation_plan_artifact.turns must not be empty")
    validated_turns: list[dict[str, Any]] = []
    for index, item in enumerate(turns, start=1):
        turn = _require_dict(item, f"conversation_plan_artifact.turns[{index}]")
        beat_id = str(turn.get("beat_id") or "").strip()
        turn_kind = str(turn.get("turn_kind") or ("event_bearing" if beat_id else "context_support"))
        annotation_target = bool(turn.get("annotation_target")) if "annotation_target" in turn else bool(beat_id)
        event_bearing = bool(turn.get("event_bearing")) if "event_bearing" in turn else annotation_target
        if annotation_target and not beat_id:
            raise ValidationError(
                f"conversation_plan_artifact.turns[{index}].beat_id is required for annotation_target turns"
            )
        validated_turns.append(
            {
                "turn_id": _require_string(turn.get("turn_id"), f"conversation_plan_artifact.turns[{index}].turn_id"),
                "beat_id": beat_id,
                "sequence_no": int(
                    _require_number(
                        turn.get("sequence_no"),
                        f"conversation_plan_artifact.turns[{index}].sequence_no",
                    )
                ),
                "session_id": _require_string(
                    turn.get("session_id"),
                    f"conversation_plan_artifact.turns[{index}].session_id",
                ),
                "speaker_actor_id": _require_string(
                    turn.get("speaker_actor_id"),
                    f"conversation_plan_artifact.turns[{index}].speaker_actor_id",
                ),
                "speaker": _require_string(
                    turn.get("speaker"),
                    f"conversation_plan_artifact.turns[{index}].speaker",
                ),
                "planned_message_text": _require_string(
                    turn.get("planned_message_text"),
                    f"conversation_plan_artifact.turns[{index}].planned_message_text",
                ),
                "turn_kind": turn_kind,
                "annotation_target": annotation_target,
                "event_bearing": event_bearing,
                "official_file_ref": str(turn.get("official_file_ref") or ""),
                "private_info_ref": str(turn.get("private_info_ref") or ""),
                "task_relevance_boundary": str(turn.get("task_relevance_boundary") or ""),
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "conversation_plan_artifact.case_id"),
        "family_id": _require_string(obj.get("family_id"), "conversation_plan_artifact.family_id"),
        "task_id": _require_string(obj.get("task_id"), "conversation_plan_artifact.task_id"),
        "sessions": _validate_session_roster(
            _require_list(obj.get("sessions"), "conversation_plan_artifact.sessions"),
            "conversation_plan_artifact.sessions",
        ),
        "turns": validated_turns,
    }


def validate_official_file_plan(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "official_file_plan")
    files: list[dict[str, Any]] = []
    seen_file_refs: set[str] = set()
    for file_index, item in enumerate(_require_list(obj.get("official_files"), "official_file_plan.official_files"), start=1):
        file_obj = _require_dict(item, f"official_file_plan.official_files[{file_index}]")
        file_ref = _require_string(
            file_obj.get("file_ref"),
            f"official_file_plan.official_files[{file_index}].file_ref",
        )
        if file_ref in seen_file_refs:
            raise ValidationError("official_file_plan.official_files file_ref must be unique")
        seen_file_refs.add(file_ref)
        private_info_items: list[dict[str, Any]] = []
        for info_index, info in enumerate(
            _require_list(
                file_obj.get("private_info_items") or [],
                f"official_file_plan.official_files[{file_index}].private_info_items",
            ),
            start=1,
        ):
            info_obj = _require_dict(
                info,
                f"official_file_plan.official_files[{file_index}].private_info_items[{info_index}]",
            )
            private_info_items.append(
                {
                    "private_info_ref": _require_string(
                        info_obj.get("private_info_ref"),
                        f"official_file_plan.official_files[{file_index}].private_info_items[{info_index}].private_info_ref",
                    ),
                    "person_ref": _require_string(
                        info_obj.get("person_ref"),
                        f"official_file_plan.official_files[{file_index}].private_info_items[{info_index}].person_ref",
                    ),
                    "private_info_summary": _require_string(
                        info_obj.get("private_info_summary"),
                        f"official_file_plan.official_files[{file_index}].private_info_items[{info_index}].private_info_summary",
                    ),
                    "must_not_become_task_state": _require_bool(
                        info_obj.get("must_not_become_task_state"),
                        f"official_file_plan.official_files[{file_index}].private_info_items[{info_index}].must_not_become_task_state",
                    ),
                }
            )
        files.append(
            {
                "file_ref": file_ref,
                "file_type": _require_string(
                    file_obj.get("file_type"),
                    f"official_file_plan.official_files[{file_index}].file_type",
                ),
                "title": _require_string(
                    file_obj.get("title"),
                    f"official_file_plan.official_files[{file_index}].title",
                ),
                "authority_level": _require_string(
                    file_obj.get("authority_level"),
                    f"official_file_plan.official_files[{file_index}].authority_level",
                ),
                "official_conclusions": [
                    _require_string(
                        conclusion,
                        f"official_file_plan.official_files[{file_index}].official_conclusions[{conclusion_index}]",
                    )
                    for conclusion_index, conclusion in enumerate(
                        _require_list(
                            file_obj.get("official_conclusions"),
                            f"official_file_plan.official_files[{file_index}].official_conclusions",
                        ),
                        start=1,
                    )
                ],
                "private_info_items": private_info_items,
                "task_relevance_boundaries": [
                    _require_string(
                        boundary,
                        f"official_file_plan.official_files[{file_index}].task_relevance_boundaries[{boundary_index}]",
                    )
                    for boundary_index, boundary in enumerate(
                        _require_list(
                            file_obj.get("task_relevance_boundaries"),
                            f"official_file_plan.official_files[{file_index}].task_relevance_boundaries",
                        ),
                        start=1,
                    )
                ],
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "official_file_plan.case_id"),
        "family_id": _require_string(obj.get("family_id"), "official_file_plan.family_id"),
        "task_id": _require_string(obj.get("task_id"), "official_file_plan.task_id"),
        "official_files": files,
    }


def _normalize_story_plan_actors(actors: list[Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    validated_actors: list[dict[str, Any]] = []
    actor_lookup: dict[str, dict[str, Any]] = {}
    display_name_lookup: dict[str, dict[str, Any]] = {}
    normalized_name_lookup: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(actors, start=1):
        actor = _require_dict(item, f"story_plan.actors[{index}]")
        actor_id = _require_string(actor.get("actor_id"), f"story_plan.actors[{index}].actor_id")
        display_name = _require_string(actor.get("display_name"), f"story_plan.actors[{index}].display_name")
        role = _require_string(actor.get("role"), f"story_plan.actors[{index}].role")
        if actor_id in actor_lookup:
            raise ValidationError("story_plan.actors actor_id must be unique")
        if display_name in display_name_lookup:
            raise ValidationError("story_plan.actors display_name must be unique")
        normalized_display_name = display_name.casefold()
        if normalized_display_name in normalized_name_lookup:
            raise ValidationError("story_plan.actors display_name casefold must be unique")
        normalized = dict(actor)
        normalized["actor_id"] = actor_id
        normalized["display_name"] = display_name
        normalized["role"] = role
        actor_lookup[actor_id] = normalized
        display_name_lookup[display_name] = normalized
        normalized_name_lookup[normalized_display_name] = normalized
        validated_actors.append(normalized)
    return validated_actors, {
        **actor_lookup,
        **{f"display:{key}": value for key, value in display_name_lookup.items()},
        **{f"casefold:{key}": value for key, value in normalized_name_lookup.items()},
    }


def _resolve_actor_from_story_plan(
    *,
    beat: dict[str, Any],
    beat_index: int,
    actor_registry: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    speaker_actor_id_value = beat.get("speaker_actor_id")
    speaker_value = beat.get("speaker")
    speaker_actor_id: str | None = None
    if isinstance(speaker_actor_id_value, str) and speaker_actor_id_value.strip():
        candidate_id = speaker_actor_id_value.strip()
        candidate_actor = actor_registry.get(candidate_id)
        if candidate_actor is None:
            raise ValidationError(
                f"story_plan.message_beats[{beat_index}].speaker_actor_id must reference an actor_id from story_plan.actors"
            )
        speaker_actor_id = candidate_id
    speaker: str | None = None
    if isinstance(speaker_value, str) and speaker_value.strip():
        speaker = speaker_value.strip()
    if speaker_actor_id is None:
        if speaker is None:
            raise ValidationError(
                f"story_plan.message_beats[{beat_index}] must include speaker_actor_id or speaker"
            )
        candidate_actor = actor_registry.get(f"display:{speaker}") or actor_registry.get(
            f"casefold:{speaker.casefold()}"
        ) or actor_registry.get(speaker) or actor_registry.get(speaker.casefold())
        if candidate_actor is None:
            raise ValidationError(
                f"story_plan.message_beats[{beat_index}].speaker must reference an actor from story_plan.actors"
            )
        speaker_actor_id = str(candidate_actor["actor_id"])
        speaker = str(candidate_actor["display_name"])
        return speaker_actor_id, speaker
    canonical_actor = actor_registry[speaker_actor_id]
    canonical_display_name = str(canonical_actor["display_name"])
    if speaker is None:
        speaker = canonical_display_name
    elif speaker.casefold() != canonical_display_name.casefold():
        raise ValidationError(
            f"story_plan.message_beats[{beat_index}].speaker must match the referenced actor display_name"
        )
    else:
        speaker = canonical_display_name
    return speaker_actor_id, speaker


def validate_story_plan(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "story_plan")
    task_obj = obj.get("task")
    tasks_obj = obj.get("tasks")
    if task_obj is not None:
        task = _require_dict(task_obj, "story_plan.task")
    elif tasks_obj is not None:
        tasks = _require_list(tasks_obj, "story_plan.tasks")
        if len(tasks) != 1:
            raise ValidationError("story_plan.tasks must contain exactly one task")
        task = _require_dict(tasks[0], "story_plan.tasks[0]")
    else:
        raise ValidationError("story_plan.task is required")
    actors = _require_list(obj.get("actors"), "story_plan.actors")
    task_actor_layout = _require_dict(obj.get("task_actor_layout"), "story_plan.task_actor_layout")
    state_changes = _require_list(obj.get("state_changes"), "story_plan.state_changes")
    message_beats = _require_list(obj.get("message_beats"), "story_plan.message_beats")
    planned_probe_queries = _require_list(
        obj.get("planned_probe_queries"),
        "story_plan.planned_probe_queries",
    )
    if not actors:
        raise ValidationError("story_plan.actors must not be empty")
    if not state_changes:
        raise ValidationError("story_plan.state_changes must not be empty")
    if not message_beats:
        raise ValidationError("story_plan.message_beats must not be empty")
    if not planned_probe_queries:
        raise ValidationError("story_plan.planned_probe_queries must not be empty")
    normalized_actors, actor_registry = _normalize_story_plan_actors(actors)
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
    normalized_message_beats: list[dict[str, Any]] = []
    for index, item in enumerate(message_beats, start=1):
        beat = _require_dict(item, f"story_plan.message_beats[{index}]")
        speaker_actor_id, speaker = _resolve_actor_from_story_plan(
            beat=beat,
            beat_index=index,
            actor_registry=actor_registry,
        )
        message_intent = _require_string(
            beat.get("message_intent"),
            f"story_plan.message_beats[{index}].message_intent",
        )
        purpose_value = beat.get("purpose")
        purpose = purpose_value.strip() if isinstance(purpose_value, str) and purpose_value.strip() else message_intent
        normalized_message_beats.append(
            {
                **beat,
                "beat_id": _require_string(beat.get("beat_id"), f"story_plan.message_beats[{index}].beat_id"),
                "purpose": purpose,
                "speaker_actor_id": speaker_actor_id,
                "speaker": speaker,
                "session_id": _require_string(
                    beat.get("session_id"),
                    f"story_plan.message_beats[{index}].session_id",
                ),
                "message_intent": message_intent,
            }
        )
    return {
        "story_id": _require_string(obj.get("story_id"), "story_plan.story_id"),
        "case_id": _require_string(obj.get("case_id"), "story_plan.case_id"),
        "family_id": _require_string(obj.get("family_id"), "story_plan.family_id"),
        "task": task,
        "actors": normalized_actors,
        "task_actor_layout": task_actor_layout,
        "state_changes": state_changes,
        "message_beats": normalized_message_beats,
        "planned_probe_queries": planned_probe_queries,
    }


def validate_command_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValidationError("command_plan must not be empty")
    validated: list[dict[str, Any]] = []
    seen_step_ids: set[str] = set()
    allowed_action_types = {
        "create_chat",
        "send_message",
        "reply_in_thread",
        "fetch_chat_messages",
        "fetch_thread_messages",
    }
    for index, row in enumerate(rows, start=1):
        obj = _require_dict(row, f"command_plan[{index}]")
        step_id = _require_string(
            obj.get("step_id") or obj.get("command_id"),
            f"command_plan[{index}].step_id",
        )
        if step_id in seen_step_ids:
            raise ValidationError(f"duplicate command_plan.step_id: {step_id}")
        seen_step_ids.add(step_id)
        action_type = _require_string(obj.get("action_type"), f"command_plan[{index}].action_type")
        if action_type not in allowed_action_types:
            raise ValidationError(f"command_plan[{index}].action_type must be supported")
        depends_on = [
            _require_string(item, f"command_plan[{index}].depends_on_step_ids[{dep_index}]")
            for dep_index, item in enumerate(
                _require_list(obj.get("depends_on_step_ids"), f"command_plan[{index}].depends_on_step_ids"),
                start=1,
            )
        ]
        params = _require_dict(obj.get("params"), f"command_plan[{index}].params")
        output_ref_value = obj.get("output_ref")
        output_ref = output_ref_value.strip() if isinstance(output_ref_value, str) else ""
        validated.append(
            {
                "case_id": _require_string(obj.get("case_id"), f"command_plan[{index}].case_id"),
                "command_id": step_id,
                "step_id": step_id,
                "sequence_no": int(_require_number(obj.get("sequence_no"), f"command_plan[{index}].sequence_no")),
                "action_type": action_type,
                "beat_id": str(obj.get("beat_id") or ""),
                "turn_id": str(obj.get("turn_id") or ""),
                "actor_id": str(obj.get("actor_id") or obj.get("speaker_ref") or ""),
                "session_id": _require_string(obj.get("session_id"), f"command_plan[{index}].session_id"),
                "source_type": _require_string(obj.get("source_type"), f"command_plan[{index}].source_type"),
                "source_ref": _require_string(obj.get("source_ref"), f"command_plan[{index}].source_ref"),
                "chat_ref": _require_string(obj.get("chat_ref"), f"command_plan[{index}].chat_ref"),
                "topic_key": _require_string(obj.get("topic_key"), f"command_plan[{index}].topic_key"),
                "turn_purpose": str(obj.get("turn_purpose") or ""),
                "speaker_role": str(obj.get("speaker_role") or ""),
                "speaker_ref": str(obj.get("speaker_ref") or obj.get("actor_id") or ""),
                "message_text": str(obj.get("message_text") or ""),
                "depends_on_step_ids": depends_on,
                "benchmark_role": str(obj.get("benchmark_role") or ""),
                "turn_kind": str(obj.get("turn_kind") or ""),
                "annotation_target": bool(obj.get("annotation_target") or False),
                "event_bearing": bool(obj.get("event_bearing") or False),
                "official_file_ref": str(obj.get("official_file_ref") or ""),
                "private_info_ref": str(obj.get("private_info_ref") or ""),
                "task_relevance_boundary": str(obj.get("task_relevance_boundary") or ""),
                "family_id": str(obj.get("family_id") or ""),
                "memory_failure_mode": str(obj.get("memory_failure_mode") or obj.get("family_id") or ""),
                "memory_trap": str(obj.get("memory_trap") or ""),
                "expected_openclaw_memory_risk": str(obj.get("expected_openclaw_memory_risk") or ""),
                "task_wiki_expected_handling": str(obj.get("task_wiki_expected_handling") or ""),
                "state_field_hints": list(obj.get("state_field_hints") or []),
                "semantic_payload": str(obj.get("semantic_payload") or ""),
                "planned_message_text": str(obj.get("planned_message_text") or obj.get("message_text") or ""),
                "output_ref": output_ref,
                "params": params,
                "lark_cli_command": _require_string(
                    obj.get("lark_cli_command"),
                    f"command_plan[{index}].lark_cli_command",
                ),
            }
        )
    return sorted(validated, key=lambda item: (item["sequence_no"], item["step_id"]))


def validate_execution_plan(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "execution_plan")
    actions: list[dict[str, Any]] = []
    seen_action_ids: set[str] = set()
    for index, item in enumerate(_require_list(obj.get("actions"), "execution_plan.actions"), start=1):
        action = _require_dict(item, f"execution_plan.actions[{index}]")
        action_id = _require_string(action.get("action_id"), f"execution_plan.actions[{index}].action_id")
        if action_id in seen_action_ids:
            raise ValidationError(f"duplicate execution_plan.action_id: {action_id}")
        seen_action_ids.add(action_id)
        action_type = _require_string(action.get("action_type"), f"execution_plan.actions[{index}].action_type")
        if action_type not in {
            "create_chat",
            "send_message",
            "reply_in_thread",
            "fetch_chat_messages",
            "fetch_thread_messages",
        }:
            raise ValidationError(f"execution_plan.actions[{index}].action_type must be supported")
        actions.append(
            {
                "action_id": action_id,
                "action_type": action_type,
                "depends_on": [
                    _require_string(dep, f"execution_plan.actions[{index}].depends_on[{dep_index}]")
                    for dep_index, dep in enumerate(
                        _require_list(action.get("depends_on") or [], f"execution_plan.actions[{index}].depends_on"),
                        start=1,
                    )
                ],
                "params": _require_dict(action.get("params"), f"execution_plan.actions[{index}].params"),
                "output_ref": str(action.get("output_ref") or ""),
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "execution_plan.case_id"),
        "operator_identity": _require_string(
            obj.get("operator_identity") or "user",
            "execution_plan.operator_identity",
        ),
        "delivery_mode": _require_string(
            obj.get("delivery_mode") or "prefixed_single_operator",
            "execution_plan.delivery_mode",
        ),
        "actions": actions,
    }


def validate_execution_result(payload: dict[str, Any]) -> dict[str, Any]:
    obj = _require_dict(payload, "execution_result")
    action_status = []
    for index, item in enumerate(_require_list(obj.get("action_status") or [], "execution_result.action_status"), start=1):
        row = _require_dict(item, f"execution_result.action_status[{index}]")
        action_status.append(
            {
                "action_id": _require_string(
                    row.get("action_id"),
                    f"execution_result.action_status[{index}].action_id",
                ),
                "status": _require_string(row.get("status"), f"execution_result.action_status[{index}].status"),
                "command": list(row.get("command") or []),
                "stdout": row.get("stdout", {}),
                "stderr": str(row.get("stderr") or ""),
                "returncode": int(row.get("returncode") or 0),
            }
        )
    return {
        "case_id": _require_string(obj.get("case_id"), "execution_result.case_id"),
        "status": _require_string(obj.get("status"), "execution_result.status"),
        "operator_identity": _require_string(
            obj.get("operator_identity") or "user",
            "execution_result.operator_identity",
        ),
        "delivery_mode": _require_string(
            obj.get("delivery_mode") or "prefixed_single_operator",
            "execution_result.delivery_mode",
        ),
        "created_resources": _require_dict(obj.get("created_resources") or {}, "execution_result.created_resources"),
        "thread_id_to_chat_id": _require_dict(
            obj.get("thread_id_to_chat_id") or {},
            "execution_result.thread_id_to_chat_id",
        ),
        "action_status": action_status,
        "preflight": _require_dict(obj.get("preflight") or {}, "execution_result.preflight"),
    }


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
