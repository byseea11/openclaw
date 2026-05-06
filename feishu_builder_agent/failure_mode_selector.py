from __future__ import annotations

from typing import Any

from .builder_settings import FAILURE_MODES, load_builder_settings, resolve_difficulty_settings


def fill_failure_modes(
    *,
    selected_failure_modes: list[str] | None,
    primary_failure_mode: str | None,
    difficulty: str,
) -> tuple[list[str], str]:
    difficulty_settings = resolve_difficulty_settings(difficulty)
    minimum_modes = int(difficulty_settings["selected_failure_modes_min"])
    settings = load_builder_settings()
    ordered_modes = sorted(
        FAILURE_MODES,
        key=lambda item: (-float(settings["failure_mode_mix"].get(item, 0.0)), item),
    )
    chosen: list[str] = []
    for item in selected_failure_modes or []:
        if item in FAILURE_MODES and item not in chosen:
            chosen.append(item)
    if not chosen:
        chosen = ordered_modes[:minimum_modes]
    else:
        # Phase 1 respects explicit case_spec selection; auto-fill only when the field is missing.
        chosen = list(chosen)
    resolved_primary = primary_failure_mode if primary_failure_mode in chosen else chosen[0]
    return chosen, resolved_primary


def normalized_failure_mode_spec(case_spec: dict[str, Any]) -> dict[str, Any]:
    selected, primary = fill_failure_modes(
        selected_failure_modes=list(case_spec.get("selected_failure_modes") or []),
        primary_failure_mode=str(case_spec.get("primary_failure_mode") or "").strip() or None,
        difficulty=str(case_spec.get("difficulty") or "medium"),
    )
    normalized = dict(case_spec)
    normalized["selected_failure_modes"] = selected
    normalized["primary_failure_mode"] = primary
    return normalized
