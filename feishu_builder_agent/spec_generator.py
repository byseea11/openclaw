from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .builder_settings import load_builder_settings, resolve_default_difficulty
from .failure_mode_selector import fill_failure_modes
from .llm_client import live_llm_required
from .logging_utils import builder_log
from .prompt_registry import build_spec_generation_prompts
from .schemas import validate_case_spec


def normalize_seed(seed: int | None = None) -> int:
    if seed is not None:
        return int(seed)
    now = datetime.now(timezone.utc)
    return int(now.strftime("%m%d%H%M%S%f"))


def _default_task_id(seed: int) -> str:
    return f"FEISHU-{seed}"


def _default_case_id(task_id: str) -> str:
    digits = re.sub(r"[^0-9]+", "", task_id)
    return f"case_feishu_{digits or 'generated'}_v3"


def _normalize_task_id(value: Any, seed: int) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return _default_task_id(seed)
    digits = re.sub(r"[^0-9]+", "", text)
    return f"FEISHU-{digits or seed}"


def _normalize_case_id(value: Any, task_id: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("case_"):
        return re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    return _default_case_id(task_id)


def _fallback_case_spec(
    *,
    difficulty: str,
    seed: int,
    comparison_target: str,
    selected_failure_modes: list[str] | None,
    primary_failure_mode: str | None,
) -> dict[str, Any]:
    task_id = _default_task_id(seed)
    case_id = _default_case_id(task_id)
    resolved_modes, resolved_primary = fill_failure_modes(
        selected_failure_modes=selected_failure_modes,
        primary_failure_mode=primary_failure_mode,
        difficulty=difficulty,
    )
    return validate_case_spec(
        {
            "case_id": case_id,
            "task_id": task_id,
            "difficulty": difficulty or resolve_default_difficulty(),
            "seed": seed,
            "comparison_target": comparison_target,
            "selected_failure_modes": resolved_modes,
            "primary_failure_mode": resolved_primary,
        }
    )
def _normalize_llm_case_spec(
    payload: dict[str, Any],
    *,
    difficulty: str,
    seed: int,
    comparison_target: str,
    selected_failure_modes: list[str] | None,
    primary_failure_mode: str | None,
) -> dict[str, Any]:
    requested_modes, requested_primary = fill_failure_modes(
        selected_failure_modes=selected_failure_modes,
        primary_failure_mode=primary_failure_mode,
        difficulty=difficulty,
    )
    task_id = _default_task_id(seed)
    case_id = _default_case_id(task_id)
    candidate_modes = payload.get("selected_failure_modes") if selected_failure_modes is None else requested_modes
    resolved_modes, resolved_primary = fill_failure_modes(
        selected_failure_modes=candidate_modes,
        primary_failure_mode=payload.get("primary_failure_mode") if primary_failure_mode is None else requested_primary,
        difficulty=difficulty,
    )
    if selected_failure_modes is not None:
        resolved_modes = requested_modes
    if primary_failure_mode is not None:
        resolved_primary = requested_primary
    return validate_case_spec(
        {
            "case_id": case_id,
            "task_id": task_id,
            "difficulty": difficulty or resolve_default_difficulty(),
            "seed": seed,
            "comparison_target": comparison_target,
            "selected_failure_modes": resolved_modes,
            "primary_failure_mode": resolved_primary,
        }
    )


def generate_case_spec_with_mode(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int | None = None,
    user_hint: str = "",
    comparison_target: str | None = None,
    selected_failure_modes: list[str] | None = None,
    primary_failure_mode: str | None = None,
    llm_client: Any | None = None,
) -> tuple[dict[str, Any], str]:
    settings = load_builder_settings()
    normalized_seed = normalize_seed(seed)
    target = comparison_target or settings["defaults"]["comparison_target_default"]
    if llm_client is None and live_llm_required():
        raise RuntimeError("spec-generation requires live LLM but no active llm_client is available")
    if llm_client is not None:
        system_prompt, user_prompt = build_spec_generation_prompts(
            difficulty=difficulty or resolve_default_difficulty(),
            seed=normalized_seed,
            comparison_target=target,
            selected_failure_modes=selected_failure_modes,
            primary_failure_mode=primary_failure_mode,
            user_hint=user_hint,
        )
        try:
            llm_payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            spec = _normalize_llm_case_spec(
                llm_payload,
                difficulty=difficulty or resolve_default_difficulty(),
                seed=normalized_seed,
                comparison_target=target,
                selected_failure_modes=selected_failure_modes,
                primary_failure_mode=primary_failure_mode,
            )
            builder_log(
                "spec",
                f"生成 V3 case_spec case_id={spec['case_id']} failure_modes={','.join(spec['selected_failure_modes'])}",
            )
            return spec, "llm"
        except Exception as exc:
            if live_llm_required():
                raise RuntimeError(f"spec-generation requires live LLM but failed: {exc}") from exc
            builder_log("spec", f"live LLM case_spec 生成失败，回退 fallback。reason={exc}")
    spec = _fallback_case_spec(
        difficulty=difficulty or resolve_default_difficulty(),
        seed=normalized_seed,
        comparison_target=target,
        selected_failure_modes=selected_failure_modes,
        primary_failure_mode=primary_failure_mode,
    )
    builder_log(
        "spec",
        f"生成 V3 case_spec case_id={spec['case_id']} failure_modes={','.join(spec['selected_failure_modes'])}",
    )
    return spec, "fallback"


def generate_case_spec(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int | None = None,
    user_hint: str = "",
    comparison_target: str | None = None,
    selected_failure_modes: list[str] | None = None,
    primary_failure_mode: str | None = None,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    spec, _mode = generate_case_spec_with_mode(
        scenario_profile=scenario_profile,
        difficulty=difficulty,
        seed=seed,
        user_hint=user_hint,
        comparison_target=comparison_target,
        selected_failure_modes=selected_failure_modes,
        primary_failure_mode=primary_failure_mode,
        llm_client=llm_client,
    )
    return spec
