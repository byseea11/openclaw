from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_SCENARIO_PROFILE = "enterprise_release_coordination"
CATALOG_PATH = Path(__file__).resolve().parent / "templates" / "case_profile_catalog.json"


@lru_cache(maxsize=1)
def load_case_profile_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def resolve_case_profile(profile_id: str | None) -> dict[str, Any]:
    catalog = load_case_profile_catalog()
    normalized = str(profile_id or DEFAULT_SCENARIO_PROFILE).strip() or DEFAULT_SCENARIO_PROFILE
    profiles = catalog.get("scenario_profiles") or {}
    return profiles.get(normalized, profiles[DEFAULT_SCENARIO_PROFILE])


def _render_template(template: str, context: dict[str, Any]) -> str:
    return str(template).format(**context)


def _choice(values: list[str], *, rng: random.Random, default: str) -> str:
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    if not cleaned:
        return default
    return cleaned[rng.randrange(len(cleaned))]


def resolve_complexity_profile(*, difficulty: str, profile_id: str | None = None) -> dict[str, int]:
    profile = resolve_case_profile(profile_id)
    complexity = profile.get("default_complexity_profile_by_difficulty") or {}
    normalized_difficulty = str(difficulty or "medium").strip() or "medium"
    return dict(complexity.get(normalized_difficulty, complexity.get("medium", {})))


def sample_departments(
    *,
    seed: int,
    difficulty: str,
    profile_id: str | None = None,
    department_hints: list[str] | None = None,
) -> list[str]:
    profile = resolve_case_profile(profile_id)
    difficulty_to_count = profile.get("department_count_by_difficulty") or {}
    normalized_difficulty = str(difficulty or "medium").strip() or "medium"
    target_count = int(difficulty_to_count.get(normalized_difficulty, difficulty_to_count.get("medium", 7)))
    hints = [str(item).strip() for item in (department_hints or []) if str(item).strip()]
    pool = [str(item).strip() for item in profile["department_pool"] if str(item).strip()]
    must_include = [str(item).strip() for item in profile.get("must_include_departments", []) if str(item).strip()]
    selected: list[str] = []
    for item in must_include + hints:
        if item not in selected:
            selected.append(item)
    rng = random.Random(seed)
    remaining_pool = [item for item in pool if item not in selected]
    rng.shuffle(remaining_pool)
    while len(selected) < target_count and remaining_pool:
        selected.append(remaining_pool.pop())
    return selected


def sample_case_seed_components(
    *,
    task_id: str,
    difficulty: str,
    seed: int,
    profile_id: str | None = None,
    department_hints: list[str] | None = None,
    title_hint: str = "",
    main_goal_hint: str = "",
    company_type_hint: str = "",
) -> dict[str, Any]:
    profile = resolve_case_profile(profile_id)
    sampled_departments = sample_departments(
        seed=seed,
        difficulty=difficulty,
        profile_id=profile_id,
        department_hints=department_hints,
    )
    complexity_profile = resolve_complexity_profile(difficulty=difficulty, profile_id=profile_id)
    rng = random.Random(seed)
    company_type = company_type_hint or _choice(
        profile.get("company_type_options", []),
        rng=rng,
        default="企业级 SaaS",
    )
    initiative_label = _choice(profile.get("initiative_labels", []), rng=rng, default="发布窗口")
    delivery_motion = _choice(profile.get("delivery_motions", []), rng=rng, default="协调推进")
    target_window = _choice(profile.get("target_window_options", []), rng=rng, default="五月上旬")
    focus_department = sampled_departments[0] if sampled_departments else "产品"
    secondary_department = sampled_departments[1] if len(sampled_departments) > 1 else focus_department
    render_context = {
        "task_id": task_id,
        "company_type": company_type,
        "initiative_label": initiative_label,
        "delivery_motion": delivery_motion,
        "target_window": target_window,
        "focus_department": focus_department,
        "secondary_department": secondary_department,
    }
    title = title_hint or _render_template(
        _choice(profile.get("title_templates", []), rng=rng, default="{task_id} 发布窗口协调推进"),
        render_context,
    )
    render_context["title"] = title
    main_goal = main_goal_hint or _render_template(
        _choice(
            profile.get("main_goal_templates", []),
            rng=rng,
            default="围绕 {task_id} 形成真实的跨部门协作讨论，并推动 {target_window} 上线决策收敛",
        ),
        render_context,
    )
    return {
        "domain": profile["domain"],
        "company_type": company_type,
        "departments": sampled_departments,
        "complexity_profile": complexity_profile,
        "title": title,
        "main_goal": main_goal,
        "render_context": render_context,
    }


