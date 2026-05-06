from __future__ import annotations

from typing import Any


def sample_case_spec() -> dict[str, Any]:
    return {
        "case_id": "case_fixture_v3",
        "task_id": "FEISHU-231",
        "difficulty": "medium",
        "seed": 42,
        "comparison_target": "openclaw_memory_md",
        "selected_failure_modes": [
            "static_memory_stale_state",
            "unverifiable_summary_claim",
            "personal_memory_pollution",
        ],
        "primary_failure_mode": "static_memory_stale_state",
    }


def sample_memory_failure_blueprint() -> dict[str, Any]:
    return {
        "case_id": "case_fixture_v3",
        "task_id": "FEISHU-231",
        "comparison_target": "openclaw_memory_md",
        "selected_failure_modes": [
            "static_memory_stale_state",
            "unverifiable_summary_claim",
            "personal_memory_pollution",
        ],
        "primary_failure_mode": "static_memory_stale_state",
        "traps": [
            {
                "trap_id": "trap_owner",
                "failure_mode": "static_memory_stale_state",
                "target_task_id": "FEISHU-231",
                "trap_mechanism": "负责人连续变更，旧负责人是真实历史但不是当前负责人。",
                "common": {
                    "distractor_tasks": ["FEISHU-999"],
                    "shared_actors": ["Bob", "Alice", "xzy"],
                    "probe_queries": ["FEISHU-231 当前负责人是谁？Bob 和 Alice 现在还负责吗？"],
                    "metric_targets": ["current_state_answer_accuracy", "stale_memory_answer_rate"],
                    "landing_requirements": {
                        "required_benchmark_roles": [
                            "stale_state_turn",
                            "supersession_turn",
                            "final_current_state_turn",
                        ],
                        "required_state_fields": ["owner"],
                        "required_evidence_messages_min": 3,
                        "required_probe_queries_min": 1,
                    },
                },
                "typed_payload": {
                    "required_state_track": {
                        "field": "owner",
                        "states": ["Bob", "Alice", "xzy"],
                        "final_current_state": "xzy",
                        "stale_states": ["Bob", "Alice"],
                    }
                },
                "expected_openclaw_failure": "Memory.md 可能把 Bob、Alice、xzy 混成并列负责人。",
                "expected_task_wiki_success": "Task Wiki 应回答 xzy 是当前负责人，并说明 Bob/Alice 只是历史负责人。",
            },
            {
                "trap_id": "trap_claim",
                "failure_mode": "unverifiable_summary_claim",
                "target_task_id": "FEISHU-231",
                "trap_mechanism": "把模糊 hearsay 和明确事实混在一起，诱发无证据总结。",
                "common": {
                    "distractor_tasks": ["FEISHU-999"],
                    "shared_actors": ["Carol"],
                    "probe_queries": ["现在说 FEISHU-231 被财务阻塞，这是谁明确说的？"],
                    "metric_targets": ["unsupported_claim_rate", "evidence_citation_success_rate"],
                    "landing_requirements": {
                        "required_benchmark_roles": [
                            "ambiguous_claim_turn",
                            "ordinary_ack_turn",
                        ],
                        "required_state_fields": [],
                        "required_evidence_messages_min": 2,
                        "required_probe_queries_min": 1,
                    },
                },
                "typed_payload": {
                    "target_claim": "FEISHU-231 当前被财务问题阻塞",
                    "evidence_distribution": {
                        "verified_fact_turns": 1,
                        "ambiguous_turns": 1,
                        "hearsay_turns": 1,
                        "weak_commitment_turns": 0,
                        "no_event_turns": 1,
                    },
                },
                "expected_openclaw_failure": "Memory.md 可能把没有证据的财务阻塞写成确定事实。",
                "expected_task_wiki_success": "Task Wiki 应把它标成 needs_review，并要求回到原始证据。",
            },
            {
                "trap_id": "trap_pollution",
                "failure_mode": "personal_memory_pollution",
                "target_task_id": "FEISHU-231",
                "trap_mechanism": "同一个人跨任务出现，导致个人维度记忆污染到目标任务。",
                "common": {
                    "distractor_tasks": ["FEISHU-999"],
                    "shared_actors": ["Bob"],
                    "probe_queries": ["Bob 在 FEISHU-231 里到底是当前负责人还是 FEISHU-999 的负责人？"],
                    "metric_targets": ["irrelevant_memory_pollution_rate", "memory_scope_purity"],
                    "landing_requirements": {
                        "required_benchmark_roles": [
                            "distractor_task_turn",
                            "memory_pollution_turn",
                        ],
                        "required_state_fields": [],
                        "required_evidence_messages_min": 1,
                        "required_probe_queries_min": 1,
                    },
                },
                "typed_payload": {
                    "target_task_summary": "目标任务只需要当前负责人，不应混入其他任务负责人。",
                    "overlapping_slots": ["owner"],
                    "pollution_dimensions": ["shared_actor", "cross_task_owner"],
                    "distractor_task_ids": ["FEISHU-999"],
                },
                "expected_openclaw_failure": "Memory.md 可能把 FEISHU-999 的负责人记到 FEISHU-231 上。",
                "expected_task_wiki_success": "Task Wiki 应隔离 FEISHU-999，避免 cross-task 污染。",
            },
        ],
    }


