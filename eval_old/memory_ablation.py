"""Shared memory-benchmark runner for native-vs-graph OpenClaw evals."""

from __future__ import annotations

from pathlib import Path
from statistics import mean
from time import sleep
from typing import Any

from eval_old.base import BenchmarkScorer, MemAdapter
from eval_old.graph_usage import (
    summarize_response_graph_usage,
    summarize_rows_graph_usage,
    summarize_trace_file,
)
from eval_old.openclaw_client import OpenClawEvalClient
from eval_old.scorers.common import dump_json
from eval_old.variants import EvalVariant


def _row_bucket(row: dict[str, Any]) -> str:
    if row.get("question_type"):
        return f"question_type:{row.get('question_type')}"
    if row.get("category") is not None:
        return f"category:{row.get('category')}"
    metadata = row.get("query_metadata")
    if isinstance(metadata, dict):
        if metadata.get("question_type"):
            return f"question_type:{metadata.get('question_type')}"
        if metadata.get("category") is not None:
            return f"category:{metadata.get('category')}"
    return "all"


def summarize_buckets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_row_bucket(row), []).append(row)
    summary: dict[str, Any] = {}
    for bucket, bucket_rows in sorted(buckets.items()):
        numeric_keys = [
            key
            for key in ("exact_match", "f1", "abstention_correct", "latency_ms")
            if any(isinstance(row.get(key), (int, float)) for row in bucket_rows)
        ]
        summary[bucket] = {
            "sample_count": len(bucket_rows),
            **{
                f"average_{key}": round(
                    mean(float(row.get(key) or 0.0) for row in bucket_rows),
                    4 if key != "latency_ms" else 3,
                )
                for key in numeric_keys
            },
            "graph_usage": summarize_rows_graph_usage(bucket_rows),
        }
    return summary


def run_memory_variant(
    *,
    adapter: MemAdapter,
    scorer: BenchmarkScorer,
    samples: list[Any],
    variant: EvalVariant,
    output_path: str | Path,
    timeout_seconds: float,
    inter_step_delay_ms: float = 0.0,
    detach_query_context: bool = False,
) -> dict[str, Any]:
    client = OpenClawEvalClient(
        variant.gateway_url,
        agent=variant.agent,
        token=variant.gateway_token,
        model_override=variant.model_override,
        timeout_seconds=timeout_seconds,
    )

    outputs: list[dict[str, Any]] = []
    session_keys: set[str] = set()
    for sample in samples:
        sample_id = adapter.make_sample_id(sample)
        session_key = f"eval-{variant.name}-{adapter.benchmark_name}-{sample_id}"
        session_keys.add(session_key)
        previous_response_id = None
        history_latencies_ms: list[float] = []

        for step in adapter.build_history_inputs(sample):
            history_response = client.send(
                session_key=session_key,
                message_channel=adapter.message_channel,
                input_items=step.input_items,
                instructions=step.instructions,
                tools=step.tools,
                previous_response_id=previous_response_id,
            )
            previous_response_id = history_response.response_id
            if history_response.latency_ms is not None:
                history_latencies_ms.append(history_response.latency_ms)
            if inter_step_delay_ms > 0:
                # Graph projection observers run after a turn completes; eval can
                # otherwise issue the recall query before the observer has flushed.
                sleep(inter_step_delay_ms / 1000)

        query_step = adapter.build_query_input(sample)
        response = client.send(
            session_key=session_key,
            message_channel=adapter.message_channel,
            input_items=query_step.input_items,
            instructions=query_step.instructions,
            tools=query_step.tools,
            previous_response_id=None if detach_query_context else previous_response_id,
        )
        row = adapter.parse_prediction(sample, response)
        row.update(
            {
                "variant": variant.name,
                "session_key": session_key,
                "history_steps": len(history_latencies_ms),
                "history_latency_ms": round(sum(history_latencies_ms), 3),
                "query_metadata": dict(query_step.metadata),
                "graph_usage": summarize_response_graph_usage(response),
            }
        )
        outputs.append(row)

    summary = scorer.score(outputs)
    graph_summary = summarize_rows_graph_usage(outputs)
    trace_summary = summarize_trace_file(variant.trace_path, session_keys)
    summary = {
        **summary,
        "variant": variant.name,
        "graph_usage": graph_summary,
        "graph_trace": trace_summary,
        "buckets": summarize_buckets(outputs),
    }
    scorer.save_outputs(outputs, output_path)
    dump_json(summary, Path(output_path).with_suffix(".summary.json"))
    return {
        "summary": summary,
        "rows": outputs,
        "output": str(output_path),
    }
