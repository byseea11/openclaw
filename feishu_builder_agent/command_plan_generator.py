from __future__ import annotations

from typing import Any

from .llm_client import JsonLLMClient
from .prompt_templates import build_command_plan_prompts
from .schemas import (
    ValidationError,
    validate_case_seed,
    validate_characters,
    validate_command_plan,
    validate_conversation_plan,
    validate_target_state,
)


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["person_id"]: item for item in characters["characters"]}


def _prefixed_message(character: dict[str, Any], text: str) -> str:
    return f"【{character['department']}/{character['name']}】{text}".strip()


def _fallback_message_text(turn: dict[str, Any], character: dict[str, Any]) -> str:
    payload = str(turn["semantic_payload"]).strip()
    if payload.endswith("。"):
        return _prefixed_message(character, payload)
    return _prefixed_message(character, f"{payload}。")


def _preview_command(action_type: str, *, output_ref: str | None = None, params: dict[str, Any]) -> str:
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
        return (
            f"lark-cli im +chat-messages-list --chat-id ${params['chat_ref']} "
            "--sort asc --page-size 50 --format json --as user"
        )
    if action_type == "fetch_thread_messages":
        return (
            f"lark-cli im +threads-messages-list --thread ${params['root_message_ref']} "
            "--sort asc --page-size 50 --format json --as user"
        )
    raise ValueError(f"Unsupported action_type: {action_type}")


def _target_refs(target_state: dict[str, Any], topic_key: str) -> list[str]:
    refs: list[str] = []
    for item in target_state["expected_current_state_targets"]:
        if item["topic_key"] == topic_key:
            refs.append(f"{item['topic_key']}:{item['slot']}")
    return refs or [topic_key]


