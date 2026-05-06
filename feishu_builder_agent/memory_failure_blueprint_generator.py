from __future__ import annotations

from typing import Any

from .builder_settings import load_builder_settings
from .llm_client import live_llm_required
from .logging_utils import builder_log
from .prompt_registry import build_memory_failure_blueprint_prompts
from .schemas import validate_case_spec, validate_memory_failure_blueprint


def _personal_memory_pollution_trap(case_spec: dict[str, Any]) -> dict[str, Any]:
    task_id = case_spec["task_id"]
    return {
        "trap_id": f"trap_{task_id.lower().replace('-', '_')}_pollution_001",
        "failure_mode": "personal_memory_pollution",
        "target_task_id": task_id,
        "trap_mechanism": "同一负责人同时参与目标任务和两个相似项目，容易把其他任务的 blocker 和 owner 污染到当前任务记忆中。",
        "common": {
            "distractor_tasks": ["FEISHU-291", "FEISHU-377"],
            "shared_actors": ["product_owner_1", "engineering_owner_1"],
            "probe_queries": [
                f"{task_id} 当前真正的 owner 和 blocker 是谁？哪些信息只是其他任务的干扰？"
            ],
            "metric_targets": ["irrelevant_memory_pollution_rate", "memory_scope_purity"],
            "landing_requirements": {
                "required_benchmark_roles": [
                    "target_fact_turn",
                    "shared_actor_turn",
                    "distractor_task_turn",
                    "memory_pollution_turn",
                ],
                "required_state_fields": ["owner", "blocker"],
                "required_evidence_messages_min": 4,
                "required_probe_queries_min": 1,
            },
        },
        "typed_payload": {
            "target_task_summary": "目标任务需要区分当前 owner、真实 blocker 和其他任务的相似描述。",
            "overlapping_slots": ["owner", "blocker", "next_step"],
            "pollution_dimensions": ["shared_actor", "similar_status_wording", "cross_task_reference"],
            "distractor_task_ids": ["FEISHU-291", "FEISHU-377"],
        },
        "expected_openclaw_failure": "Memory.md 可能把共享人员在其他任务里的状态误写进目标任务摘要，导致 scope 被污染。",
        "expected_task_wiki_success": "Task Wiki 应按 task 隔离事件，并能回答哪些 owner/blocker 属于当前任务、哪些只是干扰上下文。",
    }


def _unverifiable_summary_claim_trap(case_spec: dict[str, Any]) -> dict[str, Any]:
    task_id = case_spec["task_id"]
    return {
        "trap_id": f"trap_{task_id.lower().replace('-', '_')}_claim_001",
        "failure_mode": "unverifiable_summary_claim",
        "target_task_id": task_id,
        "trap_mechanism": "把模糊说法、传闻和普通应答夹在一起，诱发无证据总结。",
        "common": {
            "distractor_tasks": ["FEISHU-412"],
            "shared_actors": ["finance_partner_1", "product_owner_1"],
            "probe_queries": [
                f"现在说 {task_id} 受财务问题阻塞，这是谁明确说的？证据在哪？"
            ],
            "metric_targets": ["unsupported_claim_rate", "evidence_citation_success_rate"],
            "landing_requirements": {
                "required_benchmark_roles": [
                    "evidence_anchor_turn",
                    "ambiguous_claim_turn",
                    "hearsay_turn",
                    "ordinary_ack_turn",
                ],
                "required_state_fields": ["blocker"],
                "required_evidence_messages_min": 4,
                "required_probe_queries_min": 1,
            },
        },
        "typed_payload": {
            "target_claim": f"{task_id} 当前受财务问题阻塞",
            "evidence_distribution": {
                "verified_fact_turns": 2,
                "ambiguous_turns": 2,
                "hearsay_turns": 1,
                "weak_commitment_turns": 1,
                "no_event_turns": 2,
            },
        },
        "expected_openclaw_failure": "Memory.md 可能把猜测或传闻写成确定事实，而且无法追溯到原始证据。",
        "expected_task_wiki_success": "Task Wiki 应区分 verified、needs_review 和 no-event，不把模糊说法升级成确定结论。",
    }


