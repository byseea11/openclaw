from __future__ import annotations

import re
from typing import Any

from .builder_settings import load_builder_settings, resolve_difficulty_settings
from .llm_client import JsonLLMClient
from .logging_utils import builder_log
from .prompt_templates import build_case_world_prompts
from .schemas import ValidationError, validate_case_seed, validate_case_world


DEPARTMENT_ALIASES = {
    "SRE": "站点可靠性工程",
    "sre": "站点可靠性工程",
    "PMO": "项目管理办公室",
    "pmo": "项目管理办公室",
    "管理层": "项目管理办公室",
}
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _normalize_departments(values: list[object]) -> list[str]:
    normalized: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        resolved = DEPARTMENT_ALIASES.get(text, text)
        if resolved not in normalized:
            normalized.append(resolved)
    return normalized


def _pad_departments(values: list[str], fallback: list[str], *, difficulty: str) -> list[str]:
    target_count = int(resolve_difficulty_settings(difficulty)["department_count"])
    merged: list[str] = []
    for item in list(values) + list(fallback):
        if item not in merged:
            merged.append(item)
        if len(merged) >= target_count:
            break
    return merged


def _normalize_chinese_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if text and _CJK_RE.search(text):
        return text
    return fallback


def _normalize_chinese_list(values: Any, fallback: list[str]) -> list[str]:
    if not isinstance(values, list):
        return fallback
    normalized: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and _CJK_RE.search(text) and text not in normalized:
            normalized.append(text)
    return normalized or fallback


def _pad_topics(values: Any, fallback: list[dict[str, Any]], *, difficulty: str) -> list[dict[str, Any]]:
    target_count = int(resolve_difficulty_settings(difficulty)["topic_count"])
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(values) + list(fallback):
        if not isinstance(item, dict):
            continue
        topic_key = str(item.get("topic_key") or "").strip()
        if not topic_key or topic_key in seen:
            continue
        merged.append(item)
        seen.add(topic_key)
        if len(merged) >= target_count:
            break
    return merged


def _select_departments(seed: dict[str, Any]) -> list[str]:
    settings = load_builder_settings()
    difficulty_settings = resolve_difficulty_settings(seed["difficulty"])
    department_pool = list(settings["defaults"]["department_pool"])
    selected: list[str] = []
    for item in seed.get("department_hints") or []:
        value = str(item or "").strip()
        if value and value not in selected:
            selected.append(value)
    for item in department_pool:
        if item not in selected:
            selected.append(item)
    return _normalize_departments(selected[: difficulty_settings["department_count"]])


def _choose_department(departments: list[str], index: int, fallback: str) -> str:
    return departments[index] if index < len(departments) else fallback


