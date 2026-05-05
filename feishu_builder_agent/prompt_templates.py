from __future__ import annotations

import json
from typing import Any

from .builder_settings import load_builder_settings, resolve_difficulty_settings


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _department_pool_text() -> str:
    settings = load_builder_settings()
    return "、".join(settings["defaults"]["department_pool"])


def build_spec_prompts(
    *,
    scenario_profile: str,
    difficulty: str,
    seed: int,
    user_hint: str,
) -> tuple[str, str]:
    difficulty_settings = resolve_difficulty_settings(difficulty)
    complexity = difficulty_settings["complexity_profile"]
    department_pool = _department_pool_text()
    system_prompt = (
        "Generate one minimal Feishu builder case_spec as JSON. "
        "Return only a JSON object with keys: case_id, task_id, title, company_type, department_hints, "
        "scenario_profile, title_hint, main_goal_hint, main_goal, difficulty, seed. "
        "All natural-language strings and department names must be written in Simplified Chinese. "
        "title, company_type, and main_goal should usually be empty strings at this stage. "
        "department_hints must be a JSON array of department-name strings, never a single string. "
        "Do not output Markdown."
    )
    user_prompt = (
        "请生成一个最小 case_spec，用于后续扩写企业协作世界。\n"
        f"- scenario_profile: {scenario_profile}\n"
        f"- difficulty: {difficulty}\n"
        f"- seed: {seed}\n"
        f"- user_hint: {user_hint or '无'}\n"
        f"- allowed_departments: {department_pool}\n"
        f"- target_department_count: {difficulty_settings['department_count']}\n"
        f"- target_topic_count: {difficulty_settings['topic_count']}\n"
        f"- target_session_count: {complexity['session_count_target']}\n"
        f"- target_message_count: {complexity['message_count_target']}\n\n"
        "要求：\n"
        "1. 必须保留 difficulty 和 seed，不要改写。\n"
        "2. 重点生成 department_hints、title_hint、main_goal_hint。\n"
        "3. department_hints 必须是 JSON 数组，例如 [\"产品\", \"研发\", \"安全\"]，不能返回一个中文句子。\n"
        "4. department_hints 只能从 allowed_departments 中选择，必须使用中文部门名。\n"
        "5. title、company_type、main_goal 保持为空字符串。\n"
        "6. case_id 和 task_id 如果拿不准可以留空，系统会统一生成。"
    )
    return system_prompt, user_prompt


def build_case_world_prompts(
    *,
    seed: dict[str, Any],
    fallback_world: dict[str, Any],
) -> tuple[str, str]:
    difficulty_settings = resolve_difficulty_settings(seed["difficulty"])
    complexity = difficulty_settings["complexity_profile"]
    message_count_target = int(complexity["message_count_target"])
    thread_reply_depth_target = int(complexity["thread_reply_depth_target"])
    supersession_target = int(complexity["supersession_target"])
    department_pool = _department_pool_text()
    system_prompt = (
        "Generate one enterprise collaboration case world as JSON. "
        "Return only a JSON object with keys: title, company_type, departments, main_goal, organization_background, "
        "external_pressure, stakeholders, conflict_axes, hidden_constraints, reversal_points, selected_topics. "
        "All natural-language strings must be written in Simplified Chinese. "
        "departments must be a JSON array of unique Simplified Chinese department names. "
        "selected_topics must be a JSON array of topic objects. "
        "Each selected_topics item must contain topic_key, topic_title, desired_event_types, state_transitions, and turn_templates. "
        "desired_event_types must be a JSON array of event type strings. "
        "state_transitions must be a JSON array of Simplified Chinese strings. "
        "Each turn_templates item must contain session_id, speaker_department, turn_purpose, supports_event_types, state_transition, and semantic_payload_template. "
        "Do not output Markdown."
    )
    user_prompt = (
        "请基于最小 case_spec 扩写完整 case_world。\n"
        f"- difficulty: {seed['difficulty']}\n"
        f"- seed: {seed['seed']}\n"
        f"- allowed_departments: {department_pool}\n"
        f"- target_department_count: {difficulty_settings['department_count']}\n"
        f"- target_topic_count: {difficulty_settings['topic_count']}\n"
        f"- target_session_count: {complexity['session_count_target']}\n"
        f"- target_message_count: {complexity['message_count_target']}\n"
        f"- thread_reply_depth_target: {complexity['thread_reply_depth_target']}\n"
        f"- state_transition_target: {complexity['state_transition_target']}\n\n"
        f"Case seed:\n{_dump_json(seed)}\n\n"
        f"Fallback world skeleton:\n{_dump_json(fallback_world)}\n\n"
        "要求：\n"
        "1. title、company_type、departments、main_goal、selected_topics 都需要给出完整结果。\n"
        "2. departments 必须输出目标数量的唯一中文部门，并优先覆盖 department_hints。\n"
        "3. departments 只能从 allowed_departments 中选择，不允许输出 SRE、PMO 等英文缩写。\n"
        "4. selected_topics 必须输出至少目标数量的 topic，并且每个 topic 都要带 desired_event_types、state_transitions 和 turn_templates。\n"
        f"5. selected_topics 中所有 turn_templates 的总数建议 >= {message_count_target}；如果 difficulty=hard，总数不得少于 {message_count_target}。\n"
        f"6. 至少一个 thread-oriented topic 或用于 thread 的 topic 必须包含 >= {thread_reply_depth_target} 个 turn_templates。\n"
        f"7. 至少两个 topic 要包含会产生 supersession 的 state_transition 或 semantic_payload_template，显式包含“更新为”或“改为”，以支持至少 {supersession_target} 个 supersession。\n"
        "8. 必须体现外部压力、隐藏约束、角色冲突和后续改口的反转点。\n"
        "9. 如果拿不准，就沿用 fallback world skeleton 的结构和数量约束。"
    )
    return system_prompt, user_prompt


