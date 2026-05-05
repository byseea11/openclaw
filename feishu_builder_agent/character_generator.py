from __future__ import annotations

import random
import re
from typing import Any

from .builder_settings import resolve_difficulty_settings
from .llm_client import JsonLLMClient
from .logging_utils import builder_log
from .prompt_templates import build_character_prompts
from .schemas import ValidationError, validate_case_world, validate_characters

NAME_LIBRARY = [
    "林晨",
    "周宇",
    "陈雪",
    "王源",
    "高骏",
    "赵敏",
    "何然",
    "秦怡",
    "罗天",
    "苏禾",
    "唐越",
    "许薇",
    "顾宁",
    "韩朔",
]
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

ROLE_BLUEPRINTS: dict[str, list[dict[str, Any]]] = {
    "产品": [
        {
            "role_key": "product_manager",
            "role": "产品经理",
            "responsibility": "负责统一目标、范围和对外口径。",
            "communication_style": "谨慎、强调跨部门对齐。",
            "conflict_bias": "会阻止过早对外承诺。",
            "stance": "倾向于先收敛内部事实再决定说法。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握跨部门上下游信息",
            "default_channels": ["main_chat", "customer_sync_chat"],
        }
    ],
    "研发": [
        {
            "role_key": "engineering_lead",
            "role": "研发负责人",
            "responsibility": "负责核心依赖、改动窗口和技术可交付性判断。",
            "communication_style": "直接、强调事实和依赖。",
            "conflict_bias": "会指出实现风险和隐性 blocker。",
            "stance": "倾向于先锁依赖再承诺日期。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握技术依赖和改动细节",
            "default_channels": ["main_chat", "launch_window_thread"],
        },
        {
            "role_key": "engineering_pm",
            "role": "研发项目经理",
            "responsibility": "负责跟踪工程侧承诺和跨团队动作。",
            "communication_style": "条理化、会追问闭环。",
            "conflict_bias": "会推动承诺落到明确 owner。",
            "stance": "倾向于把风险拆成可执行动作。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握工程推进状态",
            "default_channels": ["main_chat", "launch_window_thread"],
        },
    ],
    "架构": [
        {
            "role_key": "architecture_owner",
            "role": "架构负责人",
            "responsibility": "负责关键技术方案边界和系统稳定性判断。",
            "communication_style": "抽象能力强、强调长期影响。",
            "conflict_bias": "会反对短期绕过架构约束的方案。",
            "stance": "倾向于先确认架构边界再推进发布日期。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握关键系统依赖与架构风险",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "安全": [
        {
            "role_key": "security_reviewer",
            "role": "安全评审",
            "responsibility": "负责高风险能力评审与放行条件。",
            "communication_style": "规则优先、直接指出边界。",
            "conflict_bias": "会拒绝未完成评审的高风险能力。",
            "stance": "倾向于在风险材料齐备前收紧承诺。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握风险和合规约束",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "合规": [
        {
            "role_key": "compliance_owner",
            "role": "合规负责人",
            "responsibility": "负责监管、审计和流程合规边界。",
            "communication_style": "谨慎、偏规则化表达。",
            "conflict_bias": "会阻止没有合规结论的上线动作。",
            "stance": "倾向于先拿到合规结论再确认对外口径。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握审计与监管要求",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "风控": [
        {
            "role_key": "risk_control_owner",
            "role": "风控负责人",
            "responsibility": "负责评估业务风险暴露和控制策略。",
            "communication_style": "偏保守、会强调风险后果。",
            "conflict_bias": "会放大潜在事故影响。",
            "stance": "倾向于先降低风险暴露再给承诺。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握业务风险敞口和控制要求",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "运维": [
        {
            "role_key": "operations_lead",
            "role": "运维负责人",
            "responsibility": "负责上线窗口、回滚预案和演练闭环。",
            "communication_style": "保守、强调放行条件。",
            "conflict_bias": "会收紧乐观窗口判断。",
            "stance": "倾向于先满足回滚条件再放行。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握窗口和演练状态",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "站点可靠性工程": [
        {
            "role_key": "sre_owner",
            "role": "站点可靠性工程负责人",
            "responsibility": "负责可靠性目标、容量和监控门槛。",
            "communication_style": "数据化、强调可观测性和容量边界。",
            "conflict_bias": "会否定没有监控和容量余量的窗口判断。",
            "stance": "倾向于先满足可靠性门槛再放行。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握稳定性和容量风险",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "数据平台": [
        {
            "role_key": "data_platform_owner",
            "role": "数据平台负责人",
            "responsibility": "负责数据链路、迁移、回填和校验平台。",
            "communication_style": "细节导向、强调数据一致性。",
            "conflict_bias": "会指出数据切换与校验窗口风险。",
            "stance": "倾向于先锁定数据切换条件再承诺窗口。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握数据平台和迁移链路细节",
            "default_channels": ["launch_window_thread", "main_chat"],
        }
    ],
    "销售": [
        {
            "role_key": "sales_owner",
            "role": "客户经理",
            "responsibility": "负责管理客户预期和对外同步节奏。",
            "communication_style": "结果导向、强调时间压力。",
            "conflict_bias": "会推动更明确的对外说法。",
            "stance": "倾向于尽快形成可同步口径。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握客户侧压力信息",
            "default_channels": ["customer_sync_chat", "main_chat"],
        }
    ],
    "市场": [
        {
            "role_key": "marketing_owner",
            "role": "市场负责人",
            "responsibility": "负责发布传播节奏和外部活动安排。",
            "communication_style": "节奏导向、强调对外窗口一致性。",
            "conflict_bias": "会推动尽快明确可传播时间点。",
            "stance": "倾向于尽早锁定对外节奏，但能接受保守表述。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握市场活动与传播计划",
            "default_channels": ["customer_sync_chat", "main_chat"],
        }
    ],
    "客户成功": [
        {
            "role_key": "customer_success",
            "role": "客户成功经理",
            "responsibility": "负责解释风险、控制客户感知和后续跟进。",
            "communication_style": "平衡、关注客户稳定性。",
            "conflict_bias": "会反对会引发反复改口的承诺。",
            "stance": "倾向于先给保守口径再逐步更新。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握客户影响面和升级风险",
            "default_channels": ["customer_sync_chat", "main_chat"],
        }
    ],
    "运营": [
        {
            "role_key": "ops_business_owner",
            "role": "业务运营负责人",
            "responsibility": "负责上线后的业务承接、规则切换和内部运营流程。",
            "communication_style": "关注执行细节和业务影响。",
            "conflict_bias": "会强调流程切换和业务承接风险。",
            "stance": "倾向于先确认运营承接方案再放量。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握业务运营切换和执行细节",
            "default_channels": ["main_chat", "customer_sync_chat"],
        }
    ],
    "客服": [
        {
            "role_key": "support_owner",
            "role": "客服负责人",
            "responsibility": "负责异常话术、客户反馈和问题升级路径。",
            "communication_style": "实务导向、强调用户感知。",
            "conflict_bias": "会担心改口对一线解释造成压力。",
            "stance": "倾向于先准备客户问答和异常话术。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握一线反馈和工单压力",
            "default_channels": ["customer_sync_chat", "main_chat"],
        }
    ],
    "测试": [
        {
            "role_key": "qa_lead",
            "role": "测试负责人",
            "responsibility": "负责验证风险和放行前缺陷状态。",
            "communication_style": "系统化、会强调验证条件。",
            "conflict_bias": "会阻止质量不确定的上线。",
            "stance": "倾向于先收敛高优问题。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握验证结论和问题清单",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "法务": [
        {
            "role_key": "legal_partner",
            "role": "法务合作伙伴",
            "responsibility": "负责对外承诺和合同风险边界。",
            "communication_style": "谨慎、强调措辞风险。",
            "conflict_bias": "会反对超出合同边界的说法。",
            "stance": "倾向于先限定对外承诺范围。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握合同与合规约束",
            "default_channels": ["customer_sync_chat", "main_chat"],
        }
    ],
    "数据": [
        {
            "role_key": "data_owner",
            "role": "数据负责人",
            "responsibility": "负责数据迁移、校验和回填方案。",
            "communication_style": "细节导向、强调前置依赖。",
            "conflict_bias": "会放大迁移窗口和校验风险。",
            "stance": "倾向于先锁定迁移条件再做承诺。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握迁移与校验细节",
            "default_channels": ["launch_window_thread", "main_chat"],
        }
    ],
    "财务": [
        {
            "role_key": "finance_owner",
            "role": "财务负责人",
            "responsibility": "负责收入确认、预算影响和成本风险评估。",
            "communication_style": "谨慎、会强调经营影响。",
            "conflict_bias": "会反对造成财务风险的过度承诺。",
            "stance": "倾向于先确认经营影响再给时间承诺。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握预算与经营风险",
            "default_channels": ["main_chat", "customer_sync_chat"],
        }
    ],
    "采购": [
        {
            "role_key": "procurement_owner",
            "role": "采购负责人",
            "responsibility": "负责外部资源、第三方服务和交付依赖采购。",
            "communication_style": "强调外部依赖和交付边界。",
            "conflict_bias": "会放大供应商交付不确定性。",
            "stance": "倾向于先锁定外部依赖交付再推进窗口。",
            "risk_preference": "低风险偏好",
            "information_access_level": "掌握供应商和采购交付状态",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
    "商务": [
        {
            "role_key": "biz_ops_owner",
            "role": "商务负责人",
            "responsibility": "负责合同条款、商务承诺和外部协作节奏。",
            "communication_style": "偏谈判式、关注承诺边界。",
            "conflict_bias": "会收紧超出合同边界的口径。",
            "stance": "倾向于在条款明确前保守表述。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握商务承诺和外部依赖情况",
            "default_channels": ["customer_sync_chat", "main_chat"],
        }
    ],
    "人力": [
        {
            "role_key": "people_partner",
            "role": "HRBP",
            "responsibility": "负责关键岗位排班、值班和组织协调资源。",
            "communication_style": "协调型、强调资源可用性。",
            "conflict_bias": "会指出人力排班和值守约束。",
            "stance": "倾向于先确认关键值守资源再推进窗口。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握排班和值守资源情况",
            "default_channels": ["main_chat"],
        }
    ],
    "项目管理办公室": [
        {
            "role_key": "pmo_owner",
            "role": "项目管理办公室负责人",
            "responsibility": "负责跨部门里程碑、风险台账和升级节奏。",
            "communication_style": "结构化、强调闭环和节奏。",
            "conflict_bias": "会要求承诺、风险和 owner 显式化。",
            "stance": "倾向于把复杂问题拆成可追踪动作。",
            "risk_preference": "中等风险偏好",
            "information_access_level": "掌握全局项目节奏和升级路径",
            "default_channels": ["main_chat", "launch_window_thread"],
        }
    ],
}


def _to_person_id(role_key: str, index: int) -> str:
    return f"{role_key}_{index + 1:02d}"


def _to_simulated_open_id(person_id: str) -> str:
    return f"ou_sim_{person_id}"


def _fallback_characters(case_world: dict[str, Any]) -> dict[str, Any]:
    world = validate_case_world(case_world)
    difficulty_settings = resolve_difficulty_settings(world["difficulty"])
    rng = random.Random(world["seed"])
    names = NAME_LIBRARY[:]
    rng.shuffle(names)
    selected_departments = list(world["departments"])
    role_pool: list[tuple[str, dict[str, Any]]] = []
    for department in selected_departments:
        role_pool.extend((department, item) for item in ROLE_BLUEPRINTS.get(department, []))
    if len(role_pool) < 8:
        for department, templates in ROLE_BLUEPRINTS.items():
            for item in templates:
                if (department, item) not in role_pool:
                    role_pool.append((department, item))
            if len(role_pool) >= 8:
                break
    min_count = difficulty_settings["character_count_min"]
    max_count = difficulty_settings["character_count_max"]
    target_count = min(max_count, max(min_count, len(selected_departments)))
    target_count = min(target_count, len(role_pool))
    characters = []
    for index, role_info in enumerate(role_pool[:target_count]):
        department, template = role_info
        role_key = template["role_key"]
        name = names[index]
        person_id = _to_person_id(role_key, index)
        characters.append(
            {
                "person_id": person_id,
                "simulated_open_id": _to_simulated_open_id(person_id),
                "name": name,
                "department": department,
                "role": template["role"],
                "responsibility": template["responsibility"],
                "communication_style": template["communication_style"],
                "conflict_bias": template["conflict_bias"],
                "stance": template["stance"],
                "risk_preference": template["risk_preference"],
                "information_access_level": template["information_access_level"],
                "default_channels": template["default_channels"],
            }
        )
    return {"case_id": world["case_id"], "characters": characters}


def _normalize_live_characters(
    payload: dict[str, Any],
    fallback: dict[str, Any],
    *,
    world: dict[str, Any],
) -> dict[str, Any]:
    fallback_characters = list(fallback["characters"])
    difficulty_settings = resolve_difficulty_settings(world["difficulty"])
    max_count = int(difficulty_settings["character_count_max"])
    min_count = int(difficulty_settings["character_count_min"])
    rows = payload.get("characters")
    if not isinstance(rows, list):
        return fallback
    normalized: list[dict[str, Any]] = []
    seen_person_ids: set[str] = set()
    fallback_by_department: dict[str, list[dict[str, Any]]] = {}
    for item in fallback_characters:
        fallback_by_department.setdefault(str(item["department"]), []).append(item)
    for row in rows:
        if not isinstance(row, dict):
            continue
        department = str(row.get("department") or "").strip()
        if not department or not _CJK_RE.search(department):
            continue
        template_candidates = fallback_by_department.get(department) or []
        fallback_template = template_candidates[0] if template_candidates else None
        if fallback_template is None:
            continue
        person_id = str(row.get("person_id") or fallback_template["person_id"]).strip()
        if not person_id or person_id in seen_person_ids:
            person_id = fallback_template["person_id"]
        seen_person_ids.add(person_id)
        name = str(row.get("name") or fallback_template["name"]).strip()
        if not name or not _CJK_RE.search(name):
            name = fallback_template["name"]
        normalized.append(
            {
                "person_id": person_id,
                "simulated_open_id": f"ou_sim_{person_id}",
                "name": name,
                "department": department,
                "role": str(row.get("role") or fallback_template["role"]).strip() or fallback_template["role"],
                "responsibility": str(row.get("responsibility") or fallback_template["responsibility"]).strip() or fallback_template["responsibility"],
                "communication_style": str(row.get("communication_style") or fallback_template["communication_style"]).strip() or fallback_template["communication_style"],
                "conflict_bias": str(row.get("conflict_bias") or fallback_template["conflict_bias"]).strip() or fallback_template["conflict_bias"],
                "stance": str(row.get("stance") or fallback_template["stance"]).strip() or fallback_template["stance"],
                "risk_preference": str(row.get("risk_preference") or fallback_template["risk_preference"]).strip() or fallback_template["risk_preference"],
                "information_access_level": str(row.get("information_access_level") or fallback_template["information_access_level"]).strip() or fallback_template["information_access_level"],
                "default_channels": row.get("default_channels") or fallback_template["default_channels"],
            }
        )
        if len(normalized) >= max_count:
            break
    if len(normalized) < min_count:
        for item in fallback_characters:
            if item["person_id"] in seen_person_ids:
                continue
            normalized.append(item)
            seen_person_ids.add(item["person_id"])
            if len(normalized) >= min_count:
                break
    return {"case_id": world["case_id"], "characters": normalized[:max_count]}


def generate_characters(
    case_world: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    characters, _mode = generate_characters_with_mode(case_world, llm_client=llm_client)
    return characters


def generate_characters_with_mode(
    case_world: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    world = validate_case_world(case_world)
    fallback = _fallback_characters(world)
    if llm_client is None:
        return validate_characters(fallback), "fallback"
    system_prompt, user_prompt = build_character_prompts(
        world=world,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        normalized_payload = _normalize_live_characters(payload, fallback, world=world)
        return validate_characters(normalized_payload), "live"
    except ValidationError as exc:
        builder_log("characters", f"模型输出未通过 characters 校验，回退 fallback。reason={exc} payload={payload!r}")
        return validate_characters(fallback), "fallback"
    except Exception as exc:
        builder_log("characters", f"模型输出后处理失败，回退 fallback。reason={exc.__class__.__name__}: {exc}")
        return validate_characters(fallback), "fallback"
