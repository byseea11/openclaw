from __future__ import annotations

from typing import Any


PromptPair = tuple[str, str]


def build_spec_generation_prompts(
    *,
    difficulty: str,
    seed: int,
    comparison_target: str,
    selected_failure_modes: list[str] | None,
    primary_failure_mode: str | None,
    user_hint: str,
) -> PromptPair:
    requested_modes = ", ".join(selected_failure_modes or []) or "由模型结合 difficulty 选择"
    requested_primary = primary_failure_mode or "由模型选择"
    system_prompt = (
        "你是 Task Wiki V3 builder 的 case_spec 生成器。"
        "只输出一个 JSON object，不要输出 Markdown，不要解释。"
        "case_spec 必须是 failure-oriented control artifact，而不是故事摘要。"
    )
    user_prompt = f"""
请生成一个 V3 case_spec JSON。

硬约束：
1. 只输出这些字段：
   - case_id
   - task_id
   - difficulty
   - seed
   - comparison_target
   - selected_failure_modes
   - primary_failure_mode
2. 不要输出 title_hint、main_goal_hint、scenario_profile、department_hints、user_hint。
3. difficulty 固定为：{difficulty}
4. seed 固定为：{seed}
5. comparison_target 固定为：{comparison_target}
6. selected_failure_modes 如果用户已指定，就必须完全使用：{requested_modes}
7. primary_failure_mode 如果用户已指定，就必须完全使用：{requested_primary}
8. task_id 和 case_id 由系统侧控制；即使你输出这两个字段，系统也会按 seed 覆盖为 deterministic ID。
9. 你真正需要决策的是 selected_failure_modes 和 primary_failure_mode，不要把注意力放在命名上。
10. task_id 使用 FEISHU-数字 格式。
11. case_id 使用 case_feishu_xxx_v3 格式。

可选补充意图：
{user_hint or "无"}
""".strip()
    return system_prompt, user_prompt


def build_personal_memory_pollution_blueprint_prompt(case_spec: dict[str, Any]) -> str:
    return f"""
你要生成 personal_memory_pollution 的 Memory.md fail blueprint。
目标任务: {case_spec["task_id"]}
要求:
1. 必须有 target task + distractor tasks + shared actors。
2. 必须制造同一人跨多个任务出现，诱发人员维度污染。
3. probe query 必须逼问当前任务的 owner / blocker / next step，而不是泛泛总结。
禁止:
1. 不要把 distractor task 写成完全无关的噪声。
2. 不要省略 landing_requirements。
示例:
{{
  "trap_id": "trap_owner_pollution_001",
  "failure_mode": "personal_memory_pollution",
  "trap_mechanism": "同一负责人同时参与目标任务和两个相似项目，Memory.md 可能把别的项目 blocker 混入当前任务。",
  "typed_payload": {{
    "target_task_summary": "目标任务需要确认当前 owner 和真实 blocker。",
    "overlapping_slots": ["owner", "blocker", "next_step"],
    "pollution_dimensions": ["shared_actor", "similar_status_wording"],
    "distractor_task_ids": ["FEISHU-291", "FEISHU-377"]
  }}
}}
""".strip()


def build_unverifiable_summary_claim_blueprint_prompt(case_spec: dict[str, Any]) -> str:
    return f"""
你要生成 unverifiable_summary_claim 的 Memory.md fail blueprint。
目标任务: {case_spec["task_id"]}
要求:
1. 必须同时包含 verified fact、ambiguous claim、hearsay、no-event。
2. target_claim 必须是一个容易被误写成确定事实的说法。
3. probe query 必须追问“谁明确说过”“证据在哪”。
示例:
{{
  "trap_id": "trap_finance_claim_001",
  "failure_mode": "unverifiable_summary_claim",
  "trap_mechanism": "把模糊说法和明确事实混在一起，诱发无证据总结。",
  "typed_payload": {{
    "target_claim": "FEISHU-231 当前受财务问题阻塞",
    "evidence_distribution": {{
      "verified_fact_turns": 2,
      "ambiguous_turns": 2,
      "hearsay_turns": 1,
      "weak_commitment_turns": 1,
      "no_event_turns": 2
    }}
  }}
}}
""".strip()


def build_static_memory_stale_state_blueprint_prompt(case_spec: dict[str, Any]) -> str:
    return f"""
你要生成 static_memory_stale_state 的 Memory.md fail blueprint。
目标任务: {case_spec["task_id"]}
要求:
1. 必须让同一个 state field 连续变化至少 3 次。
2. final_current_state 必须和 stale_states 清晰区分。
3. probe query 要问“当前是谁/当前状态是什么”，并追问旧状态是否仍然有效。
示例:
{{
  "trap_id": "trap_owner_handoff_001",
  "failure_mode": "static_memory_stale_state",
  "trap_mechanism": "负责人连续变化，旧负责人仍是真实历史但不应作为当前负责人。",
  "typed_payload": {{
    "required_state_track": {{
      "field": "owner",
      "states": ["Bob", "Alice", "xzy"],
      "final_current_state": "xzy",
      "stale_states": ["Bob", "Alice"]
    }}
  }}
}}
""".strip()