def _build_selected_topics(seed: dict[str, Any], departments: list[str]) -> list[dict[str, Any]]:
    task_id = seed["task_id"]
    difficulty_settings = resolve_difficulty_settings(seed["difficulty"])
    session_blueprint = list(difficulty_settings["session_blueprint"])
    main_chat_session = session_blueprint[0] if len(session_blueprint) >= 1 else "session_main_chat"
    launch_thread_session = session_blueprint[1] if len(session_blueprint) >= 2 else "session_launch_window_thread"
    customer_chat_session = session_blueprint[2] if len(session_blueprint) >= 3 else "session_customer_sync_chat"
    risk_thread_session = session_blueprint[3] if len(session_blueprint) >= 4 else launch_thread_session
    exec_chat_session = session_blueprint[4] if len(session_blueprint) >= 5 else main_chat_session
    product = _choose_department(departments, 0, "产品")
    engineering = _choose_department(departments, 1, product)
    security = _choose_department(departments, 2, engineering)
    operations = _choose_department(departments, 3, engineering)
    sales = _choose_department(departments, 4, product)
    customer_success = _choose_department(departments, 5, sales)
    return [
        {
            "topic_key": "release_window",
            "topic_title": "发布时间口径",
            "desired_event_types": ["conclusion_event", "time_event", "scope_event"],
            "state_transitions": [
                "先以五月上旬作为内部目标。",
                "在风险暴露后把对外口径收紧为暂不承诺具体日期。",
            ],
            "turn_templates": [
                {
                    "session_id": main_chat_session,
                    "speaker_department": product,
                    "turn_purpose": "提出初始发布时间目标",
                    "supports_event_types": ["conclusion_event", "time_event"],
                    "state_transition": "提出五月上旬的初始目标",
                    "semantic_payload_template": f"{task_id} 当前先按五月上旬作为内部目标推进，但还没有对外锁死具体发布日期。",
                },
                {
                    "session_id": launch_thread_session,
                    "speaker_department": engineering,
                    "turn_purpose": "补充实际依赖对日期的影响",
                    "supports_event_types": ["constraint_event", "time_event"],
                    "state_transition": "指出依赖未锁定前不能确认上线日期",
                    "semantic_payload_template": "研发侧判断真正的关键依赖还没锁定，现在直接对外承诺日期风险过高。",
                },
                {
                    "session_id": main_chat_session,
                    "speaker_department": operations,
                    "turn_purpose": "收紧内部日期口径",
                    "supports_event_types": ["objection_event", "time_event"],
                    "state_transition": "内部目标日期从乐观转向保守",
                    "semantic_payload_template": "运维侧建议先不要把五月上旬当成确定承诺，至少要等回滚准备确认后再同步。",
                },
                {
                    "session_id": customer_chat_session,
                    "speaker_department": sales,
                    "turn_purpose": "提出外部同步压力",
                    "supports_event_types": ["constraint_event", "scope_event"],
                    "state_transition": "对外口径需要单独管理",
                    "semantic_payload_template": "客户侧已经在追问上线时间，我们需要给一个保守但可执行的同步口径。",
                },
                {
                    "session_id": main_chat_session,
                    "speaker_department": product,
                    "turn_purpose": "形成暂不承诺具体日期的最新口径",
                    "supports_event_types": ["conclusion_event", "time_event"],
                    "state_transition": "把当前口径收敛为暂不承诺具体日期",
                    "semantic_payload_template": "当前统一口径先收敛为暂不承诺具体日期，等关键依赖确认后再重开上线窗口讨论。",
                },
            ],
        },
        {
            "topic_key": "readiness_blockers",
            "topic_title": "上线阻塞项",
            "desired_event_types": ["constraint_event", "status_event", "commitment_event"],
            "state_transitions": [
                "先暴露核心 blocker。",
                "再形成谁负责解除 blocker 的承诺。",
            ],
            "turn_templates": [
                {
                    "session_id": launch_thread_session,
                    "speaker_department": engineering,
                    "turn_purpose": "指出技术 blocker",
                    "supports_event_types": ["constraint_event", "status_event"],
                    "state_transition": "暴露迁移窗口未锁定",
                    "semantic_payload_template": "目前最大的 blocker 不是代码，而是数据迁移窗口和切换方案还没有最终确认。",
                },
                {
                    "session_id": risk_thread_session,
                    "speaker_department": security,
                    "turn_purpose": "补充安全前置约束",
                    "supports_event_types": ["constraint_event", "scope_event"],
                    "state_transition": "把安全评审加入 blocker 集合",
                    "semantic_payload_template": "安全评审还缺最后一轮结论，在结果出来前相关高风险能力不能直接开放。",
                },
                {
                    "session_id": main_chat_session,
                    "speaker_department": operations,
                    "turn_purpose": "补充运维状态",
                    "supports_event_types": ["status_event", "constraint_event"],
                    "state_transition": "把回滚演练未完成纳入 blocker",
                    "semantic_payload_template": "回滚演练还没有完成闭环，这也是当前不建议锁定窗口的重要原因。",
                },
                {
                    "session_id": "session_main_chat",
                    "speaker_department": engineering,
                    "turn_purpose": "给出解除 blocker 的承诺",
                    "supports_event_types": ["commitment_event", "time_event"],
                    "state_transition": "形成工程侧补齐依赖的承诺",
                    "semantic_payload_template": "研发会在本周内补齐迁移方案细节，并和运维一起把窗口确认条件列清楚。",
                },
                {
                    "session_id": launch_thread_session,
                    "speaker_department": operations,
                    "turn_purpose": "更新 blocker 状态",
                    "supports_event_types": ["status_event", "time_event"],
                    "state_transition": "阻塞项从未明确变成待确认",
                    "semantic_payload_template": "当前 blocker 已经收敛成三项，等迁移窗口、回滚演练和安全结论都明确后再给最终上线建议。",
                },
            ],
        },
        {
            "topic_key": "external_messaging",
            "topic_title": "客户同步口径",
            "desired_event_types": ["scope_event", "conclusion_event", "rationale_event"],
            "state_transitions": [
                "先暴露客户同步压力。",
                "再收敛成保守口径。",
            ],
            "turn_templates": [
                {
                    "session_id": customer_chat_session,
                    "speaker_department": sales,
                    "turn_purpose": "提出客户预期管理压力",
                    "supports_event_types": ["constraint_event", "scope_event"],
                    "state_transition": "客户同步成为单独问题",
                    "semantic_payload_template": "客户已经把这个能力排进内部计划，我们需要明确本周能否给出公开说法。",
                },
                {
                    "session_id": customer_chat_session,
                    "speaker_department": customer_success,
                    "turn_purpose": "补充客户影响面",
                    "supports_event_types": ["rationale_event", "scope_event"],
                    "state_transition": "把影响范围补充完整",
                    "semantic_payload_template": "如果现在给得过满，后面改口会直接影响客户侧对项目稳定性的判断。",
                },
                {
                    "session_id": main_chat_session,
                    "speaker_department": product,
                    "turn_purpose": "回主群同步保守口径",
                    "supports_event_types": ["conclusion_event", "scope_event"],
                    "state_transition": "把外部口径切换成保守表述",
                    "semantic_payload_template": "对外统一先说当前仍在完成最后的上线准备，预计窗口待确认，不给具体日历日期。",
                },
                {
                    "session_id": customer_chat_session,
                    "speaker_department": sales,
                    "turn_purpose": "确认最新客户同步措辞",
                    "supports_event_types": ["conclusion_event", "rationale_event"],
                    "state_transition": "外部口径从激进转为保守",
                    "semantic_payload_template": "那我对客户统一说现在还在做最后校验，具体时间等内部确认后第一时间同步。",
                },
            ],
        },
        {
            "topic_key": "risk_controls",
            "topic_title": "风险控制与验收条件",
            "desired_event_types": ["objection_event", "commitment_event", "status_event"],
            "state_transitions": [
                "先暴露验收条件不足。",
                "再形成补齐动作。",
            ],
            "turn_templates": [
                {
                    "session_id": main_chat_session,
                    "speaker_department": security,
                    "turn_purpose": "指出风险控制要求",
                    "supports_event_types": ["objection_event", "constraint_event"],
                    "state_transition": "把风险控制要求显式化",
                    "semantic_payload_template": "如果没有最终的风险验收清单，现在推进上线窗口只会放大后续回滚概率。",
                },
                {
                    "session_id": risk_thread_session,
                    "speaker_department": operations,
                    "turn_purpose": "要求把回滚标准写清楚",
                    "supports_event_types": ["constraint_event", "scope_event"],
                    "state_transition": "把回滚标准加入验收条件",
                    "semantic_payload_template": "运维希望把回滚触发条件和恢复时间目标都写清楚，否则演练结果没有办法作为放行依据。",
                },
                {
                    "session_id": main_chat_session,
                    "speaker_department": engineering,
                    "turn_purpose": "承诺补齐验收材料",
                    "supports_event_types": ["commitment_event", "time_event"],
                    "state_transition": "形成补齐风险材料的承诺",
                    "semantic_payload_template": "研发会在下一个工作日把迁移方案、监控预案和回滚条件整理成一版供大家评审。",
                },
                {
                    "session_id": exec_chat_session,
                    "speaker_department": product,
                    "turn_purpose": "确认放行条件和下一步",
                    "supports_event_types": ["conclusion_event", "status_event"],
                    "state_transition": "把是否放行收敛为条件式判断",
                    "semantic_payload_template": "最终是否放行以风险材料补齐和演练通过为准，在这之前所有对外说法都保持保守。",
                },
            ],
        },
        {
            "topic_key": "executive_sync",
            "topic_title": "管理层同步口径",
            "desired_event_types": ["status_event", "scope_event", "conclusion_event"],
            "state_transitions": [
                "把内部讨论结论收敛成可以上卷的管理层摘要。",
                "管理层同步不再使用乐观日期，而是采用条件式表述。",
            ],
            "turn_templates": [
                {
                    "session_id": exec_chat_session,
                    "speaker_department": product,
                    "turn_purpose": "上卷当前状态",
                    "supports_event_types": ["status_event", "scope_event"],
                    "state_transition": "把散乱讨论汇总成管理层同步摘要",
                    "semantic_payload_template": "当前对管理层的同步先聚焦风险收敛和放行条件，不直接给确定发布日期。",
                },
                {
                    "session_id": exec_chat_session,
                    "speaker_department": operations,
                    "turn_purpose": "补充放行条件",
                    "supports_event_types": ["constraint_event", "status_event"],
                    "state_transition": "把放行条件抬升为管理层同步要点",
                    "semantic_payload_template": "需要同步说明当前仍取决于迁移窗口、回滚演练和最终风险验收三个条件。",
                },
                {
                    "session_id": main_chat_session,
                    "speaker_department": product,
                    "turn_purpose": "把管理层口径回写主群",
                    "supports_event_types": ["conclusion_event", "scope_event"],
                    "state_transition": "形成统一的上卷口径",
                    "semantic_payload_template": "管理层同步也统一使用条件式表述，不再带具体乐观日期。",
                },
            ],
        },
    ][: difficulty_settings["topic_count"]]


