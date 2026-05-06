from __future__ import annotations

from typing import Any

from .schemas import validate_memory_failure_blueprint, validate_task_actor_layout


_SLOT_LIBRARY = [
    ("product_owner_1", "产品", "产品负责人"),
    ("engineering_owner_1", "研发", "研发负责人"),
    ("ops_owner_1", "运维", "运维负责人"),
    ("security_reviewer_1", "安全", "安全评审"),
    ("finance_partner_1", "财务", "财务合作方"),
    ("customer_manager_1", "销售", "客户经理"),
]


def generate_task_actor_layout(blueprint: dict[str, Any]) -> dict[str, Any]:
    validated = validate_memory_failure_blueprint(blueprint)
    target_task = {
        "task_id": validated["task_id"],
        "title": f"{validated['task_id']} 任务推进",
        "task_scope": "围绕目标任务当前负责人、阻塞项、依赖和对外口径形成可验证的任务记忆。",
    }
    distractor_ids: list[str] = []
    shared_actor_slot_ids: list[str] = []
    pollution_dimensions: list[str] = []
    for trap in validated["traps"]:
        for task_id in trap["common"]["distractor_tasks"]:
            if task_id not in distractor_ids:
                distractor_ids.append(task_id)
        for actor_slot in trap["common"]["shared_actors"]:
            if actor_slot not in shared_actor_slot_ids:
                shared_actor_slot_ids.append(actor_slot)
        typed_payload = trap["typed_payload"]
        for dimension in typed_payload.get("pollution_dimensions", []):
            if dimension not in pollution_dimensions:
                pollution_dimensions.append(dimension)
    distractor_tasks = [
        {
            "task_id": task_id,
            "title": f"{task_id} 关联任务",
            "relationship_to_target": "与目标任务共享人员或依赖，是制造 Memory.md 干扰项的来源。",
        }
        for task_id in distractor_ids
    ]
    slot_index = {slot_id: (department, role_label) for slot_id, department, role_label in _SLOT_LIBRARY}
    shared_actor_slots = []
    for actor_slot_id in shared_actor_slot_ids:
        department, role_label = slot_index.get(actor_slot_id, ("产品", "协作角色"))
        task_ids = [validated["task_id"]] + distractor_ids[:2]
        shared_actor_slots.append(
            {
                "actor_slot_id": actor_slot_id,
                "department": department,
                "role_label": role_label,
                "task_ids": task_ids,
            }
        )
    for slot_id, department, role_label in _SLOT_LIBRARY:
        if slot_id in {item["actor_slot_id"] for item in shared_actor_slots}:
            continue
        shared_actor_slots.append(
            {
                "actor_slot_id": slot_id,
                "department": department,
                "role_label": role_label,
                "task_ids": [validated["task_id"]],
            }
        )
    overlap = [
        {
            "actor_slot_id": item["actor_slot_id"],
            "task_ids": item["task_ids"],
            "overlap_reason": "共享人员是制造任务记忆污染和跨任务误引用的主要手段。",
        }
        for item in shared_actor_slots
    ]
    return validate_task_actor_layout(
        {
            "case_id": validated["case_id"],
            "task_id": validated["task_id"],
            "target_task": target_task,
            "distractor_tasks": distractor_tasks,
            "shared_actor_slots": shared_actor_slots,
            "pollution_dimensions": pollution_dimensions or ["shared_actor", "similar_status_wording"],
            "task_actor_overlap": overlap,
        }
    )
