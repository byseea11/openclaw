from __future__ import annotations

import re
from itertools import cycle
from typing import Any

from ..builder_settings import resolve_difficulty_settings
from ..llm import (
    BuilderModelClient,
    ModelPayloadValidationError,
    build_model_call_log_entry,
    create_model_client,
)
from ..prompt import build_conversation_plan_system_prompt
from ..schemas import ValidationError, validate_conversation_plan_artifact, validate_official_file_plan


TURN_KINDS = (
    "event_bearing",
    "context_support",
    "interference_noise",
    "ack_or_coordination",
    "revision_bridge",
)

FORBIDDEN_TEMPLATE_SNIPPETS = (
    "企业协作补充事实",
    "收到，我先按这个口径记录",
)


def _actor_cycle(story_plan: dict[str, Any]) -> list[dict[str, Any]]:
    actors = list(story_plan["actors"])
    if not actors:
        raise ValueError("story_plan.actors must not be empty")
    return actors


def _speaker(actor: dict[str, Any]) -> tuple[str, str]:
    return str(actor["actor_id"]), str(actor.get("display_name") or actor["actor_id"])


def _fallback_text(*, task_id: str, turn_kind: str, index: int, session: dict[str, Any]) -> str:
    title = str(session["title"])
    variants = {
        "context_support": [
            f"{title} 这边补一条背景：{task_id} 的任务页只接受正式确认，不收个人备注当结论。",
            f"我把 {title} 的前情放这里，后面问 current state 时要回到任务项本身。",
            f"{task_id} 在这个会话里有上下文，但真正能落 wiki 的只有已确认任务事实。",
        ],
        "interference_noise": [
            f"旁边还有一个相似项目也在看 checklist，别把那边的负责人带到 {task_id}。",
            f"这个说法听起来像 {task_id}，但其实是另一个并行风险登记，不要混。",
            f"我这里提到的个人安排只是沟通背景，不是 {task_id} 的 blocker。",
        ],
        "ack_or_coordination": [
            f"我先标成待确认，等正式文件或 owner 纠偏后再更新 {task_id} 的任务页。",
            f"这个先不写成结论，只作为后续核对 {task_id} 的上下文。",
            f"明白，我会在同步时区分个人背景和 {task_id} 的正式状态。",
        ],
        "revision_bridge": [
            f"如果后面正式 checklist 有更新，以最新文件结论覆盖这里的旧口径。",
            f"这里先留一条桥接说明：聊天转述不能替代正式文件里的 current state。",
            f"等 owner 确认后，我们再把 {task_id} 的状态从待确认改成最终口径。",
        ],
        "event_bearing": [
            f"{task_id} 当前仍按正式 checklist 记录：个人附注只作为 evidence，不改变任务结论。",
            f"{task_id} 的 owner 口径没有因为个人安排改变，正式文件仍是主证据。",
            f"{task_id} 的风险登记需要引用正式纪要，不能只用私聊承诺判断。",
        ],
    }
    choices = variants[turn_kind]
    return f"{choices[index % len(choices)]}（线索 {index}）"


def _build_conversation_plan_user_payload(
    *,
    case_context: dict[str, Any],
    case_world_artifact: dict[str, Any],
    story_beats_artifact: dict[str, Any],
    story_plan: dict[str, Any],
    characters: dict[str, Any],
    actor_registry: dict[str, Any],
    official_file_plan: dict[str, Any],
) -> dict[str, Any]:
    difficulty = resolve_difficulty_settings(str(case_context["difficulty"]))
    return {
        "case_context": case_context,
        "case_world_artifact": case_world_artifact,
        "story_beats_artifact": story_beats_artifact,
        "story_plan": story_plan,
        "characters": characters,
        "actor_registry": actor_registry,
        "official_file_plan": official_file_plan,
        "difficulty_scale": {
            "total_turn_count_min": difficulty["total_turn_count_min"],
            "total_turn_count_max": difficulty["total_turn_count_max"],
            "event_bearing_turn_count_min": difficulty["event_bearing_turn_count_min"],
            "event_bearing_turn_count_max": difficulty["event_bearing_turn_count_max"],
            "recommended_session_count": difficulty["recommended_session_count"],
        },
        "output_contract": {
            "artifact_name": "conversation_plan_artifact",
            "must_generate_complete_transcript": True,
            "planned_message_text_max_chars": 45,
            "must_output_exact_turn_count": difficulty["total_turn_count_min"],
            "forbidden_template_snippets": list(FORBIDDEN_TEMPLATE_SNIPPETS),
            "turn_trace_fields": [
                "turn_kind",
                "annotation_target",
                "event_bearing",
                "official_file_ref",
                "private_info_ref",
                "task_relevance_boundary",
            ],
        },
    }