def _static_memory_stale_state_trap(case_spec: dict[str, Any]) -> dict[str, Any]:
    task_id = case_spec["task_id"]
    return {
        "trap_id": f"trap_{task_id.lower().replace('-', '_')}_stale_001",
        "failure_mode": "static_memory_stale_state",
        "target_task_id": task_id,
        "trap_mechanism": "负责人与发布日期连续修正，旧状态仍是真实历史，但不应当作当前状态。",
        "common": {
            "distractor_tasks": ["FEISHU-188"],
            "shared_actors": ["engineering_owner_1", "ops_owner_1", "product_owner_1"],
            "probe_queries": [
                f"{task_id} 当前负责人是谁？Bob 和 Alice 现在还负责吗？"
            ],
            "metric_targets": ["stale_memory_answer_rate", "current_state_answer_accuracy"],
            "landing_requirements": {
                "required_benchmark_roles": [
                    "stale_state_turn",
                    "supersession_turn",
                    "final_current_state_turn",
                    "current_state_disambiguation_turn",
                ],
                "required_state_fields": ["owner", "release_window"],
                "required_evidence_messages_min": 4,
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
        "expected_openclaw_failure": "Memory.md 可能同时保留多个历史 owner，但无法稳定区分谁是当前 owner。",
        "expected_task_wiki_success": "Task Wiki 应回答当前 owner 是最终状态，并把旧 owner 标记为历史状态，引用交接证据。",
    }


def _dependency_propagation_failure_trap(case_spec: dict[str, Any]) -> dict[str, Any]:
    task_id = case_spec["task_id"]
    return {
        "trap_id": f"trap_{task_id.lower().replace('-', '_')}_dependency_001",
        "failure_mode": "dependency_propagation_failure",
        "target_task_id": task_id,
        "trap_mechanism": "上游依赖变化导致目标任务当前状态反转，但静态总结未传播更新。",
        "common": {
            "distractor_tasks": ["FEISHU-188"],
            "shared_actors": ["security_reviewer_1", "operations_owner_1"],
            "probe_queries": [
                f"{task_id} 为什么又不能锁发布日期了？这和上游依赖变化有什么关系？"
            ],
            "metric_targets": ["dependency_impact_recall", "current_state_answer_accuracy"],
            "landing_requirements": {
                "required_benchmark_roles": [
                    "dependency_link_turn",
                    "dependency_update_turn",
                    "current_state_disambiguation_turn",
                ],
                "required_state_fields": ["dependency_status", "launch_readiness"],
                "required_evidence_messages_min": 3,
                "required_probe_queries_min": 1,
            },
        },
        "typed_payload": {
            "upstream_task_id": "FEISHU-188",
            "dependency_chain": ["budget approval", "security signoff", "release window"],
            "impacted_field": "launch_readiness",
            "expected_missed_update": "如果记忆没有传播依赖更新，就会错误地把任务仍视为 ready。",
        },
        "expected_openclaw_failure": "Memory.md 可能记录了旧 readiness，却没有把上游变化重新投影到目标任务当前状态。",
        "expected_task_wiki_success": "Task Wiki 应把上游依赖变化转写成目标任务 current state 变化，并能解释因果链。",
    }


def _fallback_trap(case_spec: dict[str, Any], failure_mode: str) -> dict[str, Any]:
    if failure_mode == "personal_memory_pollution":
        return _personal_memory_pollution_trap(case_spec)
    if failure_mode == "unverifiable_summary_claim":
        return _unverifiable_summary_claim_trap(case_spec)
    if failure_mode == "static_memory_stale_state":
        return _static_memory_stale_state_trap(case_spec)
    if failure_mode == "dependency_propagation_failure":
        return _dependency_propagation_failure_trap(case_spec)
    raise ValueError(f"unsupported failure mode: {failure_mode}")


def request_blueprint_json(case_spec: dict[str, Any], *, llm_client: Any | None = None) -> dict[str, Any]:
    system_prompt, user_prompt = build_memory_failure_blueprint_prompts(case_spec)
    if llm_client is None and live_llm_required():
        raise RuntimeError("memory-failure-blueprint requires live LLM but no active llm_client is available")
    if llm_client is not None:
        try:
            payload = llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
            builder_log("memory-failure-blueprint", f"使用 live LLM blueprint 生成。prompt_size={len(user_prompt)}")
            return payload
        except Exception as exc:
            if live_llm_required():
                raise RuntimeError(f"memory-failure-blueprint requires live LLM but failed: {exc}") from exc
            builder_log("memory-failure-blueprint", f"live LLM blueprint 生成失败，回退 fallback。reason={exc}")
    builder_log("memory-failure-blueprint", f"使用 fallback blueprint 生成。prompt_size={len(user_prompt)}")
    return {
        "case_id": case_spec["case_id"],
        "task_id": case_spec["task_id"],
        "comparison_target": case_spec["comparison_target"],
        "selected_failure_modes": list(case_spec["selected_failure_modes"]),
        "primary_failure_mode": case_spec["primary_failure_mode"],
        "traps": [_fallback_trap(case_spec, item) for item in case_spec["selected_failure_modes"]],
    }


def audit_and_repair_memory_failure_blueprint(payload: dict[str, Any], case_spec: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["case_id"] = case_spec["case_id"]
    normalized["task_id"] = case_spec["task_id"]
    normalized["comparison_target"] = case_spec["comparison_target"]
    normalized["selected_failure_modes"] = list(case_spec["selected_failure_modes"])
    normalized["primary_failure_mode"] = case_spec["primary_failure_mode"]
    traps = list(normalized.get("traps") or [])
    trap_map = {str(item.get("failure_mode") or "").strip(): item for item in traps if isinstance(item, dict)}
    for failure_mode in case_spec["selected_failure_modes"]:
        if failure_mode not in trap_map:
            traps.append(_fallback_trap(case_spec, failure_mode))
    normalized["traps"] = traps
    validated = validate_memory_failure_blueprint(normalized)
    settings = load_builder_settings()
    minimum_probe_queries = int(settings["v3_blueprint"]["min_probe_queries_per_trap"])
    for trap in validated["traps"]:
        if len(trap["common"]["probe_queries"]) < minimum_probe_queries:
            raise ValueError(f"trap {trap['trap_id']} is missing probe queries")
        if not trap["common"]["metric_targets"]:
            raise ValueError(f"trap {trap['trap_id']} is missing metric_targets")
    return validated


def generate_memory_failure_blueprint_with_mode(
    case_spec: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> tuple[dict[str, Any], str]:
    validated_spec = validate_case_spec(case_spec)
    blueprint = request_blueprint_json(validated_spec, llm_client=llm_client)
    audited = audit_and_repair_memory_failure_blueprint(blueprint, validated_spec)
    return audited, "llm" if llm_client is not None and blueprint.get("traps") != [_fallback_trap(validated_spec, item) for item in validated_spec["selected_failure_modes"]] else "fallback"


def generate_memory_failure_blueprint(case_spec: dict[str, Any], *, llm_client: Any | None = None) -> dict[str, Any]:
    payload, _mode = generate_memory_failure_blueprint_with_mode(case_spec, llm_client=llm_client)
    return payload
