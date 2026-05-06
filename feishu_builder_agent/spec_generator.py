from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .builder_settings import load_builder_settings, resolve_default_difficulty
from .failure_mode_selector import fill_failure_modes
from .logging_utils import builder_log
from .schemas import ValidationError, validate_case_spec


DEFAULT_SCENARIO_PROFILE = "enterprise_task_memory"
DEFAULT_DEPARTMENTS = ["产品", "研发", "安全", "运维", "销售", "客户成功"]


def normalize_seed(seed: int | None = None) -> int:
    if seed is not None:
        return int(seed)
    now = datetime.now(timezone.utc)
    return int(now.strftime("%m%d%H%M%S"))


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


def _select_department_hints(user_hint: str) -> list[str]:
    chosen: list[str] = []
    keyword_map = {
        "财务": ["财务", "产品"],
        "客户": ["销售", "客户成功"],
        "安全": ["安全", "研发"],
        "迁移": ["数据平台", "运维"],
        "依赖": ["研发", "产品"],
    }
    for keyword, departments in keyword_map.items():
        if keyword in user_hint:
            for department in departments:
                if department not in chosen:
                    chosen.append(department)
    for department in DEFAULT_DEPARTMENTS:
        if department not in chosen:
            chosen.append(department)
    return chosen[:6]


def _fallback_case_spec(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int,
    user_hint: str,
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
            "title": "",
            "company_type": "",
            "department_hints": _select_department_hints(user_hint),
            "scenario_profile": scenario_profile or DEFAULT_SCENARIO_PROFILE,
            "title_hint": user_hint or f"{task_id} 任务记忆失败用例",
            "main_goal_hint": user_hint or f"构造会让 Memory.md 在 {task_id} 上失败的任务协作数据",
            "main_goal": "",
            "difficulty": difficulty or resolve_default_difficulty(),
            "seed": seed,
            "comparison_target": comparison_target,
            "selected_failure_modes": resolved_modes,
            "primary_failure_mode": resolved_primary,
            "user_hint": user_hint,
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
    del llm_client
    settings = load_builder_settings()
    normalized_seed = normalize_seed(seed)
    target = comparison_target or settings["defaults"]["comparison_target_default"]
    spec = _fallback_case_spec(
        scenario_profile=scenario_profile,
        difficulty=difficulty or resolve_default_difficulty(),
        seed=normalized_seed,
        user_hint=user_hint,
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
