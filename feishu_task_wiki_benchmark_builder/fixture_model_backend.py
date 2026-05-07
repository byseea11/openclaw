from __future__ import annotations

from itertools import cycle
from typing import Any

from .builder_settings import resolve_difficulty_settings
from .stages.capability_brief import build_memory_capability_brief
from .stages.case_spec import build_case_spec
from .stages.case_world import build_case_world
from .stages.family_selection import select_family


def build_fixture_case_context(
    *,
    seed: int | None,
    requested_family_id: str | None,
    difficulty: str,
    comparison_target: str,
) -> dict[str, Any]:
    selection = select_family(seed=seed, requested_family_id=requested_family_id)
    family_id = selection["family_id"]
    capability_brief = build_memory_capability_brief(family_id=family_id)
    case_spec = build_case_spec(
        family_id=family_id,
        difficulty=difficulty,
        seed=selection["seed"],
        comparison_target=comparison_target,
    )
    case_world = build_case_world(case_spec=case_spec, capability_brief=capability_brief)
    return {
        "family_id": family_id,
        "benchmark_requirement_name": capability_brief["benchmark_requirement_name"],
        "benchmark_requirement_summary": capability_brief["benchmark_requirement_summary"],
        "report_display_name": capability_brief["report_display_name"],
        "capability_under_test": capability_brief["capability_under_test"],
        "why_memory_systems_may_fail": capability_brief["why_memory_systems_may_fail"],
        "generation_rules": capability_brief["generation_rules"],
        "required_case_structure": capability_brief["required_case_structure"],
        "probe_strategy": capability_brief["probe_strategy"],
        "expected_good_system_behavior": capability_brief["expected_good_system_behavior"],
        "case_id": case_spec["case_id"],
        "task_id": case_spec["task_id"],
        "seed": case_spec["seed"],
        "difficulty": case_spec["difficulty"],
        "comparison_target": case_spec["comparison_target"],
        "organization": case_world["organization"],
        "team": case_world["team"],
        "business_goal": case_world["business_goal"],
        "scenario_summary": case_world["scenario_summary"],
        "family_fit_explanation": case_world["family_fit_explanation"],
    }


def _base_actors() -> list[dict[str, Any]]:
    return [
        {
            "actor_id": "alice",
            "display_name": "Alice",
            "simulated_open_id": "ou_alice",
            "role": "program_manager",
            "task_roles": [],
        },
        {
            "actor_id": "bob",
            "display_name": "Bob",
            "simulated_open_id": "ou_bob",
            "role": "engineering_owner",
            "task_roles": [],
        },
        {
            "actor_id": "carol",
            "display_name": "Carol",
            "simulated_open_id": "ou_carol",
            "role": "risk_reviewer",
            "task_roles": [],
        },
        {
            "actor_id": "xavier",
            "display_name": "Xavier",
            "simulated_open_id": "ou_xavier",
            "role": "release_coordinator",
            "task_roles": [],
        },
    ]


def build_fixture_story_plan(*, case_context: dict[str, Any]) -> dict[str, Any]:
    family_id = str(case_context["family_id"])
    task_id = str(case_context["task_id"])
    story_id = f"story_{case_context['case_id']}"
    builders = {
        "anti_interference": _build_anti_interference_story,
        "contradiction_update": _build_contradiction_update_story,
        "evidence_dependency_reasoning": _build_evidence_dependency_reasoning_story,
        "private_info_in_official_file": _build_private_info_official_file_story,
    }
    return builders[family_id](
        story_id=story_id,
        case_context=case_context,
        task_id=task_id,
    )


