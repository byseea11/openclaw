from __future__ import annotations

from .llm_client import JsonLLMClient
from .schemas import ValidationError, validate_case_seed, validate_case_world


def _fallback_case_world(case_seed: dict[str, object]) -> dict[str, object]:
    seed = validate_case_seed(case_seed)
    title = seed["title"]
    main_goal = seed["main_goal"]
    departments = "、".join(seed["departments"])
    return {
        "case_id": seed["case_id"],
        "task_id": seed["task_id"],
        "title": title,
        "domain": seed["domain"],
        "company_type": seed["company_type"],
        "main_goal": main_goal,
        "organization_background": f"{title} 所在团队是一个 {seed['company_type']} 组织，{departments} 需要在同一飞书协作链路里持续对齐决策、风险和对外口径。",
        "external_pressure": f"业务侧正在围绕 {seed['task_id']} 向客户和内部管理层同步预期，如果短时间内拿不出一致结论，就会影响 {main_goal} 的可信度。",
        "stakeholders": [
            "产品团队需要维持目标与范围的一致性。",
            "研发与测试团队需要确认真实可交付性。",
            "安全与运维团队需要把风险门槛说清楚。",
            "销售与客户成功团队需要一个能对外同步的窗口口径。",
        ],
        "conflict_axes": [
            "内部目标日期是否可以被当成对外承诺。",
            "关键 blocker 和评审门槛是否已经满足上线条件。",
            "上线窗口、回滚预案与客户承诺之间如何取舍。",
        ],
        "hidden_constraints": [
            "数据迁移窗口需要依赖外部团队确认。",
            "高风险能力必须通过安全评审后才能进入对外表述。",
            "回滚演练未完成前，运维不愿意锁定最终上线窗口。",
        ],
        "reversal_points": [
            "原本乐观的目标日期会在后续讨论中被修正。",
            "某个 thread 内形成的技术判断会影响主群口径。",
            "对外表述会从明确日期收缩成条件式窗口。",
        ],
        "complexity_profile": seed["complexity_profile"],
    }


def generate_case_world_with_mode(
    case_seed: dict[str, object],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, object], str]:
    seed = validate_case_seed(case_seed)
    if llm_client is None:
        return validate_case_world(_fallback_case_world(seed)), "fallback"
    system_prompt = (
        "Generate one enterprise collaboration case world as JSON. "
        "Return only a JSON object with keys: case_id, task_id, title, domain, company_type, "
        "main_goal, organization_background, external_pressure, stakeholders, conflict_axes, "
        "hidden_constraints, reversal_points, complexity_profile. "
        "All natural-language strings must be written in Simplified Chinese. "
        "Do not output Markdown."
    )
    user_prompt = (
        f"Case seed:\n{seed}\n"
        "请生成一个真实的企业协作世界观，用于飞书群聊和 thread 多轮讨论。"
        "必须体现外部压力、隐藏约束、角色冲突和后续可能改口的反转点。"
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_case_world(payload), "live"
    except (Exception, ValidationError):
        return validate_case_world(_fallback_case_world(seed)), "fallback"


def generate_case_world(case_seed: dict[str, object], *, llm_client: JsonLLMClient | None = None) -> dict[str, object]:
    case_world, _mode = generate_case_world_with_mode(case_seed, llm_client=llm_client)
    return case_world
