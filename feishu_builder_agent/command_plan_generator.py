from __future__ import annotations

from typing import Any

from .schemas import validate_characters, validate_command_plan_v3, validate_conversation_plan_v3


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["person_id"]: item for item in characters["characters"]}


def _prefixed_message(character: dict[str, Any], text: str) -> str:
    return f"【{character['department']}/{character['name']}】{text}".strip()


def _preview_command(action_type: str, *, params: dict[str, Any]) -> str:
    if action_type == "create_chat":
        return f'lark-cli im +chat-create --name "{params["name"]}" --as user'
    if action_type == "send_message":
        return f'lark-cli im +messages-send --chat-id ${params["chat_ref"]} --text "{params["content_text"]}" --as user'
    if action_type == "reply_in_thread":
        return (
            f'lark-cli im +messages-reply --message-id ${params["root_message_ref"]} '
            f'--text "{params["content_text"]}" --reply-in-thread --as user'
        )
    if action_type == "fetch_chat_messages":
        return f'lark-cli im +chat-messages-list --chat-id ${params["chat_ref"]} --sort asc --page-size 50 --format json --as user'
    if action_type == "fetch_thread_messages":
        return f'lark-cli im +threads-messages-list --thread ${params["root_message_ref"]} --sort asc --page-size 50 --format json --as user'
    raise ValueError(f"unsupported action_type: {action_type}")