def _build_anti_interference_story(
    *,
    story_id: str,
    case_context: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    target_task = task_id
    distractor_a = f"{task_id}-DOC"
    distractor_b = f"{task_id}-OPS"
    actors = _base_actors()
    return {
        "story_id": story_id,
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task": {"task_id": target_task, "task_name": "Task Wiki 发布准备", "role": "target_task"},
        "actors": actors,
        "task_actor_layout": {
            "target_task_id": target_task,
            "shared_actors": ["alice", "bob"],
            "interference_context_blocks": [
                {
                    "context_ref": "ctx_doc_review",
                    "context_label": "并行文档收口讨论",
                    "noise_source_type": "shared_actor_noise",
                    "relationship_to_target": "共享 Alice，容易把文档收口的角色信息污染到目标任务。",
                },
                {
                    "context_ref": "ctx_ops_rehearsal",
                    "context_label": "运维演练 blocker 讨论",
                    "noise_source_type": "similar_wording_noise",
                    "relationship_to_target": "共享 Bob 和相似 blocker 措辞，容易造成 scope 污染。",
                },
            ],
            "actor_task_roles": [
                {"actor_id": "alice", "task_id": target_task, "role": "target_owner"},
                {"actor_id": "alice", "context_ref": "ctx_doc_review", "role": "reviewer"},
                {"actor_id": "bob", "context_ref": "ctx_ops_rehearsal", "role": "ops_owner"},
            ],
        },
        "state_changes": [
            {
                "task_id": target_task,
                "field": "owner",
                "sequence": [{"value": "Alice", "status": "current"}],
            },
        ],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "purpose": "introduce_target_owner",
                "speaker_actor_id": "alice",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"{target_task} 现在由 Alice 负责推进，本周只看发布准备，不含运维演练。",
                "family_linkage": "scope_boundary",
            },
            {
                "beat_id": "beat_002",
                "purpose": "introduce_distractor_ops",
                "speaker_actor_id": "bob",
                "speaker": "Bob",
                "session_id": "main_chat",
                "message_intent": f"{distractor_b} 还卡在运维演练，Bob 负责盯这个 blocker。",
                "family_linkage": "shared_actor_noise",
            },
            {
                "beat_id": "beat_003",
                "purpose": "introduce_distractor_doc",
                "speaker_actor_id": "carol",
                "speaker": "Carol",
                "session_id": "thread_docs",
                "message_intent": f"{distractor_a} 的文档收口今晚由 Alice 审一轮，但这不是 {target_task} 的 owner 变更。",
                "family_linkage": "shared_actor_noise",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{target_task} 当前是谁在负责？请不要把运维演练或文档收口的负责人混进来。",
                "tests_family": case_context["family_id"],
                "expected_good_behavior": f"只回答 Alice 负责 {target_task}，并明确 Bob/Alice 在其他任务的角色不应混入当前答案。",
            }
        ],
    }


