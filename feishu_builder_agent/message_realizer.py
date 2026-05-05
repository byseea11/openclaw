from __future__ import annotations

from typing import Any

from .llm_client import JsonLLMClient
from .prompt_templates import build_message_realizer_prompts
from .schemas import ValidationError, validate_characters, validate_realized_messages, validate_utterance_plan


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["person_id"]: item for item in validate_characters(characters)["characters"]}


def _prefixed_message(character: dict[str, Any], text: str) -> str:
    return f"【{character['department']}/{character['name']}】{text}".strip()


def _fallback_content_text(row: dict[str, Any], character: dict[str, Any]) -> str:
    payload = row["semantic_payload"]
    purpose = row["turn_purpose"]
    if row["topic_key"] == "release_date":
        return _prefixed_message(character, f"{payload} 这也是我们当前需要统一的发布时间口径。")
    if row["topic_key"] == "blocker_readiness":
        return _prefixed_message(character, f"{payload} 先把 blocker 讲清楚，再决定后面的承诺。")
    if row["topic_key"] == "rollback_readiness":
        return _prefixed_message(character, f"{payload} 回滚和上线准备不到位的话，日期就不能说死。")
    if row["topic_key"] == "external_messaging":
        return _prefixed_message(character, f"{payload} 这个口径请前线和主群保持一致。")
    return _prefixed_message(character, f"{payload} {purpose}")


def realize_messages_with_mode(
    utterance_plan: list[dict[str, Any]],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> tuple[list[dict[str, Any]], str]:
    validated_characters = validate_characters(characters)
    roster = _character_map(validated_characters)
    validated_rows = validate_utterance_plan(utterance_plan, allowed_actor_refs=set(roster.keys()))
    if llm_client is None:
        realized = []
        for row in validated_rows:
            character = roster[row["speaker_ref"]]
            realized.append({**row, "content_text": _fallback_content_text(row, character)})
        return validate_realized_messages(realized, allowed_actor_refs=set(roster.keys())), "fallback"
    realized_rows: list[dict[str, Any]] = []
    live_success_count = 0
    for row in validated_rows:
        character = roster[row["speaker_ref"]]
        system_prompt, user_prompt = build_message_realizer_prompts(
            character=character,
            row=row,
        )
        try:
            payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            content_text = str(payload.get("content_text") or "").strip()
            if not content_text:
                raise ValidationError("content_text must be non-empty")
            realized_rows.append({**row, "content_text": content_text})
            live_success_count += 1
        except (Exception, ValidationError):
            realized_rows.append({**row, "content_text": _fallback_content_text(row, character)})
    mode = "live" if live_success_count == len(validated_rows) else "mixed" if live_success_count > 0 else "fallback"
    return validate_realized_messages(realized_rows, allowed_actor_refs=set(roster.keys())), mode


def realize_messages(
    utterance_plan: list[dict[str, Any]],
    characters: dict[str, Any],
    *,
    llm_client: JsonLLMClient | None = None,
) -> list[dict[str, Any]]:
    rows, _mode = realize_messages_with_mode(utterance_plan, characters, llm_client=llm_client)
    return rows