def sample_case_world_components(case_seed: dict[str, Any]) -> dict[str, list[str]]:
    profile = resolve_case_profile(case_seed.get("scenario_profile"))
    rng = random.Random(int(case_seed["seed"]) + 17)
    context = {
        "task_id": case_seed["task_id"],
        "title": case_seed["title"],
        "company_type": case_seed["company_type"],
        "main_goal": case_seed["main_goal"],
        "target_window": _choice(profile.get("target_window_options", []), rng=rng, default="五月上旬"),
        "focus_department": case_seed["departments"][0] if case_seed["departments"] else "产品",
        "secondary_department": case_seed["departments"][1] if len(case_seed["departments"]) > 1 else (case_seed["departments"][0] if case_seed["departments"] else "研发"),
    }
    stakeholders = [
        str((profile.get("stakeholder_templates") or {}).get(item, f"{item} 团队需要围绕当前目标给出明确判断。")).strip()
        for item in case_seed["departments"]
    ]
    stakeholder_count = max(4, min(8, len(stakeholders)))
    conflict_templates = [str(item).strip() for item in profile.get("conflict_axis_templates", []) if str(item).strip()]
    hidden_templates = [str(item).strip() for item in profile.get("hidden_constraint_templates", []) if str(item).strip()]
    reversal_templates = [str(item).strip() for item in profile.get("reversal_point_templates", []) if str(item).strip()]
    rng.shuffle(conflict_templates)
    rng.shuffle(hidden_templates)
    rng.shuffle(reversal_templates)
    return {
        "stakeholders": stakeholders[:stakeholder_count],
        "conflict_axes": [_render_template(item, context) for item in conflict_templates[:4]],
        "hidden_constraints": [_render_template(item, context) for item in hidden_templates[:4]],
        "reversal_points": [_render_template(item, context) for item in reversal_templates[:4]],
    }


def resolve_character_role_templates(*, profile_id: str | None = None, departments: list[str]) -> dict[str, list[dict[str, Any]]]:
    profile = resolve_case_profile(profile_id)
    templates = profile.get("character_role_templates") or {}
    return {department: list(templates.get(department, [])) for department in departments}


def sample_topic_templates(
    *,
    seed: int,
    difficulty: str,
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    profile = resolve_case_profile(profile_id)
    complexity_profile = resolve_complexity_profile(difficulty=difficulty, profile_id=profile_id)
    topic_count = int(complexity_profile.get("topic_count_target", 4))
    topic_templates = [dict(item) for item in profile.get("topic_templates", [])]
    required = [item for item in topic_templates if item.get("required")]
    optional = [item for item in topic_templates if not item.get("required")]
    rng = random.Random(seed + 29)
    rng.shuffle(optional)
    selected = required[:]
    while len(selected) < topic_count and optional:
        selected.append(optional.pop())
    return selected


def build_session_layouts(
    *,
    task_id: str,
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    profile = resolve_case_profile(profile_id)
    layouts = []
    for item in profile.get("session_layout_templates", []):
        template = dict(item)
        template["title"] = _render_template(str(item.get("title_template") or "{task_id} 会话"), {"task_id": task_id})
        layouts.append(template)
    return layouts
