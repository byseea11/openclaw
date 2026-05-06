from __future__ import annotations

from dataclasses import dataclass

from .config import FORMAL_FAMILY_IDS


@dataclass(frozen=True)
class FamilyDefinition:
    family_id: str
    display_name: str
    benchmark_requirement_name: str
    benchmark_requirement_summary: str
    report_display_name: str
    capability_under_test: str
    why_memory_systems_may_fail: str
    generation_rules: list[str]
    required_case_structure: list[str]
    probe_strategy: list[str]
    expected_good_system_behavior: list[str]
    story_plan_emphasis: list[str]


FAMILY_CATALOG: dict[str, FamilyDefinition] = {
    "anti_interference": FamilyDefinition(
        family_id="anti_interference",
        display_name="抗干扰",
        benchmark_requirement_name="抗干扰测试",
        benchmark_requirement_summary="在大量无关任务、共享角色和相似字段噪音下，仍然准确捞取目标任务的关键记忆。",
        report_display_name="抗干扰测试",
        capability_under_test="在共享角色和相似任务并存时，只回答目标任务的当前上下文，不把噪音任务的信息混入答案。",
        why_memory_systems_may_fail="系统容易把共享角色在其他任务上的信息误并入目标任务，导致回答范围污染，即使相关消息都被记住了也会答偏。",
        generation_rules=[
            "正式 contract 里只能有 1 个目标任务，不能把 distractor task 当成并列正式 task。",
            "必须存在 shared actors、跨任务噪声或相似措辞来源，让系统需要做 task boundary 判断。",
            "query 不能只问显式字段，必须逼系统区分目标任务和其他任务上下文的边界。",
        ],
        required_case_structure=[
            "target_task",
            "distractor_context",
            "shared_actors",
            "scope_limited_query_need",
        ],
        probe_strategy=[
            "让 query 同时提到目标任务和相似任务背景。",
            "要求系统明确排除非目标任务信息。",
        ],
        expected_good_system_behavior=[
            "只回答目标任务的当前负责人、状态和阻塞。",
            "显式说明相似任务的信息不应混入当前答案。",
        ],
        story_plan_emphasis=["task_actor_layout", "planned_probe_queries"],
    ),
    "contradiction_update": FamilyDefinition(
        family_id="contradiction_update",
        display_name="矛盾更新",
        benchmark_requirement_name="矛盾更新测试",
        benchmark_requirement_summary="当先后输入冲突口径时，系统能够理解时间顺序，让新指令覆盖旧指令。",
        report_display_name="矛盾更新测试",
        capability_under_test="在多个状态更新发生后，识别哪个值已经被覆盖，哪个值仍是当前值，并明确旧口径已经作废。",
        why_memory_systems_may_fail="系统容易记住较早的显式值，却忽略后续修正和 supersede 关系，最终把 stale value 当成 current value。",
        generation_rules=[
            "必须有至少 3 段状态：initial、historical、current。",
            "更新必须通过真实消息落地，不能只在结构化字段里声明。",
            "probe 必须逼系统同时区分 current 和 historical。",
        ],
        required_case_structure=[
            "target_task",
            "owner_or_schedule_field",
            "multi_step_update_sequence",
            "supersedes_relation",
        ],
        probe_strategy=[
            "查询当前状态，同时追问历史状态是否仍然有效。",
            "要求系统明确指出哪个值已经 stale。",
        ],
        expected_good_system_behavior=[
            "返回 current value，并标注历史值已经失效。",
            "解释更新发生在哪些消息里。",
        ],
        story_plan_emphasis=["state_changes", "planned_probe_queries"],
    ),
    "evidence_dependency_reasoning": FamilyDefinition(
        family_id="evidence_dependency_reasoning",
        display_name="证据驱动的依赖推理",
        benchmark_requirement_name="证据验证 + 依赖传播",
        benchmark_requirement_summary="系统不仅要指出哪条消息是真实依据，还要解释该依据对应的上游状态如何影响下游任务。",
        report_display_name="证据验证与依赖传播",
        capability_under_test="区分 verified fact、转述和猜测，并据此解释上游风险源如何影响目标任务和下游任务。",
        why_memory_systems_may_fail="系统容易把模糊说法和转述当成事实，或者只记住上游/下游片段却拼不出基于证据的影响链。",
        generation_rules=[
            "必须同时出现 verified、ambiguous、hearsay 几类说法，并且这些说法围绕同一条依赖链展开。",
            "正式 contract 里只保留 1 个目标任务；upstream/downstream 作为依赖上下文出现，不作为并列正式 task。",
            "query 必须同时要求证据归因和 impact chain 解释，而不只是要 blocker 结论。",
        ],
        required_case_structure=[
            "upstream_dependency_context",
            "downstream_dependency_context",
            "blocking_or_risk_source",
            "evidence_strength_gradient",
            "impact_chain",
        ],
        probe_strategy=[
            "提问时要求说明依据来自谁、哪条消息。",
            "追问哪些说法只是猜测或转述，哪些能作为真实 blocker 依据。",
            "要求解释该依据如何影响目标任务和下游任务。",
        ],
        expected_good_system_behavior=[
            "给出 blocker 或风险结论时附带证据引用。",
            "把 hearsay 和猜测显式降级，不当成 verified fact。",
            "解释 upstream -> downstream 的影响链。",
        ],
        story_plan_emphasis=["task_actor_layout", "state_changes", "message_beats", "planned_probe_queries"],
    ),
}


def get_family_definition(family_id: str) -> FamilyDefinition:
    try:
        return FAMILY_CATALOG[family_id]
    except KeyError as exc:
        raise KeyError(f"Unknown family_id: {family_id}") from exc


def ordered_family_ids() -> list[str]:
    return [family_id for family_id in FORMAL_FAMILY_IDS if family_id in FAMILY_CATALOG]