def generate_command_plan(
    case_spec: dict[str, Any],
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
) -> list[dict[str, Any]]:
    del case_spec
    plan = validate_conversation_plan_v3(
        conversation_plan,
        allowed_actor_refs={item["person_id"] for item in validate_characters(characters)["characters"]},
    )
    roster = _character_map(validate_characters(characters))
    session_map = {session["session_id"]: session for session in plan["sessions"]}
    rows: list[dict[str, Any]] = []
    unique_chat_refs: list[str] = []
    for session in plan["sessions"]:
        if session["chat_ref"] not in unique_chat_refs:
            unique_chat_refs.append(session["chat_ref"])
    sequence_no = 1
    chat_create_steps: dict[str, str] = {}
    for chat_ref in unique_chat_refs:
        session = next(item for item in plan["sessions"] if item["chat_ref"] == chat_ref)
        step_id = f"step_{sequence_no:03d}"
        chat_create_steps[chat_ref] = step_id
        params = {"chat_ref": chat_ref, "name": session["title"], "members": sorted(roster.keys())}
        rows.append(
            {
                "case_id": plan["case_id"],
                "step_id": step_id,
                "sequence_no": sequence_no,
                "action_type": "create_chat",
                "session_id": session["session_id"],
                "source_type": session["source_type"],
                "source_ref": session["source_ref"],
                "chat_ref": chat_ref,
                "topic_key": "bootstrap",
                "turn_id": None,
                "turn_purpose": "创建执行本 case 所需的飞书会话容器。",
                "speaker_role": "",
                "speaker_ref": "",
                "depends_on_step_ids": [],
                "benchmark_role": "",
                "memory_failure_mode": "",
                "memory_trap": "",
                "expected_openclaw_memory_risk": "",
                "task_wiki_expected_handling": "",
                "state_field_hints": [],
                "semantic_payload": "",
                "planned_message_text": "",
                "output_ref": chat_ref,
                "params": params,
                "lark_cli_command": _preview_command("create_chat", params=params),
            }
        )
        sequence_no += 1
    turn_step_ids: dict[str, str] = {}
    for turn in plan["turns"]:
        session = session_map[turn["session_id"]]
        character = roster[turn["speaker_ref"]]
        action_type = "reply_in_thread" if session["source_type"] == "thread" else "send_message"
        params = {
            "chat_ref": session["chat_ref"],
            "sender_ref": turn["speaker_ref"],
            "content_text": _prefixed_message(character, turn["planned_message_text"]),
        }
        depends_on = [chat_create_steps[session["chat_ref"]]]
        if action_type == "reply_in_thread":
            root_turn_id = session.get("root_turn_id")
            if not root_turn_id or root_turn_id not in turn_step_ids:
                raise ValueError(f"thread session {session['session_id']} requires a prior root_turn_id")
            root_message_ref = f"msg_{root_turn_id}"
            params["root_message_ref"] = root_message_ref
            depends_on.append(turn_step_ids[root_turn_id])
        step_id = f"step_{sequence_no:03d}"
        rows.append(
            {
                "case_id": plan["case_id"],
                "step_id": step_id,
                "sequence_no": sequence_no,
                "action_type": action_type,
                "session_id": turn["session_id"],
                "source_type": session["source_type"],
                "source_ref": session["source_ref"],
                "chat_ref": session["chat_ref"],
                "topic_key": turn["topic_key"],
                "turn_id": turn["turn_id"],
                "turn_purpose": turn["turn_purpose"],
                "speaker_role": character["role"],
                "speaker_ref": turn["speaker_ref"],
                "depends_on_step_ids": depends_on,
                "benchmark_role": turn["benchmark_role"],
                "memory_failure_mode": turn["memory_failure_mode"],
                "memory_trap": turn["memory_trap"],
                "expected_openclaw_memory_risk": turn["expected_openclaw_memory_risk"],
                "task_wiki_expected_handling": turn["task_wiki_expected_handling"],
                "state_field_hints": turn["state_field_hints"],
                "semantic_payload": turn["semantic_payload"],
                "planned_message_text": turn["planned_message_text"],
                "output_ref": f"msg_{turn['turn_id']}",
                "params": params,
                "lark_cli_command": _preview_command(action_type, params=params),
            }
        )
        turn_step_ids[turn["turn_id"]] = step_id
        sequence_no += 1
    for session in plan["sessions"]:
        if session["source_type"] == "chat":
            params = {"chat_ref": session["chat_ref"]}
            rows.append(
                {
                    "case_id": plan["case_id"],
                    "step_id": f"step_{sequence_no:03d}",
                    "sequence_no": sequence_no,
                    "action_type": "fetch_chat_messages",
                    "session_id": session["session_id"],
                    "source_type": "chat",
                    "source_ref": session["source_ref"],
                    "chat_ref": session["chat_ref"],
                    "topic_key": "fetch",
                    "turn_id": None,
                    "turn_purpose": "回收聊天消息，形成 observed data。",
                    "speaker_role": "",
                    "speaker_ref": "",
                    "depends_on_step_ids": [chat_create_steps[session["chat_ref"]]],
                    "benchmark_role": "",
                    "memory_failure_mode": "",
                    "memory_trap": "",
                    "expected_openclaw_memory_risk": "",
                    "task_wiki_expected_handling": "",
                    "state_field_hints": [],
                    "semantic_payload": "",
                    "planned_message_text": "",
                    "output_ref": None,
                    "params": params,
                    "lark_cli_command": _preview_command("fetch_chat_messages", params=params),
                }
            )
            sequence_no += 1
    for session in plan["sessions"]:
        if session["source_type"] != "thread":
            continue
        root_turn_id = session.get("root_turn_id")
        if not root_turn_id:
            continue
        params = {"chat_ref": session["chat_ref"], "root_message_ref": f"msg_{root_turn_id}"}
        rows.append(
            {
                "case_id": plan["case_id"],
                "step_id": f"step_{sequence_no:03d}",
                "sequence_no": sequence_no,
                "action_type": "fetch_thread_messages",
                "session_id": session["session_id"],
                "source_type": "thread",
                "source_ref": session["source_ref"],
                "chat_ref": session["chat_ref"],
                "topic_key": "fetch",
                "turn_id": None,
                "turn_purpose": "回收线程消息，形成 observed data。",
                "speaker_role": "",
                "speaker_ref": "",
                "depends_on_step_ids": [chat_create_steps[session["chat_ref"]], turn_step_ids[root_turn_id]],
                "benchmark_role": "",
                "memory_failure_mode": "",
                "memory_trap": "",
                "expected_openclaw_memory_risk": "",
                "task_wiki_expected_handling": "",
                "state_field_hints": [],
                "semantic_payload": "",
                "planned_message_text": "",
                "output_ref": None,
                "params": params,
                "lark_cli_command": _preview_command("fetch_thread_messages", params=params),
            }
        )
        sequence_no += 1
    return validate_command_plan_v3(rows, allowed_actor_refs=set(roster.keys()))


def generate_command_plan_with_mode(
    case_spec: dict[str, Any],
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    del llm_client
    return generate_command_plan(case_spec, conversation_plan, characters), "derived"