def _fallback_case_world(case_seed: dict[str, object]) -> dict[str, object]:
    seed = validate_case_seed(case_seed)
    departments = _select_departments(seed)
    title = seed["title_hint"] or f"{seed['task_id']} 发布窗口协调推进"
    company_type = seed["company_type_hint"] or "企业级 SaaS 公司"
    main_goal = seed["main_goal_hint"] or f"围绕 {seed['task_id']} 在五月上旬的目标窗口形成真实、可执行的统一口径。"
    department_text = "、".join(departments)
    return {
        "case_id": seed["case_id"],
        "task_id": seed["task_id"],
        "scenario_profile": seed["scenario_profile"],
        "difficulty": seed["difficulty"],
        "seed": seed["seed"],
        "title": title,
        "domain": seed["domain"],
        "company_type": company_type,
        "departments": departments,
        "main_goal": main_goal,
        "organization_background": f"{title} 所在团队是一个 {company_type} 组织，{department_text} 需要在同一飞书协作链路里持续对齐决策、风险和对外口径。",
        "external_pressure": f"业务侧正在围绕 {seed['task_id']} 向客户和内部管理层同步预期，如果短时间内拿不出一致结论，就会影响 {main_goal} 的可信度。",
        "stakeholders": [
            "产品团队需要统一内部与外部口径，避免过早承诺。",
            "研发团队需要明确技术依赖和迁移窗口是否真正可落地。",
            "安全与运维团队关注风险控制、回滚预案和最终放行条件。",
            "销售与客户成功团队承受客户预期压力，需要稳定但保守的对外说法。",
        ],
        "conflict_axes": [
            "内部目标日期能否被当成对外承诺。",
            "上线窗口是先锁日期还是先锁风险条件。",
            "客户同步节奏要不要跟随内部乐观判断。",
        ],
        "hidden_constraints": [
            "数据迁移窗口尚未最终确认，影响实际切换方案。",
            "回滚演练和风险验收材料还没有形成最终闭环。",
            "高风险能力需要等待最后一轮安全评审结论。",
        ],
        "reversal_points": [
            "原本乐观的发布时间会在后续讨论中被收紧。",
            "主群形成的初步口径会在 thread 中被技术事实修正。",
            "客户同步口径会从激进承诺改成条件式表述。",
        ],
        "selected_topics": _build_selected_topics(seed, departments),
        "complexity_profile": seed["complexity_profile"],
    }


