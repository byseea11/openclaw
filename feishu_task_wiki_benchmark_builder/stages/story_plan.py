from __future__ import annotations

from typing import Any

from ..schemas import validate_story_plan


def _base_actors() -> list[dict[str, Any]]:
    return [
        {
            "actor_id": "alice",
            "display_name": "Alice",
            "simulated_open_id": "ou_alice",
            "task_roles": [],
        },
        {
            "actor_id": "bob",
            "display_name": "Bob",
            "simulated_open_id": "ou_bob",
            "task_roles": [],
        },
        {
            "actor_id": "carol",
            "display_name": "Carol",
            "simulated_open_id": "ou_carol",
            "task_roles": [],
        },
        {
            "actor_id": "xzy",
            "display_name": "xzy",
            "simulated_open_id": "ou_xzy",
            "task_roles": [],
        },
    ]


def build_story_plan(
    *,
    case_spec: dict[str, Any],
    case_world: dict[str, Any],
    capability_brief: dict[str, Any],
) -> dict[str, Any]:
    family_id = str(case_spec["family_id"])
    task_id = str(case_spec["task_id"])
    story_id = f"story_{case_spec['case_id']}"
    builders = {
        "anti_interference": _build_anti_interference_story,
        "contradiction_update": _build_contradiction_update_story,
        "evidence_dependency_reasoning": _build_evidence_dependency_reasoning_story,
    }
    payload = builders[family_id](
        story_id=story_id,
        case_spec=case_spec,
        case_world=case_world,
        capability_brief=capability_brief,
        task_id=task_id,
    )
    return validate_story_plan(payload)


def _build_anti_interference_story(
    *,
    story_id: str,
    case_spec: dict[str, Any],
    case_world: dict[str, Any],
    capability_brief: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    target_task = task_id
    distractor_a = f"{task_id}-DOC"
    distractor_b = f"{task_id}-OPS"
    actors = _base_actors()
    payload = {
        "story_id": story_id,
        "case_id": case_spec["case_id"],
        "family_id": case_spec["family_id"],
        "tasks": [
            {"task_id": target_task, "task_name": "Task Wiki 发布准备", "role": "target_task"},
            {"task_id": distractor_a, "task_name": "文档收口", "role": "distractor_task"},
            {"task_id": distractor_b, "task_name": "运维演练", "role": "distractor_task"},
        ],
        "actors": actors,
        "task_actor_layout": {
            "target_task": target_task,
            "distractor_tasks": [distractor_a, distractor_b],
            "shared_actors": ["alice", "bob"],
            "actor_task_roles": [
                {"actor_id": "alice", "task_id": target_task, "role": "target_owner"},
                {"actor_id": "alice", "task_id": distractor_a, "role": "reviewer"},
                {"actor_id": "bob", "task_id": distractor_b, "role": "ops_owner"},
            ],
        },
        "state_changes": [
            {
                "task_id": target_task,
                "field": "owner",
                "sequence": [
                    {"value": "Alice", "status": "current"},
                ],
            },
            {
                "task_id": distractor_b,
                "field": "blocker",
                "sequence": [
                    {"value": "运维演练未完成", "status": "current"},
                ],
            },
        ],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "purpose": "introduce_target_owner",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"{target_task} 现在由 Alice 负责推进，本周只看发布准备，不含运维演练。",
                "family_linkage": "scope_boundary",
            },
            {
                "beat_id": "beat_002",
                "purpose": "introduce_distractor_ops",
                "speaker": "Bob",
                "session_id": "main_chat",
                "message_intent": f"{distractor_b} 还卡在运维演练，Bob 负责盯这个 blocker。",
                "family_linkage": "shared_actor_noise",
            },
            {
                "beat_id": "beat_003",
                "purpose": "introduce_distractor_doc",
                "speaker": "Carol",
                "session_id": "thread_docs",
                "message_intent": f"{distractor_a} 的文档收口今晚由 Alice 审一轮，但这不是 {target_task} 的 owner 变更。",
                "family_linkage": "shared_actor_noise",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{target_task} 当前是谁在负责？请不要把运维演练或文档收口的负责人混进来。",
                "tests_family": case_spec["family_id"],
                "expected_good_behavior": f"只回答 Alice 负责 {target_task}，并明确 Bob/Alice 在其他任务的角色不应混入当前答案。",
            }
        ],
    }
    return payload


def _build_contradiction_update_story(
    *,
    story_id: str,
    case_spec: dict[str, Any],
    case_world: dict[str, Any],
    capability_brief: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    payload = {
        "story_id": story_id,
        "case_id": case_spec["case_id"],
        "family_id": case_spec["family_id"],
        "tasks": [
            {"task_id": task_id, "task_name": "上线接入方案", "role": "target_task"},
        ],
        "actors": _base_actors(),
        "task_actor_layout": {
            "target_task": task_id,
            "distractor_tasks": [],
            "shared_actors": ["alice"],
            "actor_task_roles": [
                {"actor_id": "bob", "task_id": task_id, "role": "initial_owner"},
                {"actor_id": "alice", "task_id": task_id, "role": "historical_owner"},
                {"actor_id": "xzy", "task_id": task_id, "role": "current_owner"},
            ],
        },
        "state_changes": [
            {
                "task_id": task_id,
                "field": "owner",
                "sequence": [
                    {"value": "Bob", "status": "initial"},
                    {"value": "Alice", "status": "historical"},
                    {"value": "xzy", "status": "current"},
                ],
            },
            {
                "task_id": task_id,
                "field": "release_window",
                "sequence": [
                    {"value": "5 月 5 日", "status": "initial"},
                    {"value": "5 月 7 日", "status": "historical"},
                    {"value": "5 月 9 日", "status": "current"},
                ],
            },
        ],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "purpose": "establish_initial_owner",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"{task_id} 先由 Bob 跟进，初版窗口先按 5 月 5 日看。",
                "family_linkage": "initial_state",
            },
            {
                "beat_id": "beat_002",
                "purpose": "supersede_owner_once",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"Bob 下周要去处理别的上线，{task_id} 改成 Alice 接手，窗口改到 5 月 7 日。",
                "family_linkage": "historical_state",
            },
            {
                "beat_id": "beat_003",
                "purpose": "final_current_owner",
                "speaker": "Carol",
                "session_id": "thread_release",
                "message_intent": f"最终确认：{task_id} 由 xzy 收口，正式窗口以 5 月 9 日为准，之前口径都作废。",
                "family_linkage": "current_state",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{task_id} 当前负责人是谁？Bob 和 Alice 现在还负责吗？上线窗口最终以哪一天为准？",
                "tests_family": case_spec["family_id"],
                "expected_good_behavior": "回答 xzy 是当前负责人，Bob/Alice 只是历史负责人，最终窗口以 5 月 9 日为准。",
            }
        ],
    }
    return payload


