from __future__ import annotations

from typing import Any

from ..builder_settings import resolve_difficulty_settings
from ..schemas import validate_case_world, validate_case_world_artifact


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
        "private_info_in_official_file": {
            "organization": "飞书知识治理与发布协作组",
            "team": "正式文件边界治理小组",
            "business_goal": f"围绕 {task_id} 区分正式文件结论、聊天转述和个人私有背景，避免任务状态被个人信息污染。",
            "scenario_summary": "上线 checklist、复盘纪要和风险登记表里夹杂个人备注；群里多人引用、误读和纠正这些内容，最终必须回到正式任务结论。",
            "family_fit_explanation": "这个场景天然包含 official authority 与 personal-private context 的边界，适合测试系统是否会把个人信息误投影成任务 current state。",
        },
    }
    payload = {
        "case_id": case_spec["case_id"],
        "family_id": family_id,
        **templates[family_id],
        "brief_required_case_structure": capability_brief["required_case_structure"],
    }
    return validate_case_world(payload)


_SESSION_TYPE_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "main_chat": ("main_chat", "主群协调", "沉淀目标任务的主线协作信息和最终 current state。"),
    "handoff_thread": ("handoff_thread", "交接修正线程", "承载 owner 交接、旧状态修正和 supersession 说明。"),
    "risk_review_thread": ("risk_review_thread", "风险复核线程", "承载依赖、风险和证据分层补充信息。"),
    "customer_sync_chat": ("customer_sync_chat", "客户同步侧群", "承接外部压力、模糊口径和对外同步上下文。"),
    "exec_sync_chat": ("exec_sync_chat", "管理层同步侧群", "承载跨部门升级、相似措辞和并行决策噪声。"),
    "qa_triage_chat": ("chat", "质量联调群", "承载测试、验收、缺陷确认和状态复核。"),
    "ops_window_thread": ("thread", "运维窗口线程", "承载发布窗口、迁移窗口和运维配合细节。"),
    "dependency_sync_chat": ("chat", "依赖同步群", "承载上下游依赖、阻塞原因和影响传播。"),
    "doc_followup_thread": ("thread", "文档补充线程", "承载文档、公告和口径补充说明。"),
    "support_escalation_chat": ("chat", "支持升级群", "承载客户反馈、支持升级和外部压力。"),
}


def _session_template_for(session_id: str) -> tuple[str, str, str]:
    if session_id in _SESSION_TYPE_TEMPLATES:
        return _SESSION_TYPE_TEMPLATES[session_id]
    if session_id.endswith("_thread"):
        return ("thread", f"{session_id} 线程", "承载局部修正、依赖或补充说明。")
    return ("chat", f"{session_id} 会话", "承载目标任务相关的补充协作上下文。")


def build_case_world_artifact(
    *,
    case_context: dict[str, Any],
    task_actor_layout_artifact: dict[str, Any],
    story_plan: dict[str, Any],
) -> dict[str, Any]:
    del task_actor_layout_artifact
    seen_session_ids: set[str] = set()
    source_sessions: list[dict[str, str]] = []
    for beat in story_plan["message_beats"]:
        session_id = str(beat["session_id"])
        if session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        session_type, title, purpose = _session_template_for(session_id)
        source_sessions.append(
            {
                "session_id": session_id,
                "session_type": session_type,
                "title": title,
                "session_purpose": purpose,
            }
        )
    recommended_session_count = int(resolve_difficulty_settings(str(case_context["difficulty"]))["recommended_session_count"])
    for session_id in _SESSION_TYPE_TEMPLATES:
        if len(source_sessions) >= recommended_session_count:
            break
        if session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        session_type, title, purpose = _session_template_for(session_id)
        source_sessions.append(
            {
                "session_id": session_id,
                "session_type": session_type,
                "title": title,
                "session_purpose": purpose,
            }
        )
    payload = {
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task_id": case_context["task_id"],
        "organization": case_context["organization"],
        "team": case_context["team"],
        "business_goal": case_context["business_goal"],
        "scenario_summary": case_context["scenario_summary"],
        "family_fit_explanation": case_context["family_fit_explanation"],
        "source_sessions": source_sessions,
    }
    return validate_case_world_artifact(payload)
