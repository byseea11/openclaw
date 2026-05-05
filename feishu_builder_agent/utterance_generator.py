from __future__ import annotations

from typing import Any

from .llm_client import JsonLLMClient
from .prompt_templates import build_utterance_plan_prompts
from .schemas import ValidationError, validate_characters, validate_conversation_plan, validate_target_state, validate_utterance_plan


def _session_map(conversation_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["session_id"]: item for item in conversation_plan["sessions"]}


def _fallback_utterance_plan(conversation_plan: dict[str, Any]) -> list[dict[str, Any]]:
    validated = validate_conversation_plan(conversation_plan)
    sessions = _session_map(validated)
    rows: list[dict[str, Any]] = []
    for turn in validated["turns"]:
        session = sessions[turn["session_id"]]
        rows.append(
            {
                "turn_id": turn["turn_id"],
                "sequence_no": turn["sequence_no"],
                "session_id": turn["session_id"],
                "source_type": session["source_type"],
                "source_ref": session["source_ref"],
                "chat_ref": session["chat_ref"],
                "speaker_ref": turn["speaker_ref"],
                "topic_key": turn["topic_key"],
                "turn_purpose": turn["turn_purpose"],
                "supports_event_types": turn["supports_event_types"],
                "references_previous_turns": turn["references_previous_turns"],
                "state_transition": turn["state_transition"],
                "semantic_payload": turn["semantic_payload"],
                "root_turn_id": session.get("root_turn_id"),
            }
        )
    return rows


def generate_utterance_plan_with_mode(
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
    *,
    target_state: dict[str, Any] | None = None,
    llm_client: JsonLLMClient | None = None,
) -> tuple[list[dict[str, Any]], str]:
    validated_plan = validate_conversation_plan(
        conversation_plan,
        allowed_actor_refs={item["person_id"] for item in validate_characters(characters)["characters"]},
    )
    validated_characters = validate_characters(characters)
    validated_target_state = validate_target_state(target_state) if target_state is not None else None
    roster_ids = {item["person_id"] for item in validated_characters["characters"]}
    if llm_client is None:
        return validate_utterance_plan(_fallback_utterance_plan(validated_plan), allowed_actor_refs=roster_ids), "fallback"
    system_prompt, user_prompt = build_utterance_plan_prompts(
        validated_plan=validated_plan,
        validated_characters=validated_characters,
        validated_target_state=validated_target_state,
    )
    try:
        payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        return validate_utterance_plan(list(rows or []), allowed_actor_refs=roster_ids), "live"
    except (Exception, ValidationError):
        return validate_utterance_plan(_fallback_utterance_plan(validated_plan), allowed_actor_refs=roster_ids), "fallback"


def generate_utterance_plan(
    conversation_plan: dict[str, Any],
    characters: dict[str, Any],
    *,
    target_state: dict[str, Any] | None = None,
    llm_client: JsonLLMClient | None = None,
) -> list[dict[str, Any]]:
    rows, _mode = generate_utterance_plan_with_mode(
        conversation_plan,
        characters,
        target_state=target_state,
        llm_client=llm_client,
    )
    return rows