def _normalize_model_conversation_plan(
    *,
    model_payload: dict[str, Any],
    case_context: dict[str, Any],
    case_world_artifact: dict[str, Any],
    official_file_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = str(case_context["task_id"])
    official_refs: list[str] = []
    private_refs: list[str] = []
    if official_file_plan is not None:
        plan = validate_official_file_plan(official_file_plan)
        official_refs = [str(file["file_ref"]) for file in plan["official_files"]]
        private_refs = [
            str(info["private_info_ref"])
            for file in plan["official_files"]
            for info in file["private_info_items"]
        ]
    normalized = dict(model_payload)
    normalized["case_id"] = str(case_context["case_id"])
    normalized["family_id"] = str(case_context["family_id"])
    normalized["task_id"] = task_id
    normalized["sessions"] = list(case_world_artifact["source_sessions"])
    turns: list[dict[str, Any]] = []
    for index, raw_turn in enumerate(list(model_payload.get("turns") or []), start=1):
        if not isinstance(raw_turn, dict):
            continue
        turn = dict(raw_turn)
        turn["turn_id"] = f"turn_{index:03d}"
        turn["sequence_no"] = index
        if not str(turn.get("beat_id") or "").strip():
            turn["beat_id"] = ""
            turn["annotation_target"] = False
        official_ref = str(turn.get("official_file_ref") or "").strip()
        if official_ref and official_refs and official_ref not in official_refs:
            turn["official_file_ref"] = official_refs[(index - 1) % len(official_refs)]
        private_ref = str(turn.get("private_info_ref") or "").strip()
        if private_ref and private_refs and private_ref not in private_refs:
            turn["private_info_ref"] = private_refs[(index - 1) % len(private_refs)]
        text = str(turn.get("planned_message_text") or "")
        turn["planned_message_text"] = re.sub(r"FEISHU-\d+", task_id, text)
        turns.append(turn)
    normalized["turns"] = turns
    return normalized


def validate_conversation_plan_quality(
    *,
    artifact: dict[str, Any],
    case_context: dict[str, Any],
    official_file_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    difficulty = resolve_difficulty_settings(str(case_context["difficulty"]))
    turns = list(artifact["turns"])
    total_turns = len(turns)
    if total_turns < int(difficulty["total_turn_count_min"]):
        raise ValidationError("conversation_plan_artifact.turns is below difficulty total_turn_count_min")
    if total_turns > int(difficulty["total_turn_count_max"]):
        raise ValidationError("conversation_plan_artifact.turns exceeds difficulty total_turn_count_max")
    event_turns = [turn for turn in turns if turn["event_bearing"]]
    if len(event_turns) < int(difficulty["event_bearing_turn_count_min"]):
        raise ValidationError("conversation_plan_artifact has too few event_bearing turns")
    texts = [str(turn["planned_message_text"]).strip() for turn in turns]
    for snippet in FORBIDDEN_TEMPLATE_SNIPPETS:
        if any(snippet in text for text in texts):
            raise ValidationError(f"conversation_plan_artifact contains forbidden template snippet: {snippet}")
    repeated_texts = {text for text in texts if texts.count(text) > 2}
    if repeated_texts:
        raise ValidationError("conversation_plan_artifact has excessive duplicate message text")
    if str(case_context["family_id"]) == "private_info_in_official_file":
        official_refs = {str(turn.get("official_file_ref") or "") for turn in turns}
        private_refs = {str(turn.get("private_info_ref") or "") for turn in turns}
        boundaries = [turn for turn in turns if str(turn.get("task_relevance_boundary") or "").strip()]
        if not any(ref for ref in official_refs):
            raise ValidationError("private_info_in_official_file requires official_file_ref turns")
        if not any(ref for ref in private_refs):
            raise ValidationError("private_info_in_official_file requires private_info_ref turns")
        if not boundaries:
            raise ValidationError("private_info_in_official_file requires task_relevance_boundary turns")
        if official_file_plan is not None:
            plan = validate_official_file_plan(official_file_plan)
            known_file_refs = {file["file_ref"] for file in plan["official_files"]}
            unknown_refs = sorted(ref for ref in official_refs if ref and ref not in known_file_refs)
            if unknown_refs:
                raise ValidationError(f"conversation_plan references unknown official_file_ref: {unknown_refs}")
    return artifact


def generate_conversation_plan(
    *,
    case_context: dict[str, Any],
    case_world_artifact: dict[str, Any],
    story_beats_artifact: dict[str, Any],
    story_plan: dict[str, Any],
    characters: dict[str, Any],
    actor_registry: dict[str, Any],
    official_file_plan: dict[str, Any],
    model_client: BuilderModelClient | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    client = model_client or create_model_client()
    system_prompt = build_conversation_plan_system_prompt(
        family_id=str(case_context["family_id"]),
        difficulty=str(case_context["difficulty"]),
    )
    user_payload = _build_conversation_plan_user_payload(
        case_context=case_context,
        case_world_artifact=case_world_artifact,
        story_beats_artifact=story_beats_artifact,
        story_plan=story_plan,
        characters=characters,
        actor_registry=actor_registry,
        official_file_plan=official_file_plan,
    )
    result = client.complete_json(
        stage="conversation-plan",
        system_prompt=system_prompt,
        user_payload=user_payload,
    )
    try:
        validated = validate_conversation_plan_artifact(
            _normalize_model_conversation_plan(
                model_payload=result.payload,
                case_context=case_context,
                case_world_artifact=case_world_artifact,
                official_file_plan=official_file_plan,
            )
        )
        validate_conversation_plan_quality(
            artifact=validated,
            case_context=case_context,
            official_file_plan=official_file_plan,
        )
    except ValidationError as exc:
        raise ModelPayloadValidationError(
            f"conversation-plan payload validation failed: {exc}",
            stage="conversation-plan",
            payload=result.payload,
            backend=result.backend,
            model=result.model,
            base_url=result.base_url,
            duration_ms=result.duration_ms,
        ) from exc
    return validated, [
        build_model_call_log_entry(
            stage="conversation-plan",
            result=result,
            case_id=str(case_context["case_id"]),
            artifact_path="input/conversation_plan.json",
        )
    ]


def build_conversation_plan_artifact(
    *,
    case_context: dict[str, Any],
    case_world_artifact: dict[str, Any],
    story_beats_artifact: dict[str, Any],
    story_plan: dict[str, Any],
    official_file_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    beat_lookup = {beat["beat_id"]: beat for beat in story_beats_artifact["beats"]}
    sessions = list(case_world_artifact["source_sessions"])
    if not sessions:
        raise ValueError("case_world_artifact.source_sessions must not be empty")
    difficulty = resolve_difficulty_settings(str(case_context["difficulty"]))
    target_total_turns = int(difficulty["total_turn_count_min"])
    target_event_turns = int(difficulty["event_bearing_turn_count_min"])
    task_id = str(case_context["task_id"])
    turns: list[dict[str, Any]] = []
    official_refs = []
    private_refs = []
    if official_file_plan is not None:
        plan = validate_official_file_plan(official_file_plan)
        official_refs = [file["file_ref"] for file in plan["official_files"]]
        private_refs = [
            info["private_info_ref"]
            for file in plan["official_files"]
            for info in file["private_info_items"]
        ]

    for beat in story_plan["message_beats"]:
        beat_id = str(beat["beat_id"])
        if beat_id not in beat_lookup:
            raise ValueError(f"conversation turn references unknown beat_id: {beat_id}")
        trace_index = len(turns)
        turns.append(
            {
                "turn_id": f"turn_{len(turns) + 1:03d}",
                "beat_id": beat_id,
                "sequence_no": len(turns) + 1,
                "session_id": str(beat["session_id"]),
                "speaker_actor_id": str(beat["speaker_actor_id"]),
                "speaker": str(beat["speaker"]),
                "planned_message_text": str(beat["message_intent"]),
                "turn_kind": "event_bearing",
                "annotation_target": True,
                "event_bearing": True,
                "official_file_ref": official_refs[trace_index % len(official_refs)] if official_refs else "",
                "private_info_ref": "",
                "task_relevance_boundary": "",
            }
        )

    actors = _actor_cycle(story_plan)
    actor_iter = cycle(actors)
    session_iter = cycle(sessions)
    kind_cycle = cycle(("context_support", "interference_noise", "ack_or_coordination", "revision_bridge"))
    event_count = sum(1 for turn in turns if turn["event_bearing"])
    support_index = 1

    while event_count < target_event_turns:
        actor = next(actor_iter)
        session = next(session_iter)
        actor_id, speaker = _speaker(actor)
        trace_index = len(turns)
        turns.append(
            {
                "turn_id": f"turn_{len(turns) + 1:03d}",
                "beat_id": "",
                "sequence_no": len(turns) + 1,
                "session_id": str(session["session_id"]),
                "speaker_actor_id": actor_id,
                "speaker": speaker,
                "planned_message_text": _fallback_text(
                    task_id=task_id,
                    turn_kind="event_bearing",
                    index=support_index,
                    session=session,
                ),
                "turn_kind": "event_bearing",
                "annotation_target": False,
                "event_bearing": True,
                "official_file_ref": official_refs[trace_index % len(official_refs)] if official_refs else "",
                "private_info_ref": "",
                "task_relevance_boundary": "",
            }
        )
        support_index += 1
        event_count += 1

    while len(turns) < target_total_turns:
        actor = next(actor_iter)
        session = next(session_iter)
        turn_kind = next(kind_cycle)
        actor_id, speaker = _speaker(actor)
        trace_index = len(turns)
        turns.append(
            {
                "turn_id": f"turn_{len(turns) + 1:03d}",
                "beat_id": "",
                "sequence_no": len(turns) + 1,
                "session_id": str(session["session_id"]),
                "speaker_actor_id": actor_id,
                "speaker": speaker,
                "planned_message_text": _fallback_text(
                    task_id=task_id,
                    turn_kind=turn_kind,
                    index=support_index,
                    session=session,
                ),
                "turn_kind": turn_kind,
                "annotation_target": False,
                "event_bearing": False,
                "official_file_ref": official_refs[trace_index % len(official_refs)] if official_refs else "",
                "private_info_ref": private_refs[trace_index % len(private_refs)] if private_refs else "",
                "task_relevance_boundary": (
                    "个人信息只作为 evidence/context，不得写入任务 current state。"
                    if private_refs and turn_kind in {"context_support", "revision_bridge"}
                    else ""
                ),
            }
        )
        support_index += 1

    artifact = validate_conversation_plan_artifact(
        {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "task_id": task_id,
            "sessions": sessions,
            "turns": turns,
        }
    )
    return validate_conversation_plan_quality(
        artifact=artifact,
        case_context=case_context,
        official_file_plan=official_file_plan,
    )
