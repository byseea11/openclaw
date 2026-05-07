from __future__ import annotations

from typing import Any

from ..schemas import validate_official_file_plan


def _actor_ids(story_plan: dict[str, Any]) -> list[str]:
    actors = [str(actor["actor_id"]) for actor in story_plan.get("actors", []) if actor.get("actor_id")]
    return actors or ["alice", "bob", "carol", "xavier"]


def build_official_file_plan(
    *,
    case_context: dict[str, Any],
    story_plan: dict[str, Any],
) -> dict[str, Any]:
    task_id = str(case_context["task_id"])
    family_id = str(case_context["family_id"])
    actors = _actor_ids(story_plan)
    private_family = family_id == "private_info_in_official_file"
    private_info_items = [
        {
            "private_info_ref": "private_info_001",
            "person_ref": actors[0],
            "private_info_summary": "该同事本周三下午有个人安排，只能异步补充意见。",
            "must_not_become_task_state": True,
        },
        {
            "private_info_ref": "private_info_002",
            "person_ref": actors[1 % len(actors)],
            "private_info_summary": "该同事私下承诺会先看一版材料，但这不是正式 owner 变更。",
            "must_not_become_task_state": True,
        },
        {
            "private_info_ref": "private_info_003",
            "person_ref": actors[2 % len(actors)],
            "private_info_summary": "该同事偏好把风险说明写进 checklist 附注，不代表任务结论已改变。",
            "must_not_become_task_state": True,
        },
        {
            "private_info_ref": "private_info_004",
            "person_ref": actors[3 % len(actors)],
            "private_info_summary": "该同事和客户有私聊背景，需要作为解释上下文但不能成为正式发布口径。",
            "must_not_become_task_state": True,
        },
    ]
    if not private_family:
        private_info_items = private_info_items[:1]
    payload = {
        "case_id": case_context["case_id"],
        "family_id": family_id,
        "task_id": task_id,
        "official_files": [
            {
                "file_ref": "official_file_001",
                "file_type": "release_checklist",
                "title": f"{task_id} 上线 checklist",
                "authority_level": "formal_task_record",
                "official_conclusions": [
                    f"{task_id} 的 current state 只能以正式 checklist 的任务项结论为准。",
                    "个人备注可以作为 evidence/context，但不能直接变成任务 current state。",
                ],
                "private_info_items": private_info_items,
                "task_relevance_boundaries": [
                    "个人时间限制不是任务阻塞，除非 owner 在正式任务项里明确升级。",
                    "私下承诺不是正式 owner 变更。",
                    "文件附注中的个人偏好不能替代正式结论。",
                    "聊天转述如果和 checklist 冲突，必须回到正式文件和最新纠偏消息。",
                ],
            },
            {
                "file_ref": "official_file_002",
                "file_type": "meeting_minutes",
                "title": f"{task_id} 风险复盘纪要",
                "authority_level": "formal_meeting_record",
                "official_conclusions": [
                    "复盘纪要只确认任务风险归属，不确认个人私事会改变发布计划。",
                    "所有 current-state 问答必须区分正式结论和个人上下文。",
                ],
                "private_info_items": private_info_items[:2],
                "task_relevance_boundaries": [
                    "纪要里的个人背景用于解释沟通延迟，不用于改写任务状态。",
                    "误读消息需要被后续纠偏消息覆盖。",
                ],
            },
            {
                "file_ref": "official_file_003",
                "file_type": "risk_register",
                "title": f"{task_id} 风险登记表",
                "authority_level": "formal_risk_record",
                "official_conclusions": [
                    "风险登记表只记录任务风险和处理人，不记录个人偏好为任务结论。",
                ],
                "private_info_items": private_info_items[:1],
                "task_relevance_boundaries": [
                    "个人偏好只能作为沟通背景，不是风险状态。",
                ],
            },
        ],
    }
    return validate_official_file_plan(payload)
