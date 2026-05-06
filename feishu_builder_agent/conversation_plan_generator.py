from __future__ import annotations

from typing import Any

from .schemas import (
    validate_case_world_v3,
    validate_characters,
    validate_conversation_plan_v3,
    validate_memory_failure_blueprint,
    validate_story_beats,
)


ROLE_SESSION_PREFERENCE = {
    "target_fact_turn": "session_main_chat",
    "evidence_anchor_turn": "session_main_chat",
    "stale_state_turn": "session_handoff_thread",
    "supersession_turn": "session_handoff_thread",
    "final_current_state_turn": "session_main_chat",
    "distractor_task_turn": "session_customer_sync_chat",
    "shared_actor_turn": "session_main_chat",
    "memory_pollution_turn": "session_exec_sync_chat",
    "ambiguous_claim_turn": "session_customer_sync_chat",
    "hearsay_turn": "session_risk_review_thread",
    "weak_commitment_turn": "session_main_chat",
    "ordinary_ack_turn": "session_risk_review_thread",
    "context_only_turn": "session_customer_sync_chat",
    "dependency_link_turn": "session_risk_review_thread",
    "dependency_update_turn": "session_main_chat",
    "current_state_disambiguation_turn": "session_main_chat",
    "probe_setup_turn": "session_customer_sync_chat",
}


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["person_id"]: item for item in characters["characters"]}


def _choose_speaker(trap: dict[str, Any], benchmark_role: str, roster: dict[str, dict[str, Any]]) -> str:
    for actor_slot_id in trap["common"]["shared_actors"]:
        if actor_slot_id in roster:
            return actor_slot_id
    for person_id, item in roster.items():
        department = item["department"]
        if benchmark_role in {"dependency_link_turn", "dependency_update_turn"} and department in {"安全", "运维", "研发"}:
            return person_id
        if benchmark_role in {"ambiguous_claim_turn", "hearsay_turn"} and department in {"销售", "财务", "产品"}:
            return person_id
        if benchmark_role in {"stale_state_turn", "supersession_turn", "final_current_state_turn"} and department in {"产品", "研发", "运维"}:
            return person_id
    return next(iter(roster))


def _pick_session_id(role: str, available_session_ids: list[str]) -> str:
    preferred = ROLE_SESSION_PREFERENCE.get(role, "session_main_chat")
    if preferred in available_session_ids:
        return preferred
    return available_session_ids[0]


def _planned_message_text(task_id: str, trap: dict[str, Any], benchmark_role: str) -> str:
    payload = trap["typed_payload"]
    if benchmark_role == "target_fact_turn":
        return f"{task_id} 当前先按五月上旬作为内部目标推进，但还没有对外锁死具体发布日期。"
    if benchmark_role == "evidence_anchor_turn":
        return f"我这里确认一个硬事实：{task_id} 现在还不能对外承诺确定日期，原因是关键依赖尚未全部锁定。"
    if benchmark_role == "stale_state_turn":
        return f"{task_id} 最早是由 {payload.get('required_state_track', {}).get('states', ['Bob'])[0]} 负责推进的，当时窗口也更乐观。"
    if benchmark_role == "supersession_turn":
        return f"更新一下，之前那个 owner 口径已经作废，当前接手人和窗口判断都需要按新安排重算。"
    if benchmark_role == "final_current_state_turn":
        final_owner = payload.get("required_state_track", {}).get("final_current_state", "xzy")
        return f"现在统一一下 current state：{task_id} 当前 owner 以 {final_owner} 为准，旧 owner 只算历史信息。"
    if benchmark_role == "distractor_task_turn":
        distractor = trap["common"]["distractor_tasks"][0]
        return f"{distractor} 那边的 blocker 还是财务审批和客户排期，不要和 {task_id} 混在一起。"
    if benchmark_role == "shared_actor_turn":
        return f"同一个同学今天同时在跟 {task_id} 和其他项目，但当前这里讨论的是 {task_id} 自己的 owner 和 blocker。"
    if benchmark_role == "memory_pollution_turn":
        distractor = trap["common"]["distractor_tasks"][-1]
        return f"{distractor} 也在改发布时间和负责人，这种相似措辞特别容易让个人记忆串台。"
    if benchmark_role == "ambiguous_claim_turn":
        return f"我感觉 {payload.get('target_claim', task_id + ' 可能受财务问题影响')}，但我还没有拿到明确结论。"
    if benchmark_role == "hearsay_turn":
        return f"有人说这个事情可能和财务审批有关，不过我手里没有直接证据。"
    if benchmark_role == "weak_commitment_turn":
        return "我这边可以先盯一下这个事情，但 owner 和 deadline 还没法现在就锁定。"
    if benchmark_role == "ordinary_ack_turn":
        return "收到，我先看看。"
    if benchmark_role == "context_only_turn":
        return "客户这两天一直在追上线时间，这会影响大家对外同步的措辞。"
    if benchmark_role == "dependency_link_turn":
        chain = " -> ".join(payload.get("dependency_chain", ["上游审批", "安全放行", "发布时间"]))
        return f"{task_id} 当前状态其实被一条上游依赖链牵着走：{chain}。"
    if benchmark_role == "dependency_update_turn":
        return f"上游条件一变，{task_id} 这边原来那个 ready 判断就不成立了，当前状态需要同步回退。"
    if benchmark_role == "current_state_disambiguation_turn":
        return f"明确一下 current state：现在只认最新一轮确认过的 owner、blocker 和依赖状态，不再沿用旧说法。"
    if benchmark_role == "probe_setup_turn":
        return f"客户后面很可能直接问 {task_id} 当前负责人、当前 blocker 和下一步动作，我们先把口径理清。"
    return f"{task_id} 这里需要补一条 {benchmark_role}，让后续记忆评测有可追踪证据。"