def build_dependency_propagation_failure_blueprint_prompt(case_spec: dict[str, Any]) -> str:
    return f"""
你要生成 dependency_propagation_failure 的 Memory.md fail blueprint。
目标任务: {case_spec["task_id"]}
要求:
1. 必须有 upstream dependency -> target task impact -> current-state correction。
2. query 必须要求回答依赖变化如何影响当前任务。
示例:
{{
  "trap_id": "trap_dependency_shift_001",
  "failure_mode": "dependency_propagation_failure",
  "trap_mechanism": "上游审批条件变化后，目标任务状态已变，但静态总结未传播更新。",
  "typed_payload": {{
    "upstream_task_id": "FEISHU-188",
    "dependency_chain": ["budget approval", "security signoff", "release window"],
    "impacted_field": "launch_readiness",
    "expected_missed_update": "仍把目标任务写成 ready，而没有反映上游卡点回流。"
  }}
}}
""".strip()


def build_memory_failure_blueprint_prompts(case_spec: dict[str, Any]) -> PromptPair:
    sections = []
    for failure_mode in case_spec["selected_failure_modes"]:
        if failure_mode == "personal_memory_pollution":
            sections.append(build_personal_memory_pollution_blueprint_prompt(case_spec))
        elif failure_mode == "unverifiable_summary_claim":
            sections.append(build_unverifiable_summary_claim_blueprint_prompt(case_spec))
        elif failure_mode == "static_memory_stale_state":
            sections.append(build_static_memory_stale_state_blueprint_prompt(case_spec))
        elif failure_mode == "dependency_propagation_failure":
            sections.append(build_dependency_propagation_failure_blueprint_prompt(case_spec))

    system_prompt = (
        "你是 Task Wiki V3 的 memory_failure_blueprint 生成器。"
        "只返回一个 JSON object。"
        "必须为每个 selected_failure_mode 生成至少一个 trap。"
        "trap 必须包含 common.landing_requirements、typed_payload、expected_openclaw_failure、expected_task_wiki_success。"
    )
    user_prompt = "\n\n".join(sections)
    return system_prompt, user_prompt


def build_case_world_prompts(
    spec: dict[str, Any],
    blueprint: dict[str, Any],
    layout: dict[str, Any],
    scaffold: dict[str, Any],
) -> PromptPair:
    system_prompt = (
        "你是 Task Wiki V3 的 case_world 生成器。"
        "只返回一个 JSON object，不要输出 Markdown。"
        "目标是把 failure trap 翻译成自然企业协作背景。"
    )
    user_prompt = f"""
请基于下面的 scaffold 生成更自然、但仍满足 schema 的 case_world JSON。

目标任务：{spec["task_id"]}
primary_failure_mode：{blueprint["primary_failure_mode"]}
selected_failure_modes：{", ".join(blueprint["selected_failure_modes"])}
target_task_title：{layout["target_task"]["title"]}

要求：
1. 必须保留 source_sessions 的结构与 session_id/source_ref/chat_ref。
2. 必须用中文写 title、company_type、business_context、goal、discussion_reasons 等语义字段。
3. 必须明确说明：
   - 为什么这些人会讨论
   - 为什么信息会分散
   - 为什么会有模糊表达
   - 为什么旧状态会被修正
4. 不要删除 failure mode 信息。

scaffold:
{scaffold}
""".strip()
    return system_prompt, user_prompt


def build_conversation_plan_prompts(
    world: dict[str, Any],
    roster: dict[str, Any],
    blueprint: dict[str, Any],
    trajectory: dict[str, Any],
    scaffold: dict[str, Any],
) -> PromptPair:
    system_prompt = (
        "你是 Task Wiki V3 的 conversation_plan 生成器。"
        "只返回一个 JSON object，不要输出 Markdown。"
        "turn 必须承载 benchmark_role、memory_failure_mode、memory_trap 和证据意图。"
    )
    user_prompt = f"""
请基于下面的 scaffold 生成 conversation_plan JSON。

目标任务：{world["task_id"]}
failure modes：{", ".join(blueprint["selected_failure_modes"])}
角色：
{roster["characters"]}
状态轨迹：
{trajectory["transitions"]}

要求：
1. 必须保留 sessions 结构。
2. turns 必须覆盖 scaffold 中已有的所有 benchmark_role，不要减少 turn 数量。
3. 每条 turn 必须保留：
   - turn_id
   - sequence_no
   - session_id
   - speaker_ref
   - benchmark_role
   - memory_failure_mode
   - memory_trap
   - state_field_hints
   - probe_query_hints
4. 用中文生成：
   - turn_purpose
   - semantic_payload
   - planned_message_text
   - expected_openclaw_memory_risk
   - task_wiki_expected_handling
5. turn 文本必须像企业协作消息，不要像标注语言。

scaffold:
{scaffold}
""".strip()
    return system_prompt, user_prompt


def build_character_prompts(layout: dict[str, Any], world: dict[str, Any], scaffold: dict[str, Any]) -> PromptPair:
    system_prompt = (
        "你是 Task Wiki V3 的 character 生成器。"
        "只返回一个 JSON object，不要输出 Markdown。"
        "角色必须服务于企业任务记忆 fail case，而不是写成小说人物。"
    )
    user_prompt = f"""
请基于下面的 scaffold 生成 characters JSON。

目标任务：{world["task_id"]}
共享角色槽位：
{layout["shared_actor_slots"]}

要求：
1. 必须保留 person_id、actor_slot_id、simulated_open_id、department、role、task_ids、default_channels。
2. 用中文生成 name 和 profile。
3. profile 要解释这个角色为什么会在多个 source 中提供不同粒度信息。
4. 不要删除任何角色。

scaffold:
{scaffold}
""".strip()
    return system_prompt, user_prompt
