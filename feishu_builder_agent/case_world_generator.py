from __future__ import annotations

from typing import Any

from .builder_settings import resolve_difficulty_settings
from .schemas import (
    validate_case_spec,
    validate_case_world_v3,
    validate_memory_failure_blueprint,
    validate_task_actor_layout,
)


def generate_case_world(
    case_spec: dict[str, Any],
    memory_failure_blueprint: dict[str, Any],
    task_actor_layout: dict[str, Any],
) -> dict[str, Any]:
    spec = validate_case_spec(case_spec)
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    layout = validate_task_actor_layout(task_actor_layout)
    session_blueprint = list(resolve_difficulty_settings(spec["difficulty"])["session_blueprint"])
    source_sessions = []
    for session_id in session_blueprint:
        if session_id == "session_main_chat":
            source_type = "chat"
            source_ref = "chat:main_chat"
            chat_ref = "main_chat"
            title = "主群协调"
            purpose = "沉淀目标任务的主线协作信息和最终 current state。"
        elif session_id.endswith("_thread"):
            source_type = "thread"
            source_ref = f"thread:{session_id.removeprefix('session_')}"
            chat_ref = "main_chat"
            title = "线程补充讨论"
            purpose = "承载修正、依赖和局部事实补充，制造 cross-source revision。"
        else:
            source_type = "chat"
            source_ref = f"chat:{session_id.removeprefix('session_')}"
            chat_ref = session_id.removeprefix("session_")
            title = "侧向补充聊天"
            purpose = "承载 distractor context、客户同步或风险补充信息。"
        source_sessions.append(
            {
                "session_id": session_id,
                "source_type": source_type,
                "source_ref": source_ref,
                "chat_ref": chat_ref,
                "title": title,
                "session_purpose": purpose,
            }
        )
    return validate_case_world_v3(
        {
            "case_id": spec["case_id"],
            "task_id": spec["task_id"],
            "title": spec["title_hint"] or f"{spec['task_id']} 任务记忆失败回放",
            "company_type": spec["company_type"] or "企业软件协作团队",
            "business_context": "团队正在推进一个跨产品、研发、运维和安全的任务，消息会分散在主群、线程和侧向聊天里。",
            "case_generation_goal": {
                "baseline": spec["comparison_target"],
                "goal": "构造一组会让 Memory.md 在任务边界、当前态和证据可追溯性上失败，但能被 Task Wiki 正确处理的数据。",
            },
            "memory_failure_profile": {
                "selected_failure_modes": blueprint["selected_failure_modes"],
                "primary_failure_mode": blueprint["primary_failure_mode"],
            },
            "task_and_actor_layout_summary": "目标任务与多个 distractor task 共享角色、依赖和相似措辞，天然适合制造任务记忆污染和静态状态失真。",
            "distractor_memory_context": [
                f"{item['task_id']} 会与 {spec['task_id']} 共享人员和类似 blocker 表述，适合作为干扰任务。"
                for item in layout["distractor_tasks"]
            ],
            "discussion_reasons": [
                "为什么这些人会讨论：目标任务跨多部门推进，需要同时协调发布时间、风险和客户口径。",
                "为什么信息会分散：真实协作会把不同粒度的信息拆到主群、线程和侧群里。",
                "为什么会有模糊表达：部分说法来自猜测、传话或弱承诺，天然不适合直接写成确定事实。",
                "为什么旧状态会被修正：依赖、owner 和窗口会随着新证据出现被连续更新。",
            ],
            "info_distribution_reason": "主群负责定方向，线程补细节，客户同步群承接外部压力，因此同一结论会以不同粒度散落在多个 source。",
            "ambiguity_reason": "为了控制对外风险，协作方会使用保守、模糊或未完成承诺的措辞，这些信息不能直接升级为 verified fact。",
            "revision_reason": "随着迁移窗口、安全结论和 owner 交接变化，旧状态必须被 supersede，否则记忆会 stale。",
            "source_sessions": source_sessions,
        }
    )


def generate_case_world_with_mode(
    case_spec: dict[str, Any],
    memory_failure_blueprint: dict[str, Any],
    task_actor_layout: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> tuple[dict[str, Any], str]:
    del llm_client
    return generate_case_world(case_spec, memory_failure_blueprint, task_actor_layout), "fallback"