def _state_field_hints(trap: dict[str, Any]) -> list[str]:
    fields = list(trap["common"]["landing_requirements"]["required_state_fields"])
    payload = trap["typed_payload"]
    track = payload.get("required_state_track")
    if isinstance(track, dict):
        field = str(track.get("field") or "").strip()
        if field and field not in fields:
            fields.append(field)
    if payload.get("impacted_field") and payload["impacted_field"] not in fields:
        fields.append(payload["impacted_field"])
    return fields


def generate_conversation_plan(
    case_world: dict[str, Any],
    characters: dict[str, Any],
    memory_failure_blueprint: dict[str, Any],
    story_beats: dict[str, Any],
) -> dict[str, Any]:
    world = validate_case_world_v3(case_world)
    roster = validate_characters(characters)
    blueprint = validate_memory_failure_blueprint(memory_failure_blueprint)
    beats = validate_story_beats(story_beats)
    roster_map = _character_map(roster)
    sessions = [dict(item) for item in world["source_sessions"]]
    available_session_ids = [item["session_id"] for item in sessions]
    turns = []
    sequence_no = 1
    beats_by_trap: dict[str, list[dict[str, Any]]] = {}
    for beat in beats["beats"]:
        beats_by_trap.setdefault(beat["trap_id"], []).append(beat)
    for trap in blueprint["traps"]:
        for beat in beats_by_trap.get(trap["trap_id"], []):
            session_id = _pick_session_id(beat["benchmark_role"], available_session_ids)
            speaker_ref = _choose_speaker(trap, beat["benchmark_role"], roster_map)
            turns.append(
                {
                    "turn_id": f"turn_{sequence_no:03d}",
                    "sequence_no": sequence_no,
                    "session_id": session_id,
                    "speaker_ref": speaker_ref,
                    "topic_key": trap["failure_mode"],
                    "turn_purpose": beat["description"],
                    "references_previous_turns": [turns[-1]["turn_id"]] if turns else [],
                    "semantic_payload": _planned_message_text(world["task_id"], trap, beat["benchmark_role"]),
                    "planned_message_text": _planned_message_text(world["task_id"], trap, beat["benchmark_role"]),
                    "benchmark_role": beat["benchmark_role"],
                    "memory_failure_mode": trap["failure_mode"],
                    "memory_trap": trap["trap_id"],
                    "expected_openclaw_memory_risk": trap["expected_openclaw_failure"],
                    "task_wiki_expected_handling": trap["expected_task_wiki_success"],
                    "state_field_hints": _state_field_hints(trap),
                    "probe_query_hints": trap["common"]["probe_queries"],
                }
            )
            sequence_no += 1
    turns.sort(
        key=lambda row: (
            row["session_id"] != "session_main_chat",
            row["session_id"].endswith("_thread"),
            row["sequence_no"],
        )
    )
    for index, turn in enumerate(turns, start=1):
        turn["sequence_no"] = index
    first_main_turn_id = next((turn["turn_id"] for turn in turns if turn["session_id"] == "session_main_chat"), None)
    for session in sessions:
        if session["source_type"] == "thread":
            session["root_turn_id"] = first_main_turn_id
    return validate_conversation_plan_v3(
        {
            "case_id": world["case_id"],
            "task_id": world["task_id"],
            "sessions": sessions,
            "turns": turns,
        },
        allowed_actor_refs={item["person_id"] for item in roster["characters"]},
    )


def generate_conversation_plan_with_mode(
    case_world: dict[str, Any],
    characters: dict[str, Any],
    memory_failure_blueprint: dict[str, Any],
    story_beats: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> tuple[dict[str, Any], str]:
    del llm_client
    return generate_conversation_plan(case_world, characters, memory_failure_blueprint, story_beats), "fallback"
