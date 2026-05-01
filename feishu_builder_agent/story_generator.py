from __future__ import annotations

from typing import Any

from .llm_client import JsonLLMClient
from .schemas import ValidationError, validate_case_spec, validate_story


def _fallback_story(spec: dict[str, Any]) -> dict[str, Any]:
    title = spec["title"]
    return {
        "case_id": spec["case_id"],
        "task_id": spec["task_id"],
        "title": title,
        "background": f"{title} 所在项目处于{spec['company_type']}协作场景中，多个部门正在围绕上线节奏和对外口径持续讨论。",
        "business_pressure": f"业务侧希望 {title} 尽快形成明确推进计划，否则会影响客户信心和内部排期承诺。",
        "project_goal": spec["main_goal"],
        "initial_assumption": "团队一开始倾向于用一个偏乐观的内部目标日期推进，并希望通过跨部门协作尽快确认真实可行性。",
        "main_conflicts": [
            "业务和客户侧希望尽早形成可以对外同步的明确承诺。",
            "研发对隐藏依赖和实现不确定性保持谨慎态度。",
            "安全侧要求高风险能力必须先完成评审再决定对外口径。",
            "运维侧强调灰度窗口、回滚预案和上线稳定性必须先准备到位。",
        ],
        "in_scope": [title, "跨部门决策口径对齐"],
        "out_of_scope": ["无关的平台迁移工作", "长尾定制化需求"],
    }


def generate_story_with_mode(
    case_spec: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    spec = validate_case_spec(case_spec)
    if llm_client is None:
        return validate_story(_fallback_story(spec)), "fallback"
    system_prompt = (
        "Generate one concise enterprise software delivery story as JSON. "
        "Return only a JSON object with keys: case_id, task_id, title, background, "
        "business_pressure, project_goal, initial_assumption, main_conflicts, in_scope, out_of_scope. "
        "Keep it grounded in enterprise software collaboration. Be brief. Do not output Markdown. "
        "All natural-language strings must be written in Simplified Chinese. "
        "Do not use English sentences except unavoidable identifiers such as case_id or task_id."
    )
    user_prompt = (
        f"Case spec:\n{spec}\n"
        "请为这个 case 生成一段真实、简洁、只发生在 IM 场景中的企业协作故事。"
        "所有自然语言字段都必须使用简体中文。"
        "main_conflicts, in_scope, and out_of_scope must be arrays of strings."
    )
    try:
        story = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_story(story), "live"
    except (Exception, ValidationError):
        return validate_story(_fallback_story(spec)), "fallback"


def generate_story(case_spec: dict[str, Any], *, llm_client: JsonLLMClient | None = None) -> dict[str, Any]:
    story, _mode = generate_story_with_mode(case_spec, llm_client=llm_client)
    return story
