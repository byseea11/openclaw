from __future__ import annotations

from ..schemas import validate_case_world


def build_case_world(*, case_spec: dict[str, object], capability_brief: dict[str, object]) -> dict[str, object]:
    family_id = str(case_spec["family_id"])
    task_id = str(case_spec["task_id"])
    templates = {
        "anti_interference": {
            "organization": "飞书企业协作组",
            "team": "任务 Wiki 联调项目组",
            "business_goal": f"在发布周内完成 {task_id} 和两条相似任务线的负责人协同。",
            "scenario_summary": "同一批项目经理同时盯三个相似任务，群聊里经常把不同任务的 owner、风险和 blocker 交叉提到一起。",
            "family_fit_explanation": "这个场景天然包含共享角色和相似任务，很适合测试系统能否只回答 target task 的上下文。",
        },
        "contradiction_update": {
            "organization": "飞书基础工程部",
            "team": "发布排期保障组",
            "business_goal": f"围绕 {task_id} 连续修正负责人和发布时间窗口，保证最终排期口径一致。",
            "scenario_summary": "群里多次修正 owner 和窗口时间，早期口径被后续消息覆盖，但旧消息仍然保留在历史中。",
            "family_fit_explanation": "这个场景天然有多轮 supersede 更新，适合测试 current vs historical 的区分能力。",
        },
        "evidence_dependency_reasoning": {
            "organization": "飞书交付工程平台",
            "team": "上线证据与依赖治理组",
            "business_goal": f"围绕 {task_id} 判断真实 blocker 的证据来源，并据此收口上游迁移窗口与下游回滚预案。",
            "scenario_summary": "群里同时出现正式确认、转述和模糊口径；只有区分证据强弱，才能判断上游风险是否真实存在以及它会如何影响下游任务。",
            "family_fit_explanation": "这个场景天然要求系统一边做证据归因，一边解释 upstream -> target -> downstream 的影响链。",
        },
    }
    payload = {
        "case_id": case_spec["case_id"],
        "family_id": family_id,
        **templates[family_id],
        "brief_required_case_structure": capability_brief["required_case_structure"],
    }
    return validate_case_world(payload)
