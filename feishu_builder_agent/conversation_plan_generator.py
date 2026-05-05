from __future__ import annotations

from collections import defaultdict
from typing import Any

from .builder_settings import resolve_difficulty_settings
from .llm_client import JsonLLMClient
from .logging_utils import builder_log
from .prompt_templates import build_conversation_plan_prompts
from .schemas import (
    ValidationError,
    validate_case_world,
    validate_characters,
    validate_conversation_plan,
)


def _first_actor(roster: list[dict[str, Any]], department: str) -> str:
    for character in roster:
        if character["department"] == department:
            return character["person_id"]
    return roster[0]["person_id"]


def _render_template(template: str, context: dict[str, Any]) -> str:
    return str(template).format(**context)


def _topic_context(case_world: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    departments = list(case_world["departments"])
    return {
        "task_id": case_world["task_id"],
        "title": case_world["title"],
        "main_goal": case_world["main_goal"],
        "target_window": "五月上旬",
        "next_window": "5 月 10 日",
        "focus_department": departments[0] if departments else "产品",
        "secondary_department": departments[1] if len(departments) > 1 else (departments[0] if departments else "研发"),
        "topic_title": topic["topic_title"],
    }


def _build_turns(
    *,
    case_world: dict[str, Any],
    roster: list[dict[str, Any]],
    selected_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    per_topic_turns: list[list[dict[str, Any]]] = []
    topic_turn_ids: dict[str, list[str]] = {}
    for topic in selected_topics:
        turns_for_topic: list[dict[str, Any]] = []
        context = _topic_context(case_world, topic)
        for index, template in enumerate(topic.get("turn_templates", []), start=1):
            turn_id = f"turn_{topic['topic_key']}_{index:02d}"
            topic_turn_ids.setdefault(topic["topic_key"], []).append(turn_id)
            turns_for_topic.append(
                {
                    "turn_id": turn_id,
                    "session_id": template["session_id"],
                    "speaker_ref": _first_actor(roster, template["speaker_department"]),
                    "topic_key": topic["topic_key"],
                    "turn_purpose": template["turn_purpose"],
                    "supports_event_types": template["supports_event_types"],
                    "references_previous_turns": topic_turn_ids[topic["topic_key"]][:-1][-1:] if len(topic_turn_ids[topic["topic_key"]]) > 1 else [],
                    "state_transition": template["state_transition"],
                    "semantic_payload": _render_template(template["semantic_payload_template"], context),
                }
            )
        per_topic_turns.append(turns_for_topic)
    merged: list[dict[str, Any]] = []
    max_turn_count = max((len(item) for item in per_topic_turns), default=0)
    for round_index in range(max_turn_count):
        for topic_turns in per_topic_turns:
            if round_index < len(topic_turns):
                merged.append(topic_turns[round_index])
    for index, turn in enumerate(merged, start=1):
        turn["sequence_no"] = index
    return merged


def _build_sessions(
    *,
    selected_topics: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    first_turn_by_topic: dict[str, str] = {}
    first_main_chat_turn_id = ""
    for turn in turns:
        first_turn_by_topic.setdefault(turn["topic_key"], turn["turn_id"])
        if turn["session_id"] == "session_main_chat" and not first_main_chat_turn_id:
            first_main_chat_turn_id = turn["turn_id"]
    session_topic_keys: dict[str, list[str]] = {}
    session_counts: dict[str, int] = {}
    for turn in turns:
        session_topic_keys.setdefault(turn["session_id"], [])
        if turn["topic_key"] not in session_topic_keys[turn["session_id"]]:
            session_topic_keys[turn["session_id"]].append(turn["topic_key"])
        session_counts[turn["session_id"]] = session_counts.get(turn["session_id"], 0) + 1
    inferred_layouts: list[dict[str, Any]] = []
    for session_id in session_topic_keys:
        if session_id == "session_main_chat":
            inferred_layouts.append(
                {
                    "session_id": session_id,
                    "source_type": "chat",
                    "source_ref": "main_chat",
                    "chat_ref": "main_chat",
                    "title": "主群协调",
                    "root_topic_key": "",
                }
            )
        elif session_id.endswith("_chat"):
            inferred_layouts.append(
                {
                    "session_id": session_id,
                    "source_type": "chat",
                    "source_ref": session_id.removeprefix("session_"),
                    "chat_ref": session_id.removeprefix("session_"),
                    "title": "补充聊天会话" if session_id != "session_customer_sync_chat" else "客户同步群",
                    "root_topic_key": "",
                }
            )
        else:
            inferred_layouts.append(
                {
                    "session_id": session_id,
                    "source_type": "thread",
                    "source_ref": session_id.removeprefix("session_"),
                    "chat_ref": "main_chat",
                    "title": "线程讨论",
                    "root_topic_key": "__main_chat_root__",
                }
            )
    normalized_sessions: list[dict[str, Any]] = []
    for layout in inferred_layouts:
        root_topic_key = str(layout.get("root_topic_key") or "").strip()
        normalized_sessions.append(
            {
                "session_id": layout["session_id"],
                "source_type": layout["source_type"],
                "source_ref": layout["source_ref"],
                "chat_ref": layout["chat_ref"],
                "title": layout["title"],
                "topic_keys": session_topic_keys.get(
                    layout["session_id"],
                    [item["topic_key"] for item in selected_topics],
                ),
                "planned_turn_count": session_counts.get(layout["session_id"], 0),
                "root_turn_id": (
                    first_main_chat_turn_id
                    if root_topic_key == "__main_chat_root__"
                    else (first_turn_by_topic.get(root_topic_key) if root_topic_key else None)
                ),
            }
        )
    return normalized_sessions


def _fallback_conversation_plan(
    case_world: dict[str, Any],
    characters: dict[str, Any],
) -> dict[str, Any]:
    world = validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    roster = validated_characters["characters"]
    selected_topics = list(world["selected_topics"])
    turns = _build_turns(case_world=world, roster=roster, selected_topics=selected_topics)
    sessions = _build_sessions(selected_topics=selected_topics, turns=turns)
    return {
        "case_id": world["case_id"],
        "task_id": world["task_id"],
        "topic_registry": [
            {
                "topic_key": item["topic_key"],
                "topic_title": item["topic_title"],
                "desired_event_types": item["desired_event_types"],
                "state_transitions": item["state_transitions"],
            }
            for item in selected_topics
        ],
        "sessions": sessions,
        "turns": turns,
    }


def _plan_session_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["session_id"]: item for item in plan["sessions"]}


def _next_turn_sequence_no(turns: list[dict[str, Any]]) -> int:
    return max((int(turn["sequence_no"]) for turn in turns), default=0) + 1


def _next_turn_id(turns: list[dict[str, Any]], topic_key: str) -> str:
    prefix = f"turn_{topic_key}_repair_"
    maximum = 0
    for turn in turns:
        turn_id = str(turn["turn_id"])
        if not turn_id.startswith(prefix):
            continue
        try:
            maximum = max(maximum, int(turn_id.removeprefix(prefix)))
        except ValueError:
            continue
    return f"{prefix}{maximum + 1:02d}"


def _latest_turn_for_topic(turns: list[dict[str, Any]], topic_key: str) -> dict[str, Any] | None:
    for turn in reversed(turns):
        if turn["topic_key"] == topic_key:
            return turn
    return None


def _choose_actor_for_department_or_topic(
    roster: list[dict[str, Any]],
    *,
    department: str | None = None,
    topic_key: str | None = None,
) -> str:
    if department:
        for character in roster:
            if character["department"] == department:
                return character["person_id"]
    preferences = {
        "release_window": ["产品", "研发", "运维"],
        "readiness_blockers": ["研发", "安全", "运维"],
        "external_messaging": ["销售", "客户成功", "产品"],
        "risk_controls": ["安全", "架构", "运维"],
        "executive_sync": ["产品", "项目管理办公室", "安全"],
    }
    for preferred in preferences.get(topic_key or "", []):
        for character in roster:
            if character["department"] == preferred:
                return character["person_id"]
    return roster[0]["person_id"]


def _append_turn(
    turns: list[dict[str, Any]],
    *,
    topic_key: str,
    session_id: str,
    speaker_ref: str,
    turn_purpose: str,
    supports_event_types: list[str],
    state_transition: str,
    semantic_payload: str,
    references_previous_turns: list[str] | None = None,
) -> dict[str, Any]:
    row = {
        "turn_id": _next_turn_id(turns, topic_key),
        "sequence_no": _next_turn_sequence_no(turns),
        "session_id": session_id,
        "speaker_ref": speaker_ref,
        "topic_key": topic_key,
        "turn_purpose": turn_purpose,
        "supports_event_types": list(supports_event_types),
        "references_previous_turns": list(references_previous_turns or []),
        "state_transition": state_transition,
        "semantic_payload": semantic_payload,
    }
    turns.append(row)
    return row


def _topic_source_refs(plan: dict[str, Any], topic_key: str) -> set[str]:
    sessions = _plan_session_map(plan)
    refs: set[str] = set()
    for turn in plan["turns"]:
        if turn["topic_key"] == topic_key:
            refs.add(str(sessions[turn["session_id"]]["source_ref"]))
    return refs


def _count_supersessions(turns: list[dict[str, Any]]) -> int:
    keywords = ("更新为", "改为", "修正为", "收紧为")
    total = 0
    for turn in turns:
        state_transition = str(turn.get("state_transition") or "")
        semantic_payload = str(turn.get("semantic_payload") or "")
        if any(keyword in state_transition for keyword in keywords) or any(keyword in semantic_payload for keyword in keywords):
            total += 1
    return total


def ensure_thread_depth(
    plan: dict[str, Any],
    world: dict[str, Any],
    roster: list[dict[str, Any]],
    *,
    difficulty_settings: dict[str, Any],
) -> None:
    target_depth = int(difficulty_settings["complexity_profile"]["thread_reply_depth_target"])
    sessions = plan["sessions"]
    turns = plan["turns"]
    session_turns: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for turn in turns:
        session_turns[turn["session_id"]].append(turn)
    thread_sessions = [item for item in sessions if item["source_type"] == "thread"]
    if thread_sessions:
        primary_thread = max(thread_sessions, key=lambda item: len(session_turns.get(item["session_id"], [])))
    else:
        main_chat_root = next((turn["turn_id"] for turn in turns if turn["session_id"] == "session_main_chat"), turns[0]["turn_id"])
        primary_thread = {
            "session_id": "session_repair_thread",
            "source_type": "thread",
            "source_ref": "repair_thread",
            "chat_ref": "main_chat",
            "title": "补充线程讨论",
            "topic_keys": ["release_window", "readiness_blockers"],
            "planned_turn_count": 0,
            "root_turn_id": main_chat_root,
        }
        sessions.append(primary_thread)
        session_turns[primary_thread["session_id"]] = []
    primary_topic = "release_window"
    thread_turns = session_turns[primary_thread["session_id"]]
    previous_turn_id = thread_turns[-1]["turn_id"] if thread_turns else (primary_thread.get("root_turn_id") or turns[0]["turn_id"])
    while len(thread_turns) < target_depth:
        actor = _choose_actor_for_department_or_topic(roster, topic_key=primary_topic)
        new_turn = _append_turn(
            turns,
            topic_key=primary_topic,
            session_id=primary_thread["session_id"],
            speaker_ref=actor,
            turn_purpose="在线程中继续深挖 blocker 和窗口修正条件",
            supports_event_types=["constraint_event", "status_event", "time_event"],
            references_previous_turns=[previous_turn_id] if previous_turn_id else [],
            state_transition="线程内持续收紧上线窗口判断。",
            semantic_payload=f"{world['task_id']} 当前还需要继续在线程内补齐 blocker 细节，迁移窗口和放行条件都不能提前说死。",
        )
        thread_turns.append(new_turn)
        previous_turn_id = new_turn["turn_id"]


def ensure_supersession_count(
    plan: dict[str, Any],
    roster: list[dict[str, Any]],
    *,
    difficulty_settings: dict[str, Any],
) -> None:
    target_count = int(difficulty_settings["complexity_profile"]["supersession_target"])
    turns = plan["turns"]
    sessions = _plan_session_map(plan)
    templates = [
        (
            "release_window",
            "session_main_chat",
            "显式修正当前发布时间口径",
            ["conclusion_event", "time_event"],
            "发布时间口径从旧窗口更新为新窗口。",
            "原来的内部目标窗口更新为条件式窗口，当前暂不作为客户承诺。",
        ),
        (
            "external_messaging",
            "session_customer_sync_chat",
            "显式修正客户同步口径",
            ["conclusion_event", "scope_event"],
            "客户同步口径从旧说法改为条件式窗口。",
            "客户同步口径从明确日期改为条件式窗口，只能在评审通过后同步。",
        ),
        (
            "executive_sync",
            "session_exec_sync_chat",
            "显式修正管理层同步口径",
            ["status_event", "scope_event"],
            "管理层同步口径从乐观日期收紧为条件式表述。",
            "管理层同步口径更新为条件式窗口，在风险关闭前不再带具体日期。",
        ),
    ]
    index = 0
    while _count_supersessions(turns) < target_count:
        topic_key, preferred_session_id, turn_purpose, event_types, state_transition, semantic_payload = templates[
            index % len(templates)
        ]
        session_id = preferred_session_id if preferred_session_id in sessions else "session_main_chat"
        latest_turn = _latest_turn_for_topic(turns, topic_key)
        actor = _choose_actor_for_department_or_topic(roster, topic_key=topic_key)
        _append_turn(
            turns,
            topic_key=topic_key,
            session_id=session_id,
            speaker_ref=actor,
            turn_purpose=turn_purpose,
            supports_event_types=event_types,
            references_previous_turns=[latest_turn["turn_id"]] if latest_turn else [],
            state_transition=state_transition,
            semantic_payload=semantic_payload,
        )
        index += 1


def ensure_cross_source_revisions(
    plan: dict[str, Any],
    roster: list[dict[str, Any]],
    *,
    difficulty_settings: dict[str, Any],
) -> None:
    target_count = int(difficulty_settings["complexity_profile"]["cross_source_revision_target"])
    turns = plan["turns"]
    sessions = _plan_session_map(plan)
    templates = [
        (
            "release_window",
            "session_main_chat",
            "根据 thread 结论更新主群口径",
            ["conclusion_event", "scope_event"],
            "根据线程里的 blocker 结论，主群口径更新为条件式窗口。",
            "根据线程里的 blocker 结论，主群口径更新为条件式窗口，当前不再同步乐观日期。",
        ),
        (
            "external_messaging",
            "session_main_chat",
            "根据客户同步压力收紧主群口径",
            ["conclusion_event", "scope_event"],
            "客户同步口径从主群旧说法改为保守表述。",
            "客户同步群里的压力已经反馈到主群，当前对外说法改为只同步条件式窗口。",
        ),
        (
            "release_window",
            "session_exec_sync_chat",
            "根据外部同步压力更新管理层口径",
            ["status_event", "scope_event"],
            "管理层同步口径从旧窗口收紧为条件式同步。",
            "管理层同步口径更新为先讲条件再讲时间，不再带客户可误解的确定日期。",
        ),
    ]
    def _current_count() -> int:
        return sum(1 for topic_key in {item[0] for item in templates} if len(_topic_source_refs(plan, topic_key)) >= 2)
    index = 0
    while _current_count() < target_count:
        topic_key, preferred_session_id, turn_purpose, event_types, state_transition, semantic_payload = templates[
            index % len(templates)
        ]
        session_id = preferred_session_id if preferred_session_id in sessions else "session_main_chat"
        latest_turn = _latest_turn_for_topic(turns, topic_key)
        actor = _choose_actor_for_department_or_topic(roster, topic_key=topic_key)
        _append_turn(
            turns,
            topic_key=topic_key,
            session_id=session_id,
            speaker_ref=actor,
            turn_purpose=turn_purpose,
            supports_event_types=event_types,
            references_previous_turns=[latest_turn["turn_id"]] if latest_turn else [],
            state_transition=state_transition,
            semantic_payload=semantic_payload,
        )
        index += 1


def ensure_min_turn_count(
    plan: dict[str, Any],
    world: dict[str, Any],
    roster: list[dict[str, Any]],
    *,
    difficulty_settings: dict[str, Any],
) -> None:
    target_count = int(difficulty_settings["complexity_profile"]["message_count_target"])
    turns = plan["turns"]
    sessions = _plan_session_map(plan)
    templates = [
        (
            "release_window",
            "session_main_chat",
            "补充窗口修正后的最新判断",
            ["status_event", "time_event"],
            "发布时间口径继续收紧为条件式窗口。",
            "发布时间口径继续收紧为条件式窗口，等 blocker 清零后再恢复具体日期。",
        ),
        (
            "readiness_blockers",
            "session_launch_window_thread",
            "补充 blocker 的依赖细节",
            ["constraint_event", "status_event"],
            "阻塞项描述继续更新为更明确的依赖集合。",
            "当前仍有关键前置项待确认，迁移窗口和放行材料都还需要继续补齐。",
        ),
        (
            "external_messaging",
            "session_customer_sync_chat",
            "补充客户沟通边界",
            ["scope_event", "rationale_event"],
            "客户同步口径继续改为保守表述。",
            "客户同步口径继续改为保守表述，只同步准备中和条件未闭环这两个事实。",
        ),
        (
            "risk_controls",
            "session_risk_review_thread",
            "补充风险收敛动作",
            ["constraint_event", "status_event"],
            "风险控制要求继续收紧为明确清单。",
            "风险材料和回滚条件还要继续收紧为明确清单，不能提前放松验收口径。",
        ),
        (
            "executive_sync",
            "session_exec_sync_chat",
            "补充管理层同步的后续动作",
            ["status_event", "scope_event"],
            "管理层同步继续更新为条件式节奏。",
            "管理层同步继续更新为条件式节奏，等 thread 结论稳定后再确认下一次上卷节点。",
        ),
    ]
    index = 0
    while len(turns) < target_count:
        topic_key, preferred_session_id, turn_purpose, event_types, state_transition, semantic_payload = templates[
            index % len(templates)
        ]
        session_id = preferred_session_id if preferred_session_id in sessions else "session_main_chat"
        latest_turn = _latest_turn_for_topic(turns, topic_key)
        actor = _choose_actor_for_department_or_topic(roster, topic_key=topic_key)
        _append_turn(
            turns,
            topic_key=topic_key,
            session_id=session_id,
            speaker_ref=actor,
            turn_purpose=turn_purpose,
            supports_event_types=event_types,
            references_previous_turns=[latest_turn["turn_id"]] if latest_turn else [],
            state_transition=state_transition,
            semantic_payload=semantic_payload,
        )
        index += 1


def repair_conversation_plan_complexity(
    plan: dict[str, Any],
    world: dict[str, Any],
    characters: dict[str, Any],
    difficulty_settings: dict[str, Any],
) -> dict[str, Any]:
    validated_world = validate_case_world(world)
    validated_characters = validate_characters(characters)
    repaired = {
        "case_id": plan["case_id"],
        "task_id": plan["task_id"],
        "topic_registry": [dict(item) for item in plan["topic_registry"]],
        "sessions": [dict(item) for item in plan["sessions"]],
        "turns": [dict(item) for item in plan["turns"]],
    }
    roster = list(validated_characters["characters"])
    ensure_thread_depth(repaired, validated_world, roster, difficulty_settings=difficulty_settings)
    ensure_supersession_count(repaired, roster, difficulty_settings=difficulty_settings)
    ensure_cross_source_revisions(repaired, roster, difficulty_settings=difficulty_settings)
    ensure_min_turn_count(repaired, validated_world, roster, difficulty_settings=difficulty_settings)
    session_counts: defaultdict[str, int] = defaultdict(int)
    session_topics: defaultdict[str, list[str]] = defaultdict(list)
    main_chat_root = next((turn["turn_id"] for turn in repaired["turns"] if turn["session_id"] == "session_main_chat"), None)
    for index, turn in enumerate(repaired["turns"], start=1):
        turn["sequence_no"] = index
        session_counts[turn["session_id"]] += 1
        if turn["topic_key"] not in session_topics[turn["session_id"]]:
            session_topics[turn["session_id"]].append(turn["topic_key"])
    for session in repaired["sessions"]:
        session["planned_turn_count"] = session_counts.get(session["session_id"], 0)
        session["topic_keys"] = session_topics.get(session["session_id"], session.get("topic_keys", []))
        if session["source_type"] == "thread" and not session.get("root_turn_id"):
            session["root_turn_id"] = main_chat_root
    return repaired


def generate_conversation_plan_with_mode(
    case_world: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[dict[str, Any], str]:
    world = validate_case_world(case_world)
    validated_characters = validate_characters(characters)
    roster_ids = {item["person_id"] for item in validated_characters["characters"]}
    fallback_plan = _fallback_conversation_plan(world, validated_characters)
    difficulty_settings = resolve_difficulty_settings(world["difficulty"])
    if llm_client is None:
        repaired = repair_conversation_plan_complexity(fallback_plan, world, validated_characters, difficulty_settings)
        return validate_conversation_plan(repaired, allowed_actor_refs=roster_ids), "fallback"
    system_prompt, user_prompt = build_conversation_plan_prompts(
        world=world,
        validated_characters=validated_characters,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        live_plan = validate_conversation_plan(payload, allowed_actor_refs=roster_ids)
        repaired = repair_conversation_plan_complexity(live_plan, world, validated_characters, difficulty_settings)
        return validate_conversation_plan(repaired, allowed_actor_refs=roster_ids), "live"
    except ValidationError as exc:
        builder_log("plan", f"模型输出未通过 conversation_plan 校验，回退 fallback。reason={exc} payload={payload!r}")
        repaired = repair_conversation_plan_complexity(fallback_plan, world, validated_characters, difficulty_settings)
        return validate_conversation_plan(repaired, allowed_actor_refs=roster_ids), "fallback"
    except Exception as exc:
        builder_log("plan", f"模型输出后处理失败，回退 fallback。reason={exc.__class__.__name__}: {exc}")
        repaired = repair_conversation_plan_complexity(fallback_plan, world, validated_characters, difficulty_settings)
        return validate_conversation_plan(repaired, allowed_actor_refs=roster_ids), "fallback"


def generate_conversation_plan(
    case_world: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> dict[str, Any]:
    plan, _mode = generate_conversation_plan_with_mode(
        case_world,
        characters,
        llm_client=llm_client,
    )
    return plan
