from __future__ import annotations

from typing import Any

from ..llm import (
    BuilderModelClient,
    ModelBackendError,
    ModelPayloadValidationError,
    build_model_call_log_entry,
    create_model_client,
)
from ..prompt_loader import build_stage_system_prompt


class SemanticGoldValidationError(ValueError):
    """Raised when semantic gold cannot be grounded in observed message ids."""

    def __init__(self, message: str, *, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self.warnings = warnings or []


def build_rule_semantic_gold(
    *,
    case_context: dict[str, Any],
    story_plan: dict[str, Any],
    annotation_gold_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    supporting_ids = [str(row["message_id"]) for row in annotation_gold_rows]
    return {
        "case_id": str(case_context["case_id"]),
        "family_id": str(case_context["family_id"]),
        "task_id": str(case_context["task_id"]),
        "mode": "rule",
        "expected_task_facts": [
            {
                "fact_id": f"fact_{index:03d}",
                "claim": str(row["evidence_text"]),
                "required_supporting_message_ids": [str(row["message_id"])],
            }
            for index, row in enumerate(annotation_gold_rows, start=1)
        ],
        "expected_event_semantics": [
            {
                "event_semantic_id": f"event_semantic_{index:03d}",
                "purpose": str(row.get("purpose") or "observed_event"),
                "turn_kind": str(row.get("turn_kind") or ""),
                "required_supporting_message_ids": [str(row["message_id"])],
            }
            for index, row in enumerate(annotation_gold_rows, start=1)
        ],
        "expected_query_answers": [
            {
                "query_id": f"{case_context['case_id']}_semantic_query_{index:03d}",
                "query": str(probe["query"]),
                "expected_answer_summary": str(probe["expected_good_behavior"]),
                "required_supporting_message_ids": supporting_ids,
            }
            for index, probe in enumerate(story_plan["planned_probe_queries"], start=1)
        ],
    }


def _normalize_semantic_gold(
    *,
    payload: dict[str, Any],
    case_context: dict[str, Any],
    allowed_message_ids: set[str],
    citation_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    citation_aliases = citation_aliases or {}
    warnings: list[str] = []
    normalized = {
        "case_id": str(case_context["case_id"]),
        "family_id": str(case_context["family_id"]),
        "task_id": str(case_context["task_id"]),
        "mode": "llm",
        "expected_task_facts": [],
        "expected_event_semantics": [],
        "expected_query_answers": [],
    }
    for key in ("expected_task_facts", "expected_event_semantics", "expected_query_answers"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            warnings.append(f"{key} missing_or_not_list")
            continue
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                warnings.append(f"{key}[{index}] not_object")
                continue
            item = dict(row)
            ids = _resolve_supporting_message_ids(
                item=item,
                allowed_message_ids=allowed_message_ids,
                citation_aliases=citation_aliases,
            )
            if not ids:
                warnings.append(f"{key}[{index}] missing_observed_message_id")
                continue
            item["required_supporting_message_ids"] = ids
            item.setdefault(f"{key[:-1]}_id", f"{key}_{index:03d}")
            normalized[key].append(item)
    if not normalized["expected_task_facts"]:
        raise SemanticGoldValidationError(
            "semantic gold must contain at least one expected_task_fact with observed message evidence",
            warnings=warnings,
        )
    if warnings:
        normalized["validation_warnings"] = warnings
    return normalized


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    return [value]


def _resolve_supporting_message_ids(
    *,
    item: dict[str, Any],
    allowed_message_ids: set[str],
    citation_aliases: dict[str, str],
) -> list[str]:
    raw_ids: list[Any] = []
    for field in (
        "required_supporting_message_ids",
        "supporting_message_ids",
        "message_ids",
        "evidence_message_ids",
        "supporting_ids",
        "citations",
        "evidence_ids",
    ):
        raw_ids.extend(_as_list(item.get(field)))
    for field in ("annotation_id", "turn_id", "beat_id"):
        raw_ids.extend(_as_list(item.get(field)))

    resolved: list[str] = []
    seen: set[str] = set()
    for raw_id in raw_ids:
        candidate = str(raw_id).strip()
        if not candidate:
            continue
        message_id = candidate if candidate in allowed_message_ids else citation_aliases.get(candidate)
        if message_id and message_id in allowed_message_ids and message_id not in seen:
            resolved.append(message_id)
            seen.add(message_id)
    return resolved


def _build_observed_evidence_rows(annotation_gold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "message_id": str(row["message_id"]),
            "annotation_id": str(row.get("annotation_id") or ""),
            "turn_id": str(row.get("turn_id") or ""),
            "beat_id": str(row.get("beat_id") or ""),
            "evidence_text": str(row.get("evidence_text") or ""),
            "session_id": str(row.get("session_id") or ""),
            "turn_kind": str(row.get("turn_kind") or ""),
            "purpose": str(row.get("purpose") or ""),
        }
        for row in annotation_gold_rows
        if row.get("message_id")
    ]


def _build_citation_aliases(annotation_gold_rows: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for row in annotation_gold_rows:
        message_id = str(row.get("message_id") or "").strip()
        if not message_id:
            continue
        for field in ("annotation_id", "turn_id", "beat_id"):
            value = str(row.get(field) or "").strip()
            if value and value not in aliases:
                aliases[value] = message_id
    return aliases


def _build_semantic_gold_user_payload(
    *,
    case_context: dict[str, Any],
    story_plan: dict[str, Any],
    observed_evidence_rows: list[dict[str, Any]],
    repair_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowed_message_ids = [row["message_id"] for row in observed_evidence_rows]
    payload: dict[str, Any] = {
        "case_context": {
            "case_id": case_context["case_id"],
            "family_id": case_context["family_id"],
            "task_id": case_context["task_id"],
            "difficulty": case_context["difficulty"],
        },
        "observed_evidence_rows": observed_evidence_rows,
        "allowed_message_ids": allowed_message_ids,
        "planned_probe_queries": story_plan["planned_probe_queries"],
        "output_contract": {
            "artifact_name": "task_wiki_semantic_gold",
            "return_json_object_only": True,
            "top_level_fields": [
                "expected_task_facts",
                "expected_event_semantics",
                "expected_query_answers",
            ],
            "required_citation_field": "required_supporting_message_ids",
            "citation_rule": "Every required_supporting_message_ids item must be copied exactly from allowed_message_ids.",
            "forbidden_final_citation_ids": [
                "annotation_id",
                "turn_id",
                "beat_id",
            ],
            "schema_example": {
                "expected_task_facts": [
                    {
                        "fact_id": "fact_001",
                        "claim": "目标任务当前事实，用中文总结。",
                        "required_supporting_message_ids": allowed_message_ids[:1],
                    }
                ],
                "expected_event_semantics": [
                    {
                        "event_semantic_id": "event_semantic_001",
                        "purpose": "这条证据表达的事件语义。",
                        "turn_kind": "event_bearing",
                        "required_supporting_message_ids": allowed_message_ids[:1],
                    }
                ],
                "expected_query_answers": [
                    {
                        "query_id": "semantic_query_001",
                        "query": "一个需要 Task Wiki 回答的问题。",
                        "expected_answer_summary": "必须被 observed evidence 支撑的答案摘要。",
                        "required_supporting_message_ids": allowed_message_ids[:2] or allowed_message_ids[:1],
                    }
                ],
            },
        },
    }
    if repair_context is not None:
        payload["repair_context"] = repair_context
    return payload


def generate_semantic_gold(
    *,
    case_context: dict[str, Any],
    story_plan: dict[str, Any],
    collected_messages: list[dict[str, Any]],
    annotation_gold_rows: list[dict[str, Any]],
    mode: str = "auto",
    require_llm: bool = False,
    model_client: BuilderModelClient | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if mode == "off":
        return (
            {
                "case_id": str(case_context["case_id"]),
                "family_id": str(case_context["family_id"]),
                "task_id": str(case_context["task_id"]),
                "mode": "off",
                "expected_task_facts": [],
                "expected_event_semantics": [],
                "expected_query_answers": [],
            },
            [],
        )
    if mode not in {"auto", "llm", "rule"}:
        raise ValueError("semantic gold mode must be auto, llm, rule, or off")
    if mode == "rule":
        return build_rule_semantic_gold(
            case_context=case_context,
            story_plan=story_plan,
            annotation_gold_rows=annotation_gold_rows,
        ), []

    try:
        client = model_client or create_model_client()
    except ModelBackendError:
        if require_llm or mode == "llm":
            raise
        return build_rule_semantic_gold(
            case_context=case_context,
            story_plan=story_plan,
            annotation_gold_rows=annotation_gold_rows,
        ), []

    collected_message_ids = {str(row["message_id"]) for row in collected_messages if row.get("message_id")}
    observed_evidence_rows = [
        row
        for row in _build_observed_evidence_rows(annotation_gold_rows)
        if row["message_id"] in collected_message_ids
    ]
    allowed_ids = {row["message_id"] for row in observed_evidence_rows}
    citation_aliases = _build_citation_aliases(annotation_gold_rows)
    user_payload = _build_semantic_gold_user_payload(
        case_context=case_context,
        story_plan=story_plan,
        observed_evidence_rows=observed_evidence_rows,
    )
    result = client.complete_json(
        stage="semantic-gold",
        system_prompt=build_stage_system_prompt(
            "semantic-gold",
            family_id=str(case_context["family_id"]),
            difficulty=str(case_context["difficulty"]),
        ),
        user_payload=user_payload,
    )
    model_call_entries = [
        build_model_call_log_entry(
            stage="semantic-gold",
            result=result,
            case_id=str(case_context["case_id"]),
            artifact_path="gold/task_wiki_semantic_gold.json",
        )
    ]
    try:
        normalized = _normalize_semantic_gold(
            payload=result.payload,
            case_context=case_context,
            allowed_message_ids=allowed_ids,
            citation_aliases=citation_aliases,
        )
    except SemanticGoldValidationError as exc:
        repair_payload = _build_semantic_gold_user_payload(
            case_context=case_context,
            story_plan=story_plan,
            observed_evidence_rows=observed_evidence_rows,
            repair_context={
                "validation_error": str(exc),
                "validation_warnings": exc.warnings,
                "invalid_payload": result.payload,
                "repair_instruction": "Rewrite the artifact so every item cites observed message_id values copied exactly from allowed_message_ids.",
            },
        )
        repair_result = client.complete_json(
            stage="semantic-gold-repair",
            system_prompt=build_stage_system_prompt(
                "semantic-gold",
                family_id=str(case_context["family_id"]),
                difficulty=str(case_context["difficulty"]),
            ),
            user_payload=repair_payload,
        )
        model_call_entries.append(
            build_model_call_log_entry(
                stage="semantic-gold-repair",
                result=repair_result,
                case_id=str(case_context["case_id"]),
                artifact_path="gold/task_wiki_semantic_gold.json",
            )
        )
        try:
            normalized = _normalize_semantic_gold(
                payload=repair_result.payload,
                case_context=case_context,
                allowed_message_ids=allowed_ids,
                citation_aliases=citation_aliases,
            )
        except SemanticGoldValidationError as repair_exc:
            raise ModelPayloadValidationError(
                f"semantic-gold payload validation failed after repair: {repair_exc}",
                stage="semantic-gold",
                payload=repair_result.payload,
                backend=repair_result.backend,
                model=repair_result.model,
                base_url=repair_result.base_url,
                duration_ms=repair_result.duration_ms,
            ) from repair_exc
    return normalized, model_call_entries