def sample_state_trajectory() -> dict[str, Any]:
    return {
        "case_id": "case_fixture_v3",
        "task_id": "FEISHU-231",
        "transitions": [
            {
                "transition_id": "t1",
                "trap_id": "trap_owner",
                "failure_mode": "static_memory_stale_state",
                "state_field": "owner",
                "from_value": "",
                "to_value": "Bob",
                "creates_stale_state": "",
                "supersedes_transition_id": "",
                "is_final_current_state": False,
                "source_session_ref": "chat:main",
                "evidence_requirement": "需要保留 Bob 曾经负责过的证据。",
            },
            {
                "transition_id": "t2",
                "trap_id": "trap_owner",
                "failure_mode": "static_memory_stale_state",
                "state_field": "owner",
                "from_value": "Bob",
                "to_value": "Alice",
                "creates_stale_state": "Bob",
                "supersedes_transition_id": "t1",
                "is_final_current_state": False,
                "source_session_ref": "chat:main",
                "evidence_requirement": "需要记录 Bob 已经被交接掉。",
            },
            {
                "transition_id": "t3",
                "trap_id": "trap_owner",
                "failure_mode": "static_memory_stale_state",
                "state_field": "owner",
                "from_value": "Alice",
                "to_value": "xzy",
                "creates_stale_state": "Alice",
                "supersedes_transition_id": "t2",
                "is_final_current_state": True,
                "source_session_ref": "thread:handoff",
                "evidence_requirement": "必须明确 xzy 是最终当前负责人。",
            },
        ],
        "final_current_state": {"owner": "xzy"},
    }


def sample_coverage_spec() -> dict[str, Any]:
    return {
        "case_id": "case_fixture_v3",
        "required_failure_modes": [
            "static_memory_stale_state",
            "unverifiable_summary_claim",
            "personal_memory_pollution",
        ],
        "required_benchmark_roles": [
            "stale_state_turn",
            "supersession_turn",
            "final_current_state_turn",
            "ambiguous_claim_turn",
            "ordinary_ack_turn",
            "distractor_task_turn",
        ],
        "required_query_types": ["current_state", "evidence_trace", "scope_purity"],
        "required_state_fields": ["owner"],
        "trap_coverage": {"required_traps": ["trap_owner", "trap_claim", "trap_pollution"]},
        "hard_gates": {"min_probe_queries": 3},
    }


def sample_story_beats() -> dict[str, Any]:
    return {
        "case_id": "case_fixture_v3",
        "beats": [
            {
                "beat_id": "beat1",
                "trap_id": "trap_owner",
                "failure_mode": "static_memory_stale_state",
                "beat_type": "trap beat",
                "benchmark_role": "stale_state_turn",
                "description": "先给出旧负责人 Bob。",
                "target_session_id": "sess_main",
            }
        ],
    }


def sample_conversation_plan() -> dict[str, Any]:
    return {
        "case_id": "case_fixture_v3",
        "task_id": "FEISHU-231",
        "sessions": [
            {
                "session_id": "sess_main",
                "source_type": "chat",
                "source_ref": "chat:main",
                "chat_ref": "chat_main",
                "title": "主群",
                "session_purpose": "项目主讨论群",
                "root_turn_id": None,
            }
        ],
        "turns": [],
    }