def _build_evidence_dependency_reasoning_story(
    *,
    story_id: str,
    case_spec: dict[str, Any],
    case_world: dict[str, Any],
    capability_brief: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    upstream_task = f"{task_id}-UP"
    downstream_task = f"{task_id}-DOWN"
    payload = {
        "story_id": story_id,
        "case_id": case_spec["case_id"],
        "family_id": case_spec["family_id"],
        "tasks": [
            {"task_id": upstream_task, "task_name": "数据迁移窗口确认", "role": "upstream_task"},
            {"task_id": task_id, "task_name": "发布主任务", "role": "target_task"},
            {"task_id": downstream_task, "task_name": "回滚预案验收", "role": "downstream_task"},
        ],
        "actors": _base_actors(),
        "task_actor_layout": {
            "target_task": task_id,
            "distractor_tasks": [upstream_task, downstream_task],
            "shared_actors": ["carol", "xzy"],
            "actor_task_roles": [
                {"actor_id": "carol", "task_id": upstream_task, "role": "verified_source"},
                {"actor_id": "bob", "task_id": upstream_task, "role": "hearsay_source"},
                {"actor_id": "alice", "task_id": task_id, "role": "ambiguous_source"},
                {"actor_id": "xzy", "task_id": task_id, "role": "target_owner"},
                {"actor_id": "alice", "task_id": downstream_task, "role": "rollback_owner"},
            ],
        },
        "state_changes": [
            {
                "task_id": upstream_task,
                "field": "migration_window_confirmation",
                "sequence": [
                    {"value": "未确认", "status": "initial"},
                    {"value": "Carol 明确表示窗口还没锁定", "status": "current"},
                ],
            },
            {
                "task_id": task_id,
                "field": "release_commitment",
                "sequence": [
                    {"value": "计划 5 月 8 日上线", "status": "initial"},
                    {"value": "等待正式窗口确认后再承诺", "status": "current"},
                ],
            },
            {
                "task_id": downstream_task,
                "field": "rollback_readiness",
                "sequence": [
                    {"value": "待验收", "status": "initial"},
                    {"value": "等待主任务窗口明确后再验收", "status": "current"},
                ],
            },
        ],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "purpose": "verified_upstream_risk",
                "speaker": "Carol",
                "session_id": "main_chat",
                "message_intent": f"我刚和迁移负责人确认过，{upstream_task} 的窗口今天还没锁定，所以 {task_id} 先不要对外承诺 5 月 8 日上线。",
                "family_linkage": "verified_evidence",
            },
            {
                "beat_id": "beat_002",
                "purpose": "hearsay_relief_claim",
                "speaker": "Bob",
                "session_id": "main_chat",
                "message_intent": "我听别人说窗口其实差不多定了，感觉可以先照常往外报，但我没看到正式确认。",
                "family_linkage": "hearsay",
            },
            {
                "beat_id": "beat_003",
                "purpose": "ambiguous_target_assessment",
                "speaker": "Alice",
                "session_id": "thread_release",
                "message_intent": f"直觉上风险可能没那么大，不过如果没有正式窗口邮件，{task_id} 这边还是不敢锁最终时间。",
                "family_linkage": "ambiguous",
            },
            {
                "beat_id": "beat_004",
                "purpose": "downstream_dependency_impact",
                "speaker": "Alice",
                "session_id": "thread_release",
                "message_intent": f"如果 {task_id} 不能锁上线窗口，那 {downstream_task} 的回滚预案验收也只能一起顺延。",
                "family_linkage": "impact_chain",
            },
            {
                "beat_id": "beat_005",
                "purpose": "target_owner_summary",
                "speaker": "xzy",
                "session_id": "thread_release",
                "message_intent": f"结论先按 Carol 的确认走：当前真正 blocker 是 {upstream_task} 的窗口未锁定，这会同时卡住 {task_id} 和 {downstream_task}。",
                "family_linkage": "target_summary",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{task_id} 现在的真实 blocker 是什么？依据来自谁、哪条消息？Bob 和 Alice 的说法为什么不能直接当正式确认？这个 blocker 又是怎样影响 {downstream_task} 的？",
                "tests_family": case_spec["family_id"],
                "expected_good_behavior": f"应以 Carol 的明确确认作为主要证据，指出真正 blocker 是 {upstream_task} 的窗口未锁定；说明 Bob 是 hearsay、Alice 只是模糊判断，二者都不能替代正式确认；并解释它如何阻塞 {task_id} 以及顺延 {downstream_task}。",
            }
        ],
    }
    return payload
