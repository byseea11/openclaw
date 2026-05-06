from __future__ import annotations

import re
from typing import Any

from ..schemas import (
    validate_actor_registry,
    validate_characters,
    validate_command_plan,
    validate_conversation_plan_artifact,
    validate_task_actor_layout_artifact,
)


def _actor_map(
    *,
    characters: dict[str, Any] | None = None,
    actor_registry: dict[str, Any] | None = None,
    task_actor_layout: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if characters is not None:
        validated = validate_characters(characters)
        actors = {item["person_id"]: item for item in validated["characters"]}
        if actor_registry is not None:
            registry = validate_actor_registry(actor_registry)
            registry_by_person = {item["person_id"]: item for item in registry["actors"]}
            missing = sorted(set(actors) - set(registry_by_person))
            if missing:
                raise ValueError(f"actor_registry missing person_id(s): {missing}")
            for person_id, actor in actors.items():
                actor.update(registry_by_person[person_id])
        return actors
    if not task_actor_layout:
        return {}
    layout = validate_task_actor_layout_artifact(task_actor_layout)
    return {
        item["actor_id"]: {
            "person_id": item["actor_id"],
            "actor_slot_id": item["actor_id"],
            "name": item.get("display_name") or item["actor_id"],
            "department": item.get("department") or item.get("role") or "角色",
            "role": item.get("role") or "",
        }
        for item in layout["actors"]
    }


def _source_type(session: dict[str, Any]) -> str:
    session_type = str(session.get("session_type") or "").lower()
    if "thread" in session_type:
        return "thread"
    return "chat"


def _chat_ref(session: dict[str, Any]) -> str:
    return f"chat_{session['session_id']}"


def _source_ref(session: dict[str, Any]) -> str:
    source_type = _source_type(session)
    return f"{source_type}:{session['session_id']}"


def _speaker_label(actor: dict[str, Any] | None, actor_id: str) -> tuple[str, str, str]:
    if not actor:
        return actor_id, "", actor_id
    name = str(actor.get("name") or actor.get("display_name") or actor_id)
    department = str(actor.get("department") or actor.get("role") or "角色")
    role = str(actor.get("role") or "")
    return name, department, role


def _prefixed_message(actor: dict[str, Any] | None, actor_id: str, text: str) -> str:
    name, department, _ = _speaker_label(actor, actor_id)
    return f"【{department}/{name}】{text}".strip()


def _actor_aliases(
    *,
    actors: dict[str, dict[str, Any]],
    task_actor_layout: dict[str, Any] | None,
) -> dict[str, str]:
    if not task_actor_layout:
        return {}
    layout = validate_task_actor_layout_artifact(task_actor_layout)
    aliases: dict[str, str] = {}
    for actor in layout["actors"]:
        actor_id = str(actor["actor_id"])
        character = actors.get(actor_id)
        if not character:
            continue
        target_name = str(character.get("name") or "").strip()
        if not target_name:
            continue
        display_name = str(actor.get("display_name") or "").strip()
        if display_name and display_name != target_name:
            aliases[display_name] = target_name
    return aliases


def _rewrite_actor_mentions(text: str, aliases: dict[str, str]) -> str:
    rewritten = text
    for source_name, target_name in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<![\w]){re.escape(source_name)}(?![\w])")
        rewritten = pattern.sub(target_name, rewritten)
    return rewritten


def _preview_command(action_type: str, *, params: dict[str, Any]) -> str:
    if action_type == "create_chat":
        return f'lark-cli im +chat-create --name "{params["name"]}" --as user'
    if action_type == "send_message":
        return f'lark-cli im +messages-send --chat-id ${{{params["chat_ref"]}}} --text "{params["content_text"]}" --as user'
    if action_type == "reply_in_thread":
        return (
            f'lark-cli im +messages-reply --message-id ${{{params["root_message_ref"]}}} '
            f'--text "{params["content_text"]}" --reply-in-thread --as user'
        )
    if action_type == "fetch_chat_messages":
        return f'lark-cli im +chat-messages-list --chat-id ${{{params["chat_ref"]}}} --sort asc --page-size 50 --format json --as user'
    if action_type == "fetch_thread_messages":
        return f'lark-cli im +threads-messages-list --thread ${{{params["root_message_ref"]}}} --sort asc --page-size 50 --format json --as user'
    raise ValueError(f"unsupported action_type: {action_type}")