def sample_collected_messages() -> list[dict[str, Any]]:
    base = {
        "session_id": "sess_main",
        "source_type": "chat",
        "source_ref": "chat:main",
        "chat_ref": "chat_main",
        "speaker_ref": "person_bob",
        "topic_key": "owner_handoff",
        "turn_purpose": "推进负责人交接",
        "semantic_payload": "负责人状态修正",
        "collect_source": "simulated_observation",
        "actual_sender": {"open_id": "ou_bob", "name": "Bob", "sender_type": "user"},
        "simulated_speaker": {
            "speaker_ref": "person_bob",
            "open_id": "ou_bob",
            "name": "Bob",
            "department": "研发",
            "role": "研发负责人",
        },
        "normalized_actor_id": "person_bob",
        "speaker_resolution_mode": "command_plan_only",
        "prefix_speaker_hint": {},
        "probe_query_hints": [],
    }
    return [
        {
            **base,
            "turn_id": "turn_1",
            "sequence_no": 1,
            "content_text": "FEISHU-231 最早由 Bob 负责。",
            "message_id": "m1",
            "benchmark_role": "stale_state_turn",
            "memory_failure_mode": "static_memory_stale_state",
            "memory_trap": "trap_owner",
            "state_field_hints": ["owner"],
        },
        {
            **base,
            "turn_id": "turn_2",
            "sequence_no": 2,
            "content_text": "现在 FEISHU-231 改成 Alice 接手，Bob 只是历史负责人。",
            "message_id": "m2",
            "benchmark_role": "supersession_turn",
            "memory_failure_mode": "static_memory_stale_state",
            "memory_trap": "trap_owner",
            "state_field_hints": ["owner"],
        },
        {
            **base,
            "turn_id": "turn_3",
            "sequence_no": 3,
            "content_text": "最终负责人定为 xzy，Bob 和 Alice 现在都不负责了。",
            "message_id": "m3",
            "benchmark_role": "final_current_state_turn",
            "memory_failure_mode": "static_memory_stale_state",
            "memory_trap": "trap_owner",
            "state_field_hints": ["owner"],
        },
        {
            **base,
            "turn_id": "turn_4",
            "sequence_no": 4,
            "content_text": "有人说 FEISHU-231 可能会被财务卡住，但目前没人确认。",
            "message_id": "m4",
            "benchmark_role": "ambiguous_claim_turn",
            "memory_failure_mode": "unverifiable_summary_claim",
            "memory_trap": "trap_claim",
            "state_field_hints": [],
        },
        {
            **base,
            "turn_id": "turn_5",
            "sequence_no": 5,
            "content_text": "收到。",
            "message_id": "m5",
            "benchmark_role": "ordinary_ack_turn",
            "memory_failure_mode": "unverifiable_summary_claim",
            "memory_trap": "trap_claim",
            "state_field_hints": [],
        },
        {
            **base,
            "turn_id": "turn_6",
            "sequence_no": 6,
            "content_text": "FEISHU-999 现在还是 Bob 负责，这个别记到 FEISHU-231 上。",
            "message_id": "m6",
            "benchmark_role": "distractor_task_turn",
            "memory_failure_mode": "personal_memory_pollution",
            "memory_trap": "trap_pollution",
            "state_field_hints": [],
        },
    ]


def sample_prediction_events() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate = [
        {
            "event_id": "evt_1",
            "core_entry_id": "m1",
            "event_type": "status_event",
            "claim": "FEISHU-231 最早由 Bob 负责。",
            "evidence_quote": "FEISHU-231 最早由 Bob 负责。",
            "verification": {"verdict": "verified"},
        },
        {
            "event_id": "evt_2",
            "core_entry_id": "m2",
            "event_type": "status_event",
            "claim": "现在 FEISHU-231 改成 Alice 接手。",
            "evidence_quote": "现在 FEISHU-231 改成 Alice 接手，Bob 只是历史负责人。",
            "verification": {"verdict": "verified"},
        },
        {
            "event_id": "evt_3",
            "core_entry_id": "m3",
            "event_type": "status_event",
            "claim": "最终负责人定为 xzy。",
            "evidence_quote": "最终负责人定为 xzy，Bob 和 Alice 现在都不负责了。",
            "verification": {"verdict": "verified"},
        },
        {
            "event_id": "evt_4",
            "core_entry_id": "m4",
            "event_type": "status_event",
            "claim": "有人说 FEISHU-231 可能会被财务卡住。",
            "evidence_quote": "有人说 FEISHU-231 可能会被财务卡住，但目前没人确认。",
            "verification": {"verdict": "needs_review"},
        },
        {
            "event_id": "evt_5",
            "core_entry_id": "m6",
            "event_type": "status_event",
            "claim": "FEISHU-999 现在还是 Bob 负责。",
            "evidence_quote": "FEISHU-999 现在还是 Bob 负责，这个别记到 FEISHU-231 上。",
            "verification": {"verdict": "rejected"},
        },
    ]
    session = [item for item in candidate[:3]]
    return candidate, session


def sample_task_wiki_state() -> dict[str, Any]:
    return {
        "current_summary": "当前 FEISHU-231 的负责人已经收敛到 xzy。",
        "sections": {
            "conclusion": [
                {
                    "slot": "conclusion",
                    "topic_key": "owner_handoff",
                    "topic_title": "负责人交接",
                    "claim": "最终负责人定为 xzy。",
                    "event_id": "evt_3",
                    "event_ref": "[[sessions/a/session_events.jsonl#evt_3|evt_3]]",
                }
            ],
            "status": [
                {
                    "slot": "status",
                    "topic_key": "owner_handoff",
                    "topic_title": "负责人交接",
                    "claim": "Bob 和 Alice 现在都不负责了。",
                    "event_id": "evt_3",
                    "event_ref": "[[sessions/a/session_events.jsonl#evt_3|evt_3]]",
                }
            ],
        },
        "related_blocks": [
            {
                "topic_key": "owner_handoff",
                "topic_title": "负责人交接",
                "summary": "负责人已经稳定为 xzy。",
                "block_link": "sessions/a/session_wiki.md#block-owner",
            }
        ],
    }
