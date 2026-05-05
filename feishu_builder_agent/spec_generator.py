from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Any

from .builder_settings import load_builder_settings, resolve_difficulty_settings
from .llm_client import JsonLLMClient
from .logging_utils import builder_log
from .prompt_templates import build_spec_prompts
from .schemas import ValidationError, validate_case_spec


DEFAULT_SCENARIO_PROFILE = "enterprise_release_coordination"
DEFAULT_DEPARTMENTS = ["产品", "研发", "安全", "运维", "销售", "客户成功"]
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
DEPARTMENT_HINT_ALIASES = {
    "SRE": "站点可靠性工程",
    "PMO": "项目管理办公室",
    "管理层": "项目管理办公室",
}


def build_complexity_profile(difficulty: str) -> dict[str, int]:
    return dict(resolve_difficulty_settings(difficulty)["complexity_profile"])


def normalize_seed(seed: int | None = None) -> int:
    if seed is not None:
        return int(seed)
    now = datetime.now(timezone.utc)
    return int(now.strftime("%m%d%H%M%S"))


def _default_task_id(seed: int) -> str:
    return f"FEISHU-{seed}"


def _default_case_id(task_id: str) -> str:
    digits = re.sub(r"[^0-9]+", "", task_id)
    return f"case_feishu_{digits or 'generated'}_example"


def _normalize_task_id(value: Any, seed: int) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return _default_task_id(seed)
    digits = re.sub(r"[^0-9]+", "", text)
    if not digits:
        return _default_task_id(seed)
    return f"FEISHU-{digits}"


def _normalize_case_id(value: Any, task_id: str) -> str:
    text = str(value or "").strip().lower()
    if text:
        normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        if normalized.startswith("case_feishu_") and normalized.endswith("_example"):
            return normalized
    return _default_case_id(task_id)


def _select_department_hints(user_hint: str) -> list[str]:
    hint = str(user_hint or "").strip()
    selected: list[str] = []
    keyword_map = {
        "上线": ["产品", "研发", "运维"],
        "发布": ["产品", "研发", "销售"],
        "安全": ["安全", "研发"],
        "客户": ["客户成功", "销售"],
        "回滚": ["运维", "研发"],
        "数据": ["研发", "运维"],
    }
    for keyword, departments in keyword_map.items():
        if keyword in hint:
            for department in departments:
                if department not in selected:
                    selected.append(department)
    for department in DEFAULT_DEPARTMENTS:
        if department not in selected:
            selected.append(department)
        if len(selected) >= 6:
            break
    return selected


def _normalize_department_hints(value: Any, fallback: list[str]) -> list[str]:
    department_pool = list(load_builder_settings()["defaults"]["department_pool"])
    known_departments = set(department_pool)
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            resolved = DEPARTMENT_HINT_ALIASES.get(text, text)
            if resolved in known_departments and resolved not in normalized:
                normalized.append(resolved)
        return normalized or fallback
    text = str(value or "").strip()
    if not text:
        return fallback
    selected: list[str] = []
    for department in department_pool:
        if department in text and department not in selected:
            selected.append(department)
    for alias, resolved in DEPARTMENT_HINT_ALIASES.items():
        if alias in text and resolved not in selected:
            selected.append(resolved)
    if selected:
        return selected
    pieces = [item.strip() for item in re.split(r"[，,、；;/\s]+", text) if item.strip()]
    return pieces or fallback


def _normalize_chinese_hint(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if text and _CJK_RE.search(text):
        return text
    return fallback


def _fallback_case_spec(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int,
    user_hint: str,
) -> dict[str, Any]:
    task_id = _default_task_id(seed)
    case_id = _default_case_id(task_id)
    hint_text = str(user_hint or "").strip()
    department_hints = _select_department_hints(hint_text)
    title_hint = hint_text or f"{task_id} 发布窗口协调"
    main_goal_hint = hint_text or f"围绕 {task_id} 形成真实、可执行的跨部门协作口径"
    return validate_case_spec(
        {
            "case_id": case_id,
            "task_id": task_id,
            "title": "",
            "company_type": "",
            "department_hints": department_hints,
            "scenario_profile": scenario_profile or DEFAULT_SCENARIO_PROFILE,
            "title_hint": title_hint,
            "main_goal_hint": main_goal_hint,
            "main_goal": "",
            "difficulty": difficulty or "medium",
            "seed": seed,
        }
    )


def generate_case_spec_with_mode(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int | None = None,
    user_hint: str = "",
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_seed = normalize_seed(seed)
    fallback = _fallback_case_spec(
        scenario_profile=scenario_profile,
        difficulty=difficulty,
        seed=normalized_seed,
        user_hint=user_hint,
    )
    if llm_client is None:
        return fallback, "fallback"
    system_prompt, user_prompt = build_spec_prompts(
        scenario_profile=scenario_profile,
        difficulty=difficulty,
        seed=normalized_seed,
        user_hint=user_hint,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        normalized_task_id = _normalize_task_id(payload.get("task_id"), normalized_seed)
        normalized_case_id = _normalize_case_id(payload.get("case_id"), normalized_task_id)
        normalized_department_hints = _normalize_department_hints(
            payload.get("department_hints"),
            fallback["department_hints"],
        )
        normalized = validate_case_spec(
            {
                "case_id": normalized_case_id,
                "task_id": normalized_task_id,
                "title": "",
                "company_type": "",
                "department_hints": normalized_department_hints,
                "scenario_profile": scenario_profile or DEFAULT_SCENARIO_PROFILE,
                "title_hint": _normalize_chinese_hint(payload.get("title_hint"), fallback["title_hint"]),
                "main_goal_hint": _normalize_chinese_hint(payload.get("main_goal_hint"), fallback["main_goal_hint"]),
                "main_goal": "",
                "difficulty": difficulty or "medium",
                "seed": normalized_seed,
            }
        )
        return normalized, "live"
    except ValidationError as exc:
        builder_log(
            "spec",
            f"模型输出未通过 case_spec 校验，回退 fallback。reason={exc} payload={payload!r}",
        )
        return fallback, "fallback"
    except Exception as exc:
        builder_log(
            "spec",
            f"模型输出后处理失败，回退 fallback。reason={exc.__class__.__name__}: {exc}",
        )
        return fallback, "fallback"


def generate_case_spec(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int | None = None,
    user_hint: str = "",
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    spec, _mode = generate_case_spec_with_mode(
        scenario_profile=scenario_profile,
        difficulty=difficulty,
        seed=seed,
        user_hint=user_hint,
        llm_client=llm_client,
    )
    return spec
