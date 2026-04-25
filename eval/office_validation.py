"""Read-only validation replay for frozen office snapshots."""

from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import mean
from typing import Any

from eval.office_dataset import load_snapshot_bundle
from eval.openclaw_client import OpenClawEvalClient, OpenClawEvalResponse
from eval.scorers.common import answer_f1, dump_json, dump_jsonl, exact_match


def _usage_prompt_tokens(response: OpenClawEvalResponse) -> int:
    usage = response.usage or {}
    for key in ("input_tokens", "prompt_tokens", "total_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


def _result_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "matches", "hits", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    nested = payload.get("details")
    if isinstance(nested, dict):
        return _result_items(nested)
    return []


def _candidate_text(item: dict[str, Any]) -> str:
    for key in ("snippet", "text", "content", "summary", "body"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_probe_results(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _result_items(payload):
        snippet = _candidate_text(item)
        if not snippet and not str(item.get("path") or item.get("source") or "").strip():
            continue
        rows.append(
            {
                "path": str(item.get("path") or item.get("source") or "").strip(),
                "startLine": item.get("startLine") or item.get("start_line"),
                "endLine": item.get("endLine") or item.get("end_line"),
                "snippet": snippet,
                "corpus": str(item.get("corpus") or "memory").strip() or "memory",
                "graphMeta": item.get("graphMeta") if isinstance(item.get("graphMeta"), dict) else item.get("graph_meta"),
            }
        )
    return rows


def _parse_retrieval_probe(response: OpenClawEvalResponse) -> dict[str, Any]:
    for tool_output in response.tool_outputs:
        if tool_output.name != "memory_search":
            continue
        results = _normalize_probe_results(tool_output.output)
        if results or (
            isinstance(tool_output.output, dict) and isinstance(tool_output.output.get("results"), list)
        ):
            return {"status": "ok", "results": results, "source": "tool_output"}

    if response.text.strip():
        try:
            payload = json.loads(response.text.strip())
        except json.JSONDecodeError:
            payload = None
        results = _normalize_probe_results(payload)
        if results or (isinstance(payload, dict) and isinstance(payload.get("results"), list)):
            return {"status": "ok", "results": results, "source": "assistant_json"}

    return {
        "status": "missing_tool_output",
        "results": [],
        "source": None,
        "error": "probe response did not contain parseable memory_search results",
    }


def _event_ids_from_results(results: list[dict[str, Any]]) -> list[str]:
    event_ids: list[str] = []
    for item in results:
        snippet = str(item.get("snippet") or "")
        for token in snippet.split():
            if token.startswith("[event_id:"):
                candidate = token[len("[event_id:") :].rstrip("]")
                if candidate:
                    event_ids.append(candidate)
    return event_ids


def _evidence_recall(results: list[dict[str, Any]], evidence_event_ids: list[str], *, k: int) -> float:
    gold = {value for value in evidence_event_ids if value}
    if not gold:
        return 1.0
    predicted = set(_event_ids_from_results(results[: max(0, k)]))
    if not predicted:
        return 0.0
    return len(gold & predicted) / len(gold)


def _graph_hit_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    hits = 0
    for item in results:
        graph_meta = item.get("graphMeta")
        corpus = str(item.get("corpus") or "")
        if isinstance(graph_meta, dict) or corpus == "graph":
            hits += 1
    return hits / len(results)


def resolve_history_events(events: list[dict[str, Any]], history_window: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_ids = {value for value in history_window.get("event_ids", []) if value}
    if explicit_ids:
        selected = [event for event in events if str(event.get("event_id") or "") in explicit_ids]
    else:
        selected = list(events)
        start_event_id = str(history_window.get("start_event_id") or "").strip()
        end_event_id = str(history_window.get("end_event_id") or "").strip()
        start_time = str(history_window.get("start_time") or "").strip()
        end_time = str(history_window.get("end_time") or "").strip()
        chat_ids = {value for value in history_window.get("chat_ids", []) if value}
        thread_ids = {value for value in history_window.get("thread_ids", []) if value}

        if start_event_id:
            start_index = next(
                (idx for idx, event in enumerate(selected) if str(event.get("event_id") or "") == start_event_id),
                None,
            )
            if start_index is not None:
                selected = selected[start_index:]
        if end_event_id:
            end_index = next(
                (idx for idx, event in enumerate(selected) if str(event.get("event_id") or "") == end_event_id),
                None,
            )
            if end_index is not None:
                selected = selected[: end_index + 1]
        if start_time:
            selected = [event for event in selected if str(event.get("event_time") or "") >= start_time]
        if end_time:
            selected = [event for event in selected if str(event.get("event_time") or "") <= end_time]
        if chat_ids:
            selected = [event for event in selected if str(event.get("chat_id") or "") in chat_ids]
        if thread_ids:
            selected = [event for event in selected if str(event.get("thread_id") or "") in thread_ids]

    max_events = int(history_window.get("max_events") or 0)
    if max_events > 0:
        selected = selected[-max_events:]
    return selected


def build_event_input(event: dict[str, Any]) -> dict[str, Any]:
    sender_name = str(event.get("sender_name") or event.get("sender_open_id") or "Unknown")
    chat_id = str(event.get("chat_id") or "").strip()
    thread_id = str(event.get("thread_id") or "").strip()
    event_time = str(event.get("event_time") or "").strip()
    message_type = str(event.get("message_type") or "text")
    content = str(event.get("content_text") or "").strip()
    prefix = [
        f"[event_id: {event.get('event_id')}]",
        f"[event_time: {event_time}]",
    ]
    if chat_id:
        prefix.append(f"[chat_id: {chat_id}]")
    if thread_id:
        prefix.append(f"[thread_id: {thread_id}]")
    prefix.append(f"[message_type: {message_type}]")
    body = f"{sender_name}: {content}".strip()
    return {
        "type": "message",
        "role": "user",
        "content": "\n".join([*prefix, body]),
    }


def run_validation_variant(
    *,
    client: Any,
    root_dir: str,
    snapshot_id: str,
    output_dir: str | Path,
    variant_name: str,
    agent: str = "main",
    message_channel: str = "feishu",
    timeout_seconds: float | None = None,
    inter_step_delay_ms: float = 0.0,
    detach_query_context: bool = False,
) -> dict[str, Any]:
    del agent, timeout_seconds
    bundle = load_snapshot_bundle(root_dir, snapshot_id)
    events = bundle["events"]
    manifest = bundle["validation_manifest"]
    cases = manifest.get("cases", [])
    rows: list[dict[str, Any]] = []

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for case in cases:
        case_id = str(case.get("case_id") or "")
        history_events = resolve_history_events(events, dict(case.get("history_window") or {}))
        session_key = f"eval:office_validation:{snapshot_id}:{variant_name}:{case_id}"
        previous_response_id: str | None = None

        for event in history_events:
            history_response = client.send(
                session_key=session_key,
                message_channel=message_channel,
                input_items=[build_event_input(event)],
                instructions=(
                    "Treat this as historical office context only. Do not answer the user yet."
                ),
                previous_response_id=previous_response_id,
            )
            previous_response_id = history_response.response_id
            if inter_step_delay_ms > 0:
                time.sleep(inter_step_delay_ms / 1000)

        probe_previous_id = None if detach_query_context else previous_response_id
        probe_response = client.send(
            session_key=session_key,
            message_channel=message_channel,
            input_items=[
                {
                    "type": "message",
                    "role": "user",
                    "content": str(case.get("question") or ""),
                }
            ],
            instructions=(
                "Use the memory_search tool exactly once with the user's question. "
                "After retrieval, respond with JSON only and no commentary. "
                'Return {"results":[{"path":"","startLine":1,"endLine":1,"snippet":"","corpus":"memory","graphMeta":null}]}. '
                'If nothing relevant is found, return {"results":[]}.'
            ),
            tools=[{"type": "function", "name": "memory_search"}],
            previous_response_id=probe_previous_id,
        )
        probe = _parse_retrieval_probe(probe_response)
        retrieval_results = list(probe.get("results", []))

        answer_previous_id = None if detach_query_context else previous_response_id
        answer_response = client.send(
            session_key=session_key,
            message_channel=message_channel,
            input_items=[
                {
                    "type": "message",
                    "role": "user",
                    "content": str(case.get("question") or ""),
                }
            ],
            instructions=(
                "Answer using the historical office context. "
                "Be concise and only state what is supported by the snapshot."
            ),
            previous_response_id=answer_previous_id,
        )
        expected_answer = str(case.get("expected_answer") or "")
        evidence_event_ids = [str(item) for item in case.get("evidence_event_ids", [])]
        row = {
            "snapshot_id": snapshot_id,
            "variant": variant_name,
            "case_id": case_id,
            "ability_tag": str(case.get("ability_tag") or ""),
            "question": str(case.get("question") or ""),
            "expected_answer": expected_answer,
            "predicted_answer": answer_response.text,
            "evidence_event_ids": evidence_event_ids,
            "history_event_ids": [str(event.get("event_id") or "") for event in history_events],
            "history_event_count": len(history_events),
            "retrieval_probe_status": probe.get("status"),
            "retrieval_results": retrieval_results,
            "graph_hit_rate": round(_graph_hit_rate(retrieval_results), 4),
            "recall_at_5": round(_evidence_recall(retrieval_results, evidence_event_ids, k=5), 4),
            "recall_at_10": round(_evidence_recall(retrieval_results, evidence_event_ids, k=10), 4),
            "latency_ms": answer_response.latency_ms or 0.0,
            "prompt_tokens": _usage_prompt_tokens(answer_response),
            "exact_match": exact_match(answer_response.text, expected_answer),
            "f1": answer_f1(answer_response.text, expected_answer),
        }
        rows.append(row)

    jsonl_path = output_path / f"{variant_name}.jsonl"
    summary_path = output_path / f"{variant_name}.summary.json"
    details_path = output_path / f"{variant_name}.details.json"
    dump_jsonl(rows, jsonl_path)
    dump_json(rows, details_path)

    summary = {
        "snapshot_id": snapshot_id,
        "variant": variant_name,
        "case_count": len(rows),
        "exact_match": round(mean(float(row["exact_match"]) for row in rows), 4) if rows else 0.0,
        "average_f1": round(mean(float(row["f1"]) for row in rows), 4) if rows else 0.0,
        "average_recall_at_5": round(mean(float(row["recall_at_5"]) for row in rows), 4) if rows else 0.0,
        "average_recall_at_10": round(mean(float(row["recall_at_10"]) for row in rows), 4) if rows else 0.0,
        "average_graph_hit_rate": round(mean(float(row["graph_hit_rate"]) for row in rows), 4)
        if rows
        else 0.0,
        "average_latency_ms": round(mean(float(row["latency_ms"]) for row in rows), 3) if rows else 0.0,
        "average_prompt_tokens": round(mean(float(row["prompt_tokens"]) for row in rows), 1)
        if rows
        else 0.0,
        "output": {
            "jsonl": str(jsonl_path),
            "details": str(details_path),
        },
    }
    dump_json(summary, summary_path)
    return summary