def build_character_prompts(
    *,
    world: dict[str, Any],
) -> tuple[str, str]:
    difficulty_settings = resolve_difficulty_settings(world["difficulty"])
    department_pool = _department_pool_text()
    system_prompt = (
        "Generate a concise role roster for one enterprise software delivery case. "
        "Return only JSON with keys: case_id, characters. "
        "Each object must contain person_id, simulated_open_id, name, department, role, responsibility, communication_style, conflict_bias, "
        "stance, risk_preference, information_access_level, default_channels. "
        "All natural-language strings must be written in Simplified Chinese. "
        "Only person_id and simulated_open_id may remain snake_case."
    )
    user_prompt = (
        "请基于 case_world 生成角色画像。\n"
        f"- difficulty: {world['difficulty']}\n"
        f"- allowed_departments: {department_pool}\n"
        f"- selected_departments: {'、'.join(world['departments'])}\n"
        f"- character_count_min: {difficulty_settings['character_count_min']}\n"
        f"- character_count_max: {difficulty_settings['character_count_max']}\n\n"
        f"Case world:\n{_dump_json(world)}\n\n"
        "要求：\n"
        "1. 优先覆盖 case_world.departments 中已经选中的部门。\n"
        "2. 所有自然语言字段必须使用简体中文，字段尽量简短。\n"
        "3. person_id 必须是稳定的 snake_case。\n"
        "4. simulated_open_id 必须形如 ou_sim_security_01。\n"
        "5. 不要生成英文部门名。"
    )
    return system_prompt, user_prompt


