from __future__ import annotations

from typing import Any

from .schemas import (
    ValidationError,
    validate_block_annotations,
    validate_collected_messages_v3,
    validate_event_annotations,
    validate_query_benchmark,
)


def validate_gold_against_observed_data(
    *,
    collected_messages: list[dict[str, Any]],
    event_annotations: list[dict[str, Any]],
    block_annotations: dict[str, Any],
    query_benchmark: dict[str, Any],
) -> dict[str, Any]:
    messages = validate_collected_messages_v3(collected_messages)
    events = validate_event_annotations(event_annotations)
    blocks = validate_block_annotations(block_annotations)
    queries = validate_query_benchmark(query_benchmark)

    message_by_id = {row["message_id"]: row for row in messages}
    event_by_id = {row["annotation_id"]: row for row in events}
    errors: list[str] = []

    for annotation in events:
        message = message_by_id.get(annotation["evidence_message_id"])
        if message is None:
            errors.append(f"missing evidence_message_id: {annotation['annotation_id']} -> {annotation['evidence_message_id']}")
            continue
        if annotation["evidence_quote"] not in message["content_text"]:
            errors.append(f"evidence_quote mismatch: {annotation['annotation_id']} -> {annotation['evidence_message_id']}")

    for block in blocks["blocks"]:
        for annotation_id in block["gold_event_annotation_ids"]:
            if annotation_id not in event_by_id:
                errors.append(f"block references missing annotation: {block['block_annotation_id']} -> {annotation_id}")
        for state in block["current_state"]:
            for annotation_id in [*state["supporting_event_annotation_ids"], *state["stale_event_annotation_ids"]]:
                if annotation_id not in event_by_id:
                    errors.append(f"current_state references missing annotation: {block['block_annotation_id']} -> {annotation_id}")

    for query in queries["queries"]:
        for annotation_id in query["required_event_annotation_ids"]:
            if annotation_id not in event_by_id:
                errors.append(f"query references missing annotation: {query['query_id']} -> {annotation_id}")
        for message_id in query["citation_expectation"]["must_cite_message_ids"]:
            if message_id not in message_by_id:
                errors.append(f"query requires missing message id: {query['query_id']} -> {message_id}")

    report = {
        "case_id": blocks["case_id"],
        "status": "pass" if not errors else "fail",
        "error_count": len(errors),
        "errors": errors,
    }
    if errors:
        raise ValidationError("\n".join(errors))
    return report