def _thread_root_text(session: dict[str, Any]) -> str:
    return f"【benchmark/root】{session['title']}：以下回复承载该 source session 的真实 benchmark 消息。"


def _base_row(
    *,
    case_id: str,
    family_id: str,
    step_id: str,
    sequence_no: int,
    action_type: str,
    session: dict[str, Any],
    topic_key: str,
    depends_on_step_ids: list[str],
    output_ref: str,
    params: dict[str, Any],
    turn: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actor_id = str((turn or {}).get("speaker_actor_id") or "")
    _, _, speaker_role = _speaker_label(actor, actor_id)
    text = str((turn or {}).get("planned_message_text") or "")
    return {
        "case_id": case_id,
        "family_id": family_id,
        "command_id": step_id,
        "step_id": step_id,
        "sequence_no": sequence_no,
        "action_type": action_type,
        "session_id": str(session["session_id"]),
        "source_type": _source_type(session),
        "source_ref": _source_ref(session),
        "chat_ref": _chat_ref(session),
        "topic_key": topic_key,
        "turn_id": str((turn or {}).get("turn_id") or ""),
        "beat_id": str((turn or {}).get("beat_id") or ""),
        "turn_purpose": str((turn or {}).get("planned_message_text") or session.get("session_purpose") or ""),
        "speaker_role": speaker_role,
        "speaker_ref": actor_id,
        "actor_id": actor_id,
        "depends_on_step_ids": depends_on_step_ids,
        "benchmark_role": str((turn or {}).get("benchmark_role") or ""),
        "memory_failure_mode": family_id,
        "memory_trap": str((turn or {}).get("memory_trap") or ""),
        "expected_openclaw_memory_risk": str((turn or {}).get("expected_openclaw_memory_risk") or ""),
        "task_wiki_expected_handling": str((turn or {}).get("task_wiki_expected_handling") or ""),
        "state_field_hints": list((turn or {}).get("state_field_hints") or []),
        "semantic_payload": text,
        "planned_message_text": text,
        "message_text": text,
        "output_ref": output_ref,
        "params": params,
        "lark_cli_command": _preview_command(action_type, params=params),
    }


def build_command_plan(
    *,
    conversation_plan: dict[str, Any],
    characters: dict[str, Any] | None = None,
    actor_registry: dict[str, Any] | None = None,
    task_actor_layout: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    plan = validate_conversation_plan_artifact(conversation_plan)
    actors = _actor_map(
        characters=characters,
        actor_registry=actor_registry,
        task_actor_layout=task_actor_layout,
    )
    aliases = _actor_aliases(actors=actors, task_actor_layout=task_actor_layout)
    session_map = {session["session_id"]: session for session in plan["sessions"]}
    rows: list[dict[str, Any]] = []
    sequence_no = 1

    chat_create_steps: dict[str, str] = {}
    unique_chat_refs: list[str] = []
    for session in plan["sessions"]:
        chat_ref = _chat_ref(session)
        if chat_ref not in unique_chat_refs:
            unique_chat_refs.append(chat_ref)

    for chat_ref in unique_chat_refs:
        session = next(item for item in plan["sessions"] if _chat_ref(item) == chat_ref)
        step_id = f"step_{sequence_no:03d}"
        chat_create_steps[chat_ref] = step_id
        params = {"chat_ref": chat_ref, "name": session["title"], "members": sorted(actors.keys())}
        rows.append(
            _base_row(
                case_id=plan["case_id"],
                family_id=plan["family_id"],
                step_id=step_id,
                sequence_no=sequence_no,
                action_type="create_chat",
                session=session,
                topic_key="bootstrap",
                depends_on_step_ids=[],
                output_ref=chat_ref,
                params=params,
            )
        )
        sequence_no += 1

    thread_root_steps: dict[str, str] = {}
    thread_root_refs: dict[str, str] = {}
    for session in plan["sessions"]:
        if _source_type(session) != "thread":
            continue
        chat_ref = _chat_ref(session)
        session_id = str(session["session_id"])
        step_id = f"step_{sequence_no:03d}"
        output_ref = f"thread_root_{session_id}"
        params = {
            "chat_ref": chat_ref,
            "sender_ref": "benchmark_root",
            "content_text": _thread_root_text(session),
        }
        rows.append(
            _base_row(
                case_id=plan["case_id"],
                family_id=plan["family_id"],
                step_id=step_id,
                sequence_no=sequence_no,
                action_type="send_message",
                session=session,
                topic_key="thread_root",
                depends_on_step_ids=[chat_create_steps[chat_ref]],
                output_ref=output_ref,
                params=params,
            )
        )
        thread_root_steps[session_id] = step_id
        thread_root_refs[session_id] = output_ref
        sequence_no += 1

    turn_step_ids: dict[str, str] = {}
    session_message_step_ids: dict[str, list[str]] = {}
    for turn in plan["turns"]:
        session = session_map[turn["session_id"]]
        chat_ref = _chat_ref(session)
        session_id = str(session["session_id"])
        is_thread = _source_type(session) == "thread"
        action_type = "reply_in_thread" if is_thread else "send_message"
        actor_id = str(turn["speaker_actor_id"])
        actor = actors.get(actor_id)
        if actor is None and characters is not None:
            raise ValueError(f"conversation_plan turn {turn['turn_id']} references unknown person_id: {actor_id}")
        planned_text = _rewrite_actor_mentions(str(turn["planned_message_text"]), aliases)
        row_turn = {**turn, "planned_message_text": planned_text}
        params = {
            "chat_ref": chat_ref,
            "sender_ref": actor_id,
            "content_text": _prefixed_message(actor, actor_id, planned_text),
        }
        depends_on = [chat_create_steps[chat_ref]]
        if action_type == "reply_in_thread":
            params["root_message_ref"] = thread_root_refs[session_id]
            depends_on.append(thread_root_steps[session_id])
        step_id = f"step_{sequence_no:03d}"
        rows.append(
            _base_row(
                case_id=plan["case_id"],
                family_id=plan["family_id"],
                step_id=step_id,
                sequence_no=sequence_no,
                action_type=action_type,
                session=session,
                topic_key=plan["family_id"],
                depends_on_step_ids=depends_on,
                output_ref=f"msg_{turn['turn_id']}",
                params=params,
                turn=row_turn,
                actor=actor,
            )
        )
        turn_step_ids[str(turn["turn_id"])] = step_id
        session_message_step_ids.setdefault(session_id, []).append(step_id)
        sequence_no += 1

    for session in plan["sessions"]:
        if _source_type(session) != "chat":
            continue
        params = {"chat_ref": _chat_ref(session)}
        rows.append(
            _base_row(
                case_id=plan["case_id"],
                family_id=plan["family_id"],
                step_id=f"step_{sequence_no:03d}",
                sequence_no=sequence_no,
                action_type="fetch_chat_messages",
                session=session,
                topic_key="fetch",
                depends_on_step_ids=[
                    chat_create_steps[_chat_ref(session)],
                    *session_message_step_ids.get(str(session["session_id"]), []),
                ],
                output_ref="",
                params=params,
            )
        )
        sequence_no += 1

    for session in plan["sessions"]:
        if _source_type(session) != "thread":
            continue
        session_id = str(session["session_id"])
        root_ref = thread_root_refs.get(session_id)
        if not root_ref:
            continue
        params = {"chat_ref": _chat_ref(session), "root_message_ref": root_ref}
        rows.append(
            _base_row(
                case_id=plan["case_id"],
                family_id=plan["family_id"],
                step_id=f"step_{sequence_no:03d}",
                sequence_no=sequence_no,
                action_type="fetch_thread_messages",
                session=session,
                topic_key="fetch",
                depends_on_step_ids=[
                    chat_create_steps[_chat_ref(session)],
                    thread_root_steps[session_id],
                    *session_message_step_ids.get(str(session["session_id"]), []),
                ],
                output_ref="",
                params=params,
            )
        )
        sequence_no += 1

    return validate_command_plan(rows)