def _build_contradiction_update_story(
    *,
    story_id: str,
    case_context: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    return {
        "story_id": story_id,
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task": {"task_id": task_id, "task_name": "上线接入方案", "role": "target_task"},
        "actors": _base_actors(),
        "task_actor_layout": {
            "target_task_id": task_id,
            "revision_context_blocks": [
                {
                    "context_ref": "ctx_owner_handoff",
                    "field": "owner",
                    "revision_role": "historical_update",
                    "relationship_to_target": "Bob -> Alice -> Xavier 的交接链会诱发历史 owner 残留。",
                },
                {
                    "context_ref": "ctx_window_shift",
                    "field": "release_window",
                    "revision_role": "superseded_schedule",
                    "relationship_to_target": "发布时间多轮修正，容易让系统保留旧窗口。",
                },
            ],
            "supersession_clues": ["之前口径作废", "最终确认以本轮为准"],
            "shared_actors": ["alice"],
            "actor_task_roles": [
                {"actor_id": "bob", "task_id": task_id, "role": "initial_owner"},
                {"actor_id": "alice", "task_id": task_id, "role": "historical_owner"},
                {"actor_id": "xavier", "task_id": task_id, "role": "current_owner"},
            ],
        },
        "state_changes": [
            {
                "task_id": task_id,
                "field": "owner",
                "sequence": [
                    {"value": "Bob", "status": "initial"},
                    {"value": "Alice", "status": "historical"},
                    {"value": "Xavier", "status": "current"},
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
                "speaker_actor_id": "alice",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"{task_id} 先由 Bob 跟进，初版窗口先按 5 月 5 日看。",
                "family_linkage": "initial_state",
            },
            {
                "beat_id": "beat_002",
                "purpose": "supersede_owner_once",
                "speaker_actor_id": "alice",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"Bob 下周要去处理别的上线，{task_id} 改成 Alice 接手，窗口改到 5 月 7 日。",
                "family_linkage": "historical_state",
            },
            {
                "beat_id": "beat_003",
                "purpose": "final_current_owner",
                "speaker_actor_id": "carol",
                "speaker": "Carol",
                "session_id": "thread_release",
                "message_intent": f"最终确认：{task_id} 由 Xavier 收口，正式窗口以 5 月 9 日为准，之前口径都作废。",
                "family_linkage": "current_state",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{task_id} 当前负责人是谁？Bob 和 Alice 现在还负责吗？上线窗口最终以哪一天为准？",
                "tests_family": case_context["family_id"],
                "expected_good_behavior": "回答 Xavier 是当前负责人，Bob/Alice 只是历史负责人，最终窗口以 5 月 9 日为准。",
            }
        ],
    }


def _build_evidence_dependency_reasoning_story(
    *,
    story_id: str,
    case_context: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    upstream_task = f"{task_id}-UP"
    downstream_task = f"{task_id}-DOWN"
    return {
        "story_id": story_id,
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task": {"task_id": task_id, "task_name": "发布主任务", "role": "target_task"},
        "actors": _base_actors(),
        "task_actor_layout": {
            "target_task_id": task_id,
            "shared_actors": ["carol", "xavier"],
            "dependency_context_blocks": [
                {
                    "context_ref": "ctx_upstream_window",
                    "context_label": "迁移窗口确认链路",
                    "dependency_role": "verified_anchor",
                    "evidence_strength": "verified",
                    "impact_on_target": "上游窗口未锁定，会直接阻塞目标任务对外承诺。",
                },
                {
                    "context_ref": "ctx_window_hearsay",
                    "context_label": "窗口缓解传闻",
                    "dependency_role": "hearsay_channel",
                    "evidence_strength": "hearsay",
                    "impact_on_target": "错误地相信窗口已确认，会让系统过早承诺上线时间。",
                },
                {
                    "context_ref": "ctx_target_assessment",
                    "context_label": "目标任务模糊判断",
                    "dependency_role": "ambiguous_channel",
                    "evidence_strength": "ambiguous",
                    "impact_on_target": "模糊判断不能替代正式确认，但容易被 summary 压成结论。",
                },
                {
                    "context_ref": "ctx_downstream_rollback",
                    "context_label": "回滚预案验收影响",
                    "dependency_role": "downstream_impact",
                    "evidence_strength": "derived_from_verified",
                    "impact_on_target": "目标任务不锁窗口时，下游回滚预案验收也会被顺延。",
                },
            ],
            "actor_task_roles": [
                {"actor_id": "carol", "context_ref": "ctx_upstream_window", "role": "verified_source"},
                {"actor_id": "bob", "context_ref": "ctx_window_hearsay", "role": "hearsay_source"},
                {"actor_id": "alice", "task_id": task_id, "role": "ambiguous_source"},
                {"actor_id": "xavier", "task_id": task_id, "role": "target_owner"},
                {"actor_id": "alice", "context_ref": "ctx_downstream_rollback", "role": "rollback_owner"},
            ],
        },
        "state_changes": [
            {
                "task_id": task_id,
                "field": "upstream_dependency_status",
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
                "task_id": task_id,
                "field": "downstream_dependency_impact",
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
                "speaker_actor_id": "carol",
                "speaker": "Carol",
                "session_id": "main_chat",
                "message_intent": f"我刚和迁移负责人确认过，{upstream_task} 的窗口今天还没锁定，所以 {task_id} 先不要对外承诺 5 月 8 日上线。",
                "family_linkage": "verified_evidence",
            },
            {
                "beat_id": "beat_002",
                "purpose": "hearsay_relief_claim",
                "speaker_actor_id": "bob",
                "speaker": "Bob",
                "session_id": "main_chat",
                "message_intent": "我听别人说窗口其实差不多定了，感觉可以先照常往外报，但我没看到正式确认。",
                "family_linkage": "hearsay",
            },
            {
                "beat_id": "beat_003",
                "purpose": "ambiguous_target_assessment",
                "speaker_actor_id": "alice",
                "speaker": "Alice",
                "session_id": "thread_release",
                "message_intent": f"直觉上风险可能没那么大，不过如果没有正式窗口邮件，{task_id} 这边还是不敢锁最终时间。",
                "family_linkage": "ambiguous",
            },
            {
                "beat_id": "beat_004",
                "purpose": "downstream_dependency_impact",
                "speaker_actor_id": "alice",
                "speaker": "Alice",
                "session_id": "thread_release",
                "message_intent": f"如果 {task_id} 不能锁上线窗口，那 {downstream_task} 的回滚预案验收也只能一起顺延。",
                "family_linkage": "impact_chain",
            },
            {
                "beat_id": "beat_005",
                "purpose": "target_owner_summary",
                "speaker_actor_id": "xavier",
                "speaker": "Xavier",
                "session_id": "thread_release",
                "message_intent": f"结论先按 Carol 的确认走：当前真正 blocker 是 {upstream_task} 的窗口未锁定，这会同时卡住 {task_id} 和 {downstream_task}。",
                "family_linkage": "target_summary",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{task_id} 现在的真实 blocker 是什么？依据来自谁、哪条消息？Bob 和 Alice 的说法为什么不能直接当正式确认？这个 blocker 又是怎样影响 {downstream_task} 的？",
                "tests_family": case_context["family_id"],
                "expected_good_behavior": f"应以 Carol 的明确确认作为主要证据，指出真正 blocker 是 {upstream_task} 的窗口未锁定；说明 Bob 是 hearsay、Alice 只是模糊判断，二者都不能替代正式确认；并解释它如何阻塞 {task_id} 以及顺延 {downstream_task}。",
            }
        ],
    }


def _build_private_info_official_file_story(
    *,
    story_id: str,
    case_context: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    actors = _base_actors()
    return {
        "story_id": story_id,
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task": {"task_id": task_id, "task_name": "正式文件边界确认", "role": "target_task"},
        "actors": actors,
        "task_actor_layout": {
            "target_task_id": task_id,
            "official_file_context_blocks": [
                {
                    "context_ref": "ctx_release_checklist",
                    "file_type": "release_checklist",
                    "relationship_to_target": "正式 checklist 中同时出现任务结论和个人备注。",
                },
                {
                    "context_ref": "ctx_private_note",
                    "file_type": "meeting_minutes",
                    "relationship_to_target": "个人私有信息只能解释沟通延迟，不能改写任务 current state。",
                },
            ],
            "shared_actors": ["alice", "bob", "carol"],
            "actor_task_roles": [
                {"actor_id": "alice", "task_id": task_id, "role": "target_owner"},
                {"actor_id": "bob", "context_ref": "ctx_private_note", "role": "private_info_subject"},
                {"actor_id": "carol", "context_ref": "ctx_release_checklist", "role": "official_file_owner"},
                {"actor_id": "xavier", "task_id": task_id, "role": "boundary_reviewer"},
            ],
        },
        "state_changes": [
            {
                "task_id": task_id,
                "field": "official_release_status",
                "sequence": [
                    {"value": "待正式 checklist 确认", "status": "initial"},
                    {"value": "以正式 checklist 的任务项结论为准", "status": "current"},
                ],
            },
            {
                "task_id": task_id,
                "field": "private_info_boundary",
                "sequence": [{"value": "个人备注只作为上下文", "status": "current"}],
            },
        ],
        "message_beats": [
            {
                "beat_id": "beat_001",
                "purpose": "official_file_anchor",
                "speaker_actor_id": "carol",
                "speaker": "Carol",
                "session_id": "main_chat",
                "message_intent": f"{task_id} 的正式 checklist 已更新：任务状态只按 checklist 的任务项结论走，个人备注不能当作 blocker。",
                "family_linkage": "official_file_reference",
            },
            {
                "beat_id": "beat_002",
                "purpose": "private_info_exposed",
                "speaker_actor_id": "bob",
                "speaker": "Bob",
                "session_id": "thread_release",
                "message_intent": "我周三下午只能异步看材料，这个个人安排可以写在备注里，但别把它写成发布阻塞。",
                "family_linkage": "personal_private_context",
            },
            {
                "beat_id": "beat_003",
                "purpose": "misread_private_info",
                "speaker_actor_id": "alice",
                "speaker": "Alice",
                "session_id": "main_chat",
                "message_intent": f"我看到 Bob 的备注差点以为 {task_id} 要延期，但回看 checklist 发现正式结论没有这么写。",
                "family_linkage": "misread_or_overgeneralization",
            },
            {
                "beat_id": "beat_004",
                "purpose": "boundary_correction",
                "speaker_actor_id": "xavier",
                "speaker": "Xavier",
                "session_id": "thread_release",
                "message_intent": f"纠偏一下：{task_id} 当前状态还是按正式文件结论，不把 Bob 的个人时间安排投影成任务 current state。",
                "family_linkage": "task_relevance_boundary",
            },
        ],
        "planned_probe_queries": [
            {
                "query": f"{task_id} 当前正式结论是什么？Bob 的个人安排是否会改变任务 current state？请说明依据。",
                "tests_family": case_context["family_id"],
                "expected_good_behavior": "回答 current state 以正式 checklist 为准，Bob 的个人安排只是上下文或 evidence，不会改变任务状态。",
            }
        ],
    }


def build_fixture_conversation_plan(*, user_payload: dict[str, Any]) -> dict[str, Any]:
    case_context = dict(user_payload["case_context"])
    case_world = dict(user_payload["case_world_artifact"])
    story_plan = dict(user_payload["story_plan"])
    official_file_plan = dict(user_payload.get("official_file_plan") or {})
    difficulty = resolve_difficulty_settings(str(case_context["difficulty"]))
    target_total = int(difficulty["total_turn_count_min"])
    target_event = int(difficulty["event_bearing_turn_count_min"])
    sessions = list(case_world["source_sessions"])
    characters = list((user_payload.get("characters") or {}).get("characters") or [])
    actors = [
        {"actor_id": str(item["person_id"]), "display_name": str(item["name"])}
        for item in characters
        if item.get("person_id") and item.get("name")
    ] or [
        {
            "actor_id": str(item["actor_id"]),
            "display_name": str(item.get("display_name") or item["actor_id"]),
        }
        for item in story_plan["actors"]
    ]
    official_files = list(official_file_plan.get("official_files") or [])
    official_refs = [str(item["file_ref"]) for item in official_files] or ["official_file_001"]
    private_refs = [
        str(info["private_info_ref"])
        for file in official_files
        for info in file.get("private_info_items", [])
    ] or ["private_info_001"]
    turns: list[dict[str, Any]] = []
    task_id = str(case_context["task_id"])

    def append_turn(
        *,
        session: dict[str, Any],
        actor: dict[str, Any],
        text: str,
        turn_kind: str,
        beat_id: str = "",
        annotation_target: bool = False,
        event_bearing: bool = False,
        official_file_ref: str = "",
        private_info_ref: str = "",
        boundary: str = "",
    ) -> None:
        turns.append(
            {
                "turn_id": f"turn_{len(turns) + 1:03d}",
                "beat_id": beat_id,
                "sequence_no": len(turns) + 1,
                "session_id": str(session["session_id"]),
                "speaker_actor_id": str(actor["actor_id"]),
                "speaker": str(actor["display_name"]),
                "planned_message_text": text,
                "turn_kind": turn_kind,
                "annotation_target": annotation_target,
                "event_bearing": event_bearing,
                "official_file_ref": official_file_ref,
                "private_info_ref": private_info_ref,
                "task_relevance_boundary": boundary,
            }
        )

    actor_iter = cycle(actors)
    session_iter = cycle(sessions)
    for index, beat in enumerate(story_plan["message_beats"]):
        append_turn(
            session=next(
                (item for item in sessions if item["session_id"] == beat["session_id"]),
                sessions[index % len(sessions)],
            ),
            actor=next(
                (item for item in actors if item["actor_id"] == beat["speaker_actor_id"]),
                actors[index % len(actors)],
            ),
            text=str(beat["message_intent"]),
            turn_kind="event_bearing",
            beat_id=str(beat["beat_id"]),
            annotation_target=True,
            event_bearing=True,
            official_file_ref=official_refs[index % len(official_refs)],
        )

    event_templates = [
        "{task} 的正式文件这次只确认任务项结论，个人附注不升级成 blocker。",
        "我复核了文件引用，{task} 的 owner 没有因为私下承诺发生变化。",
        "{task} 的风险登记只接受正式确认，群里转述需要再核一遍来源。",
        "这条可以作为 evidence：正式纪要说 current state 仍待文件 owner 最终确认。",
        "请把这条和上一条放在一起看，个人安排不是 {task} 的状态更新。",
    ]
    while sum(1 for turn in turns if turn["event_bearing"]) < target_event:
        index = len(turns)
        append_turn(
            session=next(session_iter),
            actor=next(actor_iter),
            text=f"{event_templates[index % len(event_templates)].format(task=task_id)}（证据轮次 {index + 1}）",
            turn_kind="event_bearing",
            event_bearing=True,
            official_file_ref=official_refs[index % len(official_refs)],
            private_info_ref=private_refs[index % len(private_refs)] if index % 3 == 0 else "",
            boundary="个人背景不能替代正式任务结论。" if index % 3 == 0 else "",
        )

    support_templates = [
        "我先把文件链接贴回主群，大家不要只看转述截图。",
        "这个上下文有用，但问任务当前状态时还是要回到正式记录。",
        "旁边项目也有类似 checklist，别把那边的个人备注带过来。",
        "我理解这个备注为什么会被误读，所以这里单独标成 context。",
        "如果后面文件 owner 改口，再用最新文件覆盖旧消息。",
        "这条只是确认收到，不进入 annotation gold。",
        "我会在同步里注明：个人限制不是发布计划变更。",
        "刚才那句像结论，其实只是对文件附注的解释。",
        "请在任务页只写正式结论，聊天背景保留在 evidence。",
        "这轮先不要把私聊承诺写成 owner 变更。",
    ]
    kinds = cycle(("context_support", "interference_noise", "ack_or_coordination", "revision_bridge"))
    while len(turns) < target_total:
        index = len(turns)
        kind = next(kinds)
        append_turn(
            session=next(session_iter),
            actor=next(actor_iter),
            text=f"{support_templates[index % len(support_templates)]}（{task_id} / {index + 1}）",
            turn_kind=kind,
            official_file_ref=official_refs[index % len(official_refs)] if index % 2 == 0 else "",
            private_info_ref=private_refs[index % len(private_refs)] if index % 4 == 0 else "",
            boundary="这条只作为 context/evidence，不投影为 current state。" if index % 4 == 0 else "",
        )

    return {
        "case_id": case_context["case_id"],
        "family_id": case_context["family_id"],
        "task_id": task_id,
        "sessions": sessions,
        "turns": turns,
    }


def build_fixture_semantic_gold(*, user_payload: dict[str, Any]) -> dict[str, Any]:
    case_context = user_payload["case_context"]
    annotation_gold = list(user_payload.get("observed_evidence_rows") or user_payload.get("annotation_gold") or [])
    message_ids = [str(row["message_id"]) for row in annotation_gold]
    return {
        "expected_task_facts": [
            {
                "fact_id": f"fact_{index:03d}",
                "claim": str(row["evidence_text"]),
                "required_supporting_message_ids": [str(row["message_id"])],
            }
            for index, row in enumerate(annotation_gold, start=1)
        ],
        "expected_event_semantics": [
            {
                "event_semantic_id": f"event_semantic_{index:03d}",
                "purpose": str(row.get("purpose") or "observed_event"),
                "required_supporting_message_ids": [str(row["message_id"])],
            }
            for index, row in enumerate(annotation_gold, start=1)
        ],
        "expected_query_answers": [
            {
                "query_id": f"{case_context['case_id']}_semantic_query_{index:03d}",
                "query": str(probe["query"]),
                "expected_answer_summary": str(probe["expected_good_behavior"]),
                "required_supporting_message_ids": message_ids,
            }
            for index, probe in enumerate(user_payload["planned_probe_queries"], start=1)
        ],
    }