def _fallback_command_plan(
    case_seed: dict[str, Any],
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
    target_state: dict[str, Any],
) -> list[dict[str, Any]]:
    seed = validate_case_seed(case_seed)
    plan = validate_conversation_plan(
        conversation_plan,
        allowed_actor_refs={item["person_id"] for item in validate_characters(characters)["characters"]},
    )
    roster = _character_map(validate_characters(characters))
    target = validate_target_state(target_state)
    session_map = {item["session_id"]: item for item in plan["sessions"]}
    rows: list[dict[str, Any]] = []
    unique_chat_refs: list[str] = []
    for session in plan["sessions"]:
        if session["chat_ref"] not in unique_chat_refs:
            unique_chat_refs.append(session["chat_ref"])
    step_index = 1
    chat_create_steps: dict[str, str] = {}
    for chat_ref in unique_chat_refs:
        step_id = f"step_{step_index:03d}"
        chat_create_steps[chat_ref] = step_id
        session = next(item for item in plan["sessions"] if item["chat_ref"] == chat_ref)
        params = {
            "chat_ref": chat_ref,
            "name": session["title"],
            "members": sorted(roster.keys()),
        }
        rows.append(
            {
                "case_id": seed["case_id"],
                "step_id": step_id,
                "sequence_no": step_index,
                "action_type": "create_chat",
                "session_id": session["session_id"],
                "source_type": session["source_type"],
                "source_ref": session["source_ref"],
                "channel_scope": f"chat:{chat_ref}",
                "chat_ref": chat_ref,
                "topic_key": session["topic_keys"][0] if session["topic_keys"] else "bootstrap",
                "turn_purpose": "创建执行此 case 所需的飞书群聊容器",
                "speaker_role": "system",
                "speaker_ref": "",
                "supports_event_types": [],
                "depends_on_step_ids": [],
                "gold_intent_refs": [],
                "expected_effect": f"创建群聊 {session['title']}",
                "state_transition": "建立协作载体",
                "semantic_payload": f"为 {seed['task_id']} 建立飞书会话容器",
                "root_turn_id": None,
                "root_message_ref": None,
                "output_ref": chat_ref,
                "params": params,
                "lark_cli_command": _preview_command("create_chat", params=params),
            }
        )
        step_index += 1
    turn_step_ids: dict[str, str] = {}
    for turn in plan["turns"]:
        session = session_map[turn["session_id"]]
        actor = roster[turn["speaker_ref"]]
        action_type = "reply_in_thread" if session["source_type"] == "thread" else "send_message"
        step_id = f"step_{step_index:03d}"
        output_ref = f"msg_{turn['turn_id']}"
        depends_on = [chat_create_steps[session["chat_ref"]]]
        root_message_ref = None
        if action_type == "reply_in_thread":
            root_turn_id = session.get("root_turn_id")
            if not root_turn_id:
                raise ValidationError(f"thread session {session['session_id']} missing root_turn_id")
            if root_turn_id not in turn_step_ids:
                raise ValidationError(f"thread session {session['session_id']} root_turn_id must appear earlier in conversation plan")
            root_message_ref = f"msg_{root_turn_id}"
            depends_on.append(turn_step_ids[root_turn_id])
        params = {
            "chat_ref": session["chat_ref"],
            "sender_ref": turn["speaker_ref"],
            "content_text": _fallback_message_text(turn, actor),
        }
        if root_message_ref:
            params["root_message_ref"] = root_message_ref
        rows.append(
            {
                "case_id": seed["case_id"],
                "step_id": step_id,
                "sequence_no": step_index,
                "action_type": action_type,
                "session_id": turn["session_id"],
                "source_type": session["source_type"],
                "source_ref": session["source_ref"],
                "channel_scope": f"chat:{session['chat_ref']}",
                "chat_ref": session["chat_ref"],
                "topic_key": turn["topic_key"],
                "turn_purpose": turn["turn_purpose"],
                "speaker_role": actor["role"],
                "speaker_ref": turn["speaker_ref"],
                "supports_event_types": turn["supports_event_types"],
                "depends_on_step_ids": depends_on,
                "gold_intent_refs": _target_refs(target, turn["topic_key"]),
                "expected_effect": f"围绕 {turn['topic_key']} 推进一条新的协作消息",
                "state_transition": turn["state_transition"],
                "semantic_payload": turn["semantic_payload"],
                "root_turn_id": session.get("root_turn_id"),
                "root_message_ref": root_message_ref,
                "output_ref": output_ref,
                "params": params,
                "lark_cli_command": _preview_command(action_type, output_ref=output_ref, params=params),
            }
        )
        turn_step_ids[turn["turn_id"]] = step_id
        step_index += 1
    used_chat_refs = {session_map[turn["session_id"]]["chat_ref"] for turn in plan["turns"]}
    for chat_ref in sorted(used_chat_refs):
        step_id = f"step_{step_index:03d}"
        session = next(item for item in plan["sessions"] if item["chat_ref"] == chat_ref)
        params = {"chat_ref": chat_ref}
        rows.append(
            {
                "case_id": seed["case_id"],
                "step_id": step_id,
                "sequence_no": step_index,
                "action_type": "fetch_chat_messages",
                "session_id": session["session_id"],
                "source_type": "chat",
                "source_ref": session["source_ref"],
                "channel_scope": f"chat:{chat_ref}",
                "chat_ref": chat_ref,
                "topic_key": session["topic_keys"][0] if session["topic_keys"] else "fetch",
                "turn_purpose": "回收主群消息，供后续 gold 和 replay 使用",
                "speaker_role": "system",
                "speaker_ref": "",
                "supports_event_types": [],
                "depends_on_step_ids": [chat_create_steps[chat_ref]],
                "gold_intent_refs": [],
                "expected_effect": "拉取主群历史消息",
                "state_transition": "收集证据",
                "semantic_payload": "收集主群消息作为后续评测证据",
                "root_turn_id": None,
                "root_message_ref": None,
                "output_ref": None,
                "params": params,
                "lark_cli_command": _preview_command("fetch_chat_messages", params=params),
            }
        )
        step_index += 1
    for session in plan["sessions"]:
        if session["source_type"] != "thread":
            continue
        root_turn_id = session.get("root_turn_id")
        if not root_turn_id:
            continue
        step_id = f"step_{step_index:03d}"
        root_message_ref = f"msg_{root_turn_id}"
        params = {
            "chat_ref": session["chat_ref"],
            "root_message_ref": root_message_ref,
        }
        rows.append(
            {
                "case_id": seed["case_id"],
                "step_id": step_id,
                "sequence_no": step_index,
                "action_type": "fetch_thread_messages",
                "session_id": session["session_id"],
                "source_type": session["source_type"],
                "source_ref": session["source_ref"],
                "channel_scope": f"thread:{session['source_ref']}",
                "chat_ref": session["chat_ref"],
                "topic_key": session["topic_keys"][0] if session["topic_keys"] else "fetch",
                "turn_purpose": "回收 thread 消息，供后续 gold 和 replay 使用",
                "speaker_role": "system",
                "speaker_ref": "",
                "supports_event_types": [],
                "depends_on_step_ids": [chat_create_steps[session["chat_ref"]], turn_step_ids[root_turn_id]],
                "gold_intent_refs": [],
                "expected_effect": "拉取 thread 历史消息",
                "state_transition": "收集证据",
                "semantic_payload": "收集 thread 消息作为后续评测证据",
                "root_turn_id": root_turn_id,
                "root_message_ref": root_message_ref,
                "output_ref": None,
                "params": params,
                "lark_cli_command": _preview_command("fetch_thread_messages", params=params),
            }
        )
        step_index += 1
    return validate_command_plan(rows, allowed_actor_refs=set(roster.keys()))


def generate_command_plan_with_mode(
    case_seed: dict[str, Any],
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
    *,
    target_state: dict[str, Any],
    llm_client: JsonLLMClient | None = None,
) -> tuple[list[dict[str, Any]], str]:
    seed = validate_case_seed(case_seed)
    validated_characters = validate_characters(characters)
    validated_plan = validate_conversation_plan(
        conversation_plan,
        allowed_actor_refs={item["person_id"] for item in validated_characters["characters"]},
    )
    validated_target = validate_target_state(target_state)
    allowed_refs = {item["person_id"] for item in validated_characters["characters"]}
    if llm_client is None:
        return _fallback_command_plan(seed, validated_plan, validated_characters, validated_target), "fallback"
    system_prompt, user_prompt = build_command_plan_prompts(
        seed=seed,
        validated_plan=validated_plan,
        validated_characters=validated_characters,
        validated_target=validated_target,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        return validate_command_plan(list(rows or []), allowed_actor_refs=allowed_refs), "live"
    except (Exception, ValidationError):
        return _fallback_command_plan(seed, validated_plan, validated_characters, validated_target), "fallback"


def generate_command_plan(
    case_seed: dict[str, Any],
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
    *,
    target_state: dict[str, Any],
    llm_client: JsonLLMClient | None = None,
) -> list[dict[str, Any]]:
    rows, _mode = generate_command_plan_with_mode(
        case_seed,
        conversation_plan,
        characters,
        target_state=target_state,
        llm_client=llm_client,
    )
    return rows