def generate_case_world_with_mode(
    case_seed: dict[str, object],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, object], str]:
    seed = validate_case_seed(case_seed)
    fallback_world = _fallback_case_world(seed)
    if llm_client is None:
        return validate_case_world(fallback_world), "fallback"
    system_prompt, user_prompt = build_case_world_prompts(
        seed=seed,
        fallback_world=fallback_world,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        normalized_departments = _pad_departments(
            _normalize_departments(payload.get("departments") or []),
            list(fallback_world["departments"]),
            difficulty=seed["difficulty"],
        )
        merged = {
            **fallback_world,
            "title": _normalize_chinese_text(payload.get("title"), str(fallback_world["title"])),
            "company_type": _normalize_chinese_text(payload.get("company_type"), str(fallback_world["company_type"])),
            "departments": normalized_departments,
            "main_goal": _normalize_chinese_text(payload.get("main_goal"), str(fallback_world["main_goal"])),
            "organization_background": _normalize_chinese_text(
                payload.get("organization_background"),
                str(fallback_world["organization_background"]),
            ),
            "external_pressure": _normalize_chinese_text(
                payload.get("external_pressure"),
                str(fallback_world["external_pressure"]),
            ),
            "stakeholders": _normalize_chinese_list(payload.get("stakeholders"), list(fallback_world["stakeholders"])),
            "conflict_axes": _normalize_chinese_list(payload.get("conflict_axes"), list(fallback_world["conflict_axes"])),
            "hidden_constraints": _normalize_chinese_list(
                payload.get("hidden_constraints"),
                list(fallback_world["hidden_constraints"]),
            ),
            "reversal_points": _normalize_chinese_list(
                payload.get("reversal_points"),
                list(fallback_world["reversal_points"]),
            ),
            "selected_topics": _pad_topics(
                payload.get("selected_topics") or [],
                list(fallback_world["selected_topics"]),
                difficulty=seed["difficulty"],
            ),
        }
        return validate_case_world(merged), "live"
    except ValidationError as exc:
        builder_log("case-world", f"模型输出未通过 case_world 校验，回退 fallback。reason={exc} payload={payload!r}")
        return validate_case_world(fallback_world), "fallback"
    except Exception as exc:
        builder_log(
            "case-world",
            f"模型输出后处理失败，回退 fallback。reason={exc.__class__.__name__}: {exc}",
        )
        return validate_case_world(fallback_world), "fallback"


def generate_case_world(case_seed: dict[str, object], *, llm_client: JsonLLMClient | None = None) -> dict[str, object]:
    case_world, _mode = generate_case_world_with_mode(case_seed, llm_client=llm_client)
    return case_world