def build_conversation_plan_prompts(
    *,
    world: dict[str, Any],
    validated_characters: dict[str, Any],
    current_metrics: dict[str, int] | None = None,
    remaining_deficit: dict[str, int] | None = None,
    must_fix_now: list[str] | None = None,
) -> tuple[str, str]:
    difficulty_settings = resolve_difficulty_settings(world["difficulty"])
    complexity = difficulty_settings["complexity_profile"]
    required_turn_count = int(complexity["message_count_target"])
    required_session_count = int(complexity["session_count_target"])
    required_topic_count = int(difficulty_settings["topic_count"])
    required_thread_depth = int(complexity["thread_reply_depth_target"])
    required_state_transitions = int(complexity["state_transition_target"])
    required_supersessions = int(complexity["supersession_target"])
    required_cross_source_revisions = int(complexity["cross_source_revision_target"])
    system_prompt = (
        "Generate one enterprise IM conversation plan as JSON. "
        "Return only a JSON object with keys: case_id, task_id, topic_registry, sessions, turns. "
        "Use source_type values from chat, thread. "
        "All natural-language strings must be written in Simplified Chinese. "
        "The output must satisfy all numeric complexity requirements exactly or above the minimum. "
        "Do not rely on implicit complexity. Every required state change must be visible in turns. "
        "Do not output Markdown."
    )
    retry_section = ""
    if current_metrics is not None or remaining_deficit or must_fix_now:
        retry_section = (
            "\n当前上一版 live plan 的统计如下：\n"
            f"- current_metrics: {_dump_json(current_metrics or {})}\n"
            f"- remaining_deficit: {_dump_json(remaining_deficit or {})}\n"
            f"- must_fix_now: {_dump_json(must_fix_now or [])}\n\n"
            "这是一轮 retry，不要重复输出同样规模的计划。"
            "你必须优先补齐 remaining_deficit 中非 0 的指标，尤其是 turns、thread 深度、supersession 和 cross-source revision。"
            "不允许用摘要式描述掩盖 deficit，必须通过合法的 session/topic/turn 结构把缺口补满。\n"
        )
    user_prompt = (
        "请基于已有 world 和角色配置生成一个多轮、多 source 的飞书协作计划。\n"
        f"- difficulty: {world['difficulty']}\n"
        f"- required_session_count_min: {required_session_count}\n"
        f"- required_topic_count_min: {required_topic_count}\n"
        f"- required_turn_count_min: {required_turn_count}\n"
        f"- required_thread_reply_depth_min: {required_thread_depth}\n"
        f"- required_state_transition_count_min: {required_state_transitions}\n"
        f"- required_supersession_count_min: {required_supersessions}\n"
        f"- required_cross_source_revision_count_min: {required_cross_source_revisions}\n"
        f"{retry_section}\n"
        f"Case world:\n{_dump_json(world)}\n\n"
        f"Characters:\n{_dump_json(validated_characters)}\n\n"
        "要求：\n"
        f"1. sessions 数量必须 >= {required_session_count}。\n"
        f"2. topic_registry 数量必须 >= {required_topic_count}。\n"
        f"3. turns 数量必须 >= {required_turn_count}。如果少于 {required_turn_count} 条，本次输出无效。\n"
        f"4. 至少一个 source_type='thread' 的 session 必须包含 >= {required_thread_depth} 条 turns，不要把 thread 讨论分散到多个 thread session 中。\n"
        f"5. 至少生成 {required_supersessions} 个 supersession turns。每个 supersession turn 的 semantic_payload 和 state_transition 必须显式包含“更新为”或“改为”。\n"
        f"6. 至少生成 {required_cross_source_revisions} 个跨 source 口径修正。跨 source 修正必须体现为：一个 session 中的信息改变另一个 session 中的当前口径。\n"
        f"7. 至少生成 {required_state_transitions} 个非空 state_transition。\n"
        "8. turns 必须引用合法的 speaker_ref、topic_key、session_id。\n"
        "9. thread turn 必须有合法 root_turn_id；thread 的 root turn 必须早于 reply turn。\n"
        "10. 不要只生成摘要式计划，每个 turn 都必须是可执行的 IM 发言意图。\n\n"
        "推荐结构：\n"
        "- 主群先提出初始目标窗口。\n"
        f"- 上线窗口 thread 至少连续讨论 {required_thread_depth} 轮，暴露 blocker，并把原窗口改为新窗口。\n"
        "- 主群回写 thread 结论，形成第一次 supersession。\n"
        "- 客户同步群推动外部口径收紧，形成跨 source revision。\n"
        "- 风险或管理同步再触发第二次 supersession。\n\n"
        "supersession 示例写法：\n"
        "- semantic_payload: 原来的五月上旬窗口更新为五月中旬，当前仍不能作为客户承诺。\n"
        "- semantic_payload: 客户口径从明确日期改为条件式窗口，只能说评审通过后同步。\n"
        "- state_transition: 发布时间口径从旧窗口更新为新窗口。\n"
    )
    return system_prompt, user_prompt


