from __future__ import annotations

from typing import Any

from .schemas import validate_characters, validate_execution_plan, validate_story, validate_timeline


def _character_map(characters: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {item["person_id"]: item for item in characters["characters"]}


def _prefixed_message(character: dict[str, str], text: str) -> str:
    return f"【{character['department']}/{character['name']}】{text}".strip()


def _message_from_event(event: dict[str, Any], actor: dict[str, str]) -> str:
    event_type = event["event_type"]
    if event_type == "initial_request":
        return _prefixed_message(actor, "客户这边已经开始追问进度了，如果再没有明确动作，交付压力会继续上升。")
    if event_type == "initial_target":
        return _prefixed_message(actor, "当前这个日期只能先当内部目标推进，还不能当成已确认的对外承诺。")
    if event_type == "engineering_blocker":
        return _prefixed_message(actor, "现在真正的 blocker 不只是开发工作量，还有一个关键依赖还没有稳定下来。")
    if event_type == "security_constraint":
        return _prefixed_message(actor, "涉及高风险能力的细节，在评审门槛通过之前都不应该写进承诺口径。")
    if event_type == "ops_risk":
        return _prefixed_message(actor, "上线窗口还没有稳定，回滚准备也没有完全到位，现在不能把日期说得太死。")
    if event_type == "external_messaging_fix":
        return _prefixed_message(actor, "请不要再把这个目标日期当成已确认时间对外同步，外部口径需要收紧。")
    return _prefixed_message(actor, event["description"])


def build_execution_plan(story: dict[str, Any], characters: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
    validated_story = validate_story(story)
    validated_characters = validate_characters(characters)
    validated_timeline = validate_timeline(
        timeline,
        allowed_actor_refs={item["person_id"] for item in validated_characters["characters"]},
    )
    roster = _character_map(validated_characters)
    case_id = validated_story["case_id"]
    task_id = validated_story["task_id"]
    actions: list[dict[str, Any]] = [
        {
            "action_id": "act_001",
            "action_type": "create_chat",
            "params": {
                "chat_ref": "main_chat",
                "name": f"{task_id} 项目协作群",
                "members": sorted(roster.keys()),
            },
            "output_ref": "main_chat",
        }
    ]
    root_output_ref = ""
    surfaced_events = [event for event in validated_timeline["timeline"] if event["should_surface_in_message"]]
    for index, event in enumerate(surfaced_events, start=2):
        actor = roster[event["actor_refs"][0]]
        message = _message_from_event(event, actor)
        output_ref = f"msg_{event['timeline_id']}"
        if not root_output_ref:
            root_output_ref = output_ref
            actions.append(
                {
                    "action_id": f"act_{index:03d}",
                    "action_type": "send_message",
                    "depends_on": ["act_001"],
                    "params": {
                        "chat_ref": "main_chat",
                        "sender_ref": actor["person_id"],
                        "content_text": message,
                    },
                    "output_ref": output_ref,
                }
            )
        else:
            actions.append(
                {
                    "action_id": f"act_{index:03d}",
                    "action_type": "reply_in_thread",
                    "depends_on": ["act_001"],
                    "params": {
                        "chat_ref": "main_chat",
                        "root_message_ref": root_output_ref,
                        "sender_ref": actor["person_id"],
                        "content_text": message,
                    },
                    "output_ref": output_ref,
                }
            )
    if root_output_ref:
        actions.extend(
            [
                {
                    "action_id": f"act_{len(actions)+1:03d}",
                    "action_type": "fetch_chat_messages",
                    "depends_on": ["act_001"],
                    "params": {"chat_ref": "main_chat"},
                },
                {
                    "action_id": f"act_{len(actions)+2:03d}",
                    "action_type": "fetch_thread_messages",
                    "depends_on": ["act_001"],
                    "params": {"chat_ref": "main_chat", "root_message_ref": root_output_ref},
                },
            ]
        )
    plan = {
        "case_id": case_id,
        "operator_identity": "user",
        "delivery_mode": "prefixed_single_operator",
        "actions": actions,
    }
    return validate_execution_plan(plan, allowed_sender_refs=set(roster.keys()))
