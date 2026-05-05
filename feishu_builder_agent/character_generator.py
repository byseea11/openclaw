from __future__ import annotations

import random
from typing import Any

from .llm_client import JsonLLMClient
from .schemas import ValidationError, validate_case_spec, validate_characters, validate_story


ROLE_LIBRARY = [
    ("product", "产品", "产品经理", "负责界定范围，并保持内部外部口径一致。", "谨慎、强调对齐。", "会主动反对过早承诺。"),
    ("engineering", "研发", "后端负责人", "评估后端工作量和隐藏依赖。", "技术导向、风险敏感。", "会指出集成和时序风险。"),
    ("frontend", "前端", "前端负责人", "负责界面范围和交付顺序。", "务实、表达具体。", "会反对范围不清的需求。"),
    ("qa", "测试", "测试负责人", "负责验证范围和发布信心。", "系统化、重证据。", "会阻止质量不确定的上线。"),
    ("security", "安全", "安全评审", "负责权限、审计和合规影响评估。", "直接、规则优先。", "会拒绝未经评审的风险。"),
    ("operations", "运维", "SRE 负责人", "负责上线窗口和回滚准备。", "偏运营、较保守。", "会指出发布窗口风险。"),
    ("sales", "销售", "客户经理", "推动形成面向客户的承诺。", "紧迫、结果导向。", "容易把节奏推向更激进承诺。"),
    ("customer_success", "客服成功", "客户成功经理", "承接客户诉求和时间压力。", "升级导向、以客户为中心。", "会放大客户侧紧迫感。"),
    ("management", "管理", "技术负责人", "平衡权衡取舍和决策质量。", "冷静、善于综合。", "会追问更清晰的责任归属。"),
]

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
]


def _to_person_id(role_key: str, index: int) -> str:
    return f"{role_key}_{index + 1:02d}"


def _to_simulated_open_id(person_id: str) -> str:
    return f"ou_sim_{person_id}"


def _fallback_characters(spec: dict[str, Any]) -> dict[str, Any]:
    spec = validate_case_spec(spec)
    rng = random.Random(spec["seed"])
    role_pool = ROLE_LIBRARY[:]
    rng.shuffle(role_pool)
    names = NAME_LIBRARY[:]
    rng.shuffle(names)
    selected = role_pool[: max(6, min(10, len(spec["departments"]) + 2))]
    characters = []
    for index, role_info in enumerate(selected):
        role_key, department, role, responsibility, communication_style, conflict_bias = role_info
        name = names[index]
        characters.append(
            {
                "person_id": _to_person_id(role_key, index),
                "simulated_open_id": _to_simulated_open_id(_to_person_id(role_key, index)),
                "name": name,
                "department": department,
                "role": role,
                "responsibility": responsibility,
                "communication_style": communication_style,
                "conflict_bias": conflict_bias,
                "stance": f"{department} 侧会围绕自己的职责对 {spec['task_id']} 提出明确立场。",
                "risk_preference": "中等风险偏好" if department in {"产品", "销售", "客户成功"} else "低风险偏好",
                "information_access_level": "掌握跨部门上下游信息" if department in {"产品", "管理"} else "掌握本职能关键事实",
                "default_channels": ["main_chat", "customer_sync_chat"] if department in {"销售", "客户成功"} else ["main_chat", "launch_window_thread"],
            }
        )
    return {"case_id": spec["case_id"], "characters": characters}


def generate_characters(
    case_spec: dict[str, Any],
    story: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    characters, _mode = generate_characters_with_mode(case_spec, story, llm_client=llm_client)
    return characters


def generate_characters_with_mode(
    case_spec: dict[str, Any],
    story: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    spec = validate_case_spec(case_spec)
    validated_story = validate_story(story)
    if llm_client is None:
        return validate_characters(_fallback_characters(spec)), "fallback"
    system_prompt = (
        "Generate a concise role roster for one enterprise software delivery case. "
        "Return only JSON with keys: case_id, characters. characters must be an array of 6 to 10 objects. "
        "Each object must contain person_id, simulated_open_id, name, department, role, responsibility, communication_style, conflict_bias, "
        "stance, risk_preference, information_access_level, default_channels. "
        "All natural-language strings must be written in Simplified Chinese. "
        "Only person_id and simulated_open_id may remain snake_case."
    )
    user_prompt = (
        f"Case spec:\n{spec}\nStory:\n{validated_story}\n"
        "请生成 6 到 10 个覆盖至少 5 个部门的角色。所有自然语言字段必须使用简体中文，字段尽量简短。"
        "person_id must be stable snake_case strings. simulated_open_id must look like a synthetic Feishu open_id such as "
        "'ou_sim_security_01'. default_channels should be string arrays such as "
        "['main_chat', 'launch_window_thread', 'customer_sync_chat']."
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return validate_characters(payload), "live"
    except (Exception, ValidationError):
        return validate_characters(_fallback_characters(spec)), "fallback"