def build_command_plan_prompts(
    *,
    seed: dict[str, Any],
    validated_plan: dict[str, Any],
    validated_characters: dict[str, Any],
    validated_target: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = (
        "Generate an executable Feishu command plan as JSON. "
        "Return only a JSON object with a key named rows. "
        "Each row must represent one logical lark-cli action and must contain: "
        "step_id, sequence_no, action_type, session_id, source_type, source_ref, channel_scope, chat_ref, "
        "topic_key, turn_purpose, speaker_role, speaker_ref, supports_event_types, depends_on_step_ids, "
        "gold_intent_refs, expected_effect, state_transition, semantic_payload, root_turn_id, root_message_ref, "
        "output_ref, params, lark_cli_command. "
        "Allowed action_type values are create_chat, send_message, reply_in_thread, fetch_chat_messages, fetch_thread_messages. "
        "Do not invent new sessions or turns."
    )
    user_prompt = (
        f"Case seed:\n{_dump_json(seed)}\n\n"
        f"Conversation plan:\n{_dump_json(validated_plan)}\n\n"
        f"Characters:\n{_dump_json(validated_characters)}\n\n"
        f"Target state:\n{_dump_json(validated_target)}\n\n"
        "请生成完整的 command_plan。重点要求：\n"
        "1. 主群和 thread 的依赖关系要正确。\n"
        "2. message/reply 动作里的 content_text 必须是自然中文，并保留角色前缀。\n"
        "3. fetch 动作用于后续 collect/gold，不要省略。\n"
        "4. lark_cli_command 使用符号化引用即可，例如 $main_chat、$msg_turn_001。"
    )
    return system_prompt, user_prompt


def build_gold_event_prompts(*, payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You generate gold expected session_event records for a Feishu Task Wiki benchmark. "
        "Return one JSON object with key 'events'. Each event must match the Layer 2 session_event shape. "
        "Allowed event_type values are conclusion_event, rationale_event, objection_event, constraint_event, "
        "commitment_event, status_event, time_event, scope_event. "
        "Every event must contain event_id, task_ref, source_session_id, ingest_version, event_type, claim, "
        "core_entry_id, evidence_quote, context_quotes, participants, event_time, source, confidence, verification, gold_meta. "
        "Also include the required typed fields for each event_type. "
        "Use Simplified Chinese for natural-language fields. Do not invent facts beyond the provided collected_messages."
    )
    user_prompt = (
        "请把下面的 benchmark payload 转成 Layer 2 对齐的 gold expected_events。"
        "每条 event 必须能够回到 collected_messages 中对应的 turn/message 证据。"
        f"\n\nPayload:\n{_dump_json(payload)}"
    )
    return system_prompt, user_prompt


def build_story_prompts(*, world: dict[str, Any], validated_characters: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "Generate one concise enterprise software delivery story as JSON. "
        "Return only a JSON object with keys: case_id, task_id, title, background, "
        "business_pressure, project_goal, initial_assumption, main_conflicts, in_scope, out_of_scope. "
        "Keep it grounded in enterprise software collaboration. Be brief. Do not output Markdown. "
        "All natural-language strings must be written in Simplified Chinese."
    )
    user_prompt = (
        f"Case world:\n{_dump_json(world)}\n\n"
        f"Characters:\n{_dump_json(validated_characters)}\n\n"
        "请基于已有企业世界和角色配置生成一段真实、简洁、只发生在 IM 场景中的企业协作故事。"
        "所有自然语言字段都必须使用简体中文。"
        "main_conflicts, in_scope, and out_of_scope must be arrays of strings."
    )
    return system_prompt, user_prompt


def build_timeline_prompts(
    *,
    world: dict[str, Any],
    validated_story: dict[str, Any],
    validated_characters: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = (
        "Generate a concise enterprise conflict timeline as JSON. "
        "Return only JSON with keys: case_id, timeline. timeline must contain 6 to 12 events. "
        "Each event must have timeline_id, time_order, event_type, description, actor_refs, affected_topic, state_effect, should_surface_in_message. "
        "All natural-language strings must be written in Simplified Chinese."
    )
    user_prompt = (
        f"Case world:\n{_dump_json(world)}\n\n"
        f"Story:\n{_dump_json(validated_story)}\n\n"
        f"Characters:\n{_dump_json(validated_characters)}\n\n"
        "请生成一条真实但简洁的时间线，至少包含一个早期目标、一个 blocker、一个风险或约束，以及后续一次对外口径修正。"
        "所有自然语言字段必须使用简体中文。"
        "actor_refs must only reference existing person_id values."
    )
    return system_prompt, user_prompt


def build_utterance_plan_prompts(
    *,
    validated_plan: dict[str, Any],
    validated_characters: dict[str, Any],
    validated_target_state: dict[str, Any] | None,
) -> tuple[str, str]:
    system_prompt = (
        "Transform an enterprise conversation plan into an utterance plan as JSON. "
        "Return only a JSON object with one key named rows. "
        "Each row must contain turn_id, sequence_no, session_id, source_type, source_ref, chat_ref, speaker_ref, "
        "topic_key, turn_purpose, supports_event_types, references_previous_turns, semantic_payload, root_turn_id. "
        "Do not change the number of turns."
    )
    user_prompt = (
        f"Conversation plan:\n{_dump_json(validated_plan)}\n\n"
        f"Characters:\n{_dump_json(validated_characters)}\n\n"
        f"Target state:\n{_dump_json(validated_target_state)}\n\n"
        "请把 turns 变成可以直接用于消息 realization 的 utterance rows。"
        "不要新增或删除 turn，只允许补全 source 和 root_turn_id 等执行所需字段。"
    )
    return system_prompt, user_prompt


def build_message_realizer_prompts(*, character: dict[str, Any], row: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "Rewrite one enterprise IM turn as a single natural Chinese message. "
        "Return only a JSON object with one key named content_text. "
        "Keep it concise, realistic, and suitable for a Feishu group or thread. "
        "Do not remove the factual meaning."
    )
    user_prompt = (
        f"角色信息：{_dump_json(character)}\n"
        f"Turn plan：{_dump_json(row)}\n"
        "请输出一条简洁、真实、适合飞书群聊的中文消息，保留角色前缀。"
    )
    return system_prompt, user_prompt
