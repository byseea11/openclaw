"""Variant definitions for native-vs-graph OpenClaw eval experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvalVariant:
    """One OpenClaw deployment/configuration under test."""

    name: str
    gateway_url: str
    agent: str = "main"
    gateway_token: str | None = None
    model_override: str | None = None
    trace_path: str | None = None


def numeric_metric_deltas(native: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Compare numeric metrics that appear in both summaries."""

    deltas: dict[str, Any] = {}
    for key, native_value in native.items():
        graph_value = graph.get(key)
        if isinstance(native_value, bool) or isinstance(graph_value, bool):
            continue
        if isinstance(native_value, (int, float)) and isinstance(graph_value, (int, float)):
            deltas[key] = {
                "native": native_value,
                "graph": graph_value,
                "delta": round(float(graph_value) - float(native_value), 6),
            }
    return deltas


def build_comparison(
    *,
    benchmark: str,
    native_summary: dict[str, Any],
    graph_summary: dict[str, Any],
    native_output: str,
    graph_output: str,
) -> dict[str, Any]:
    return {
        "benchmark": benchmark,
        "variants": {
            "native": {
                "summary": native_summary,
                "output": native_output,
            },
            "graph": {
                "summary": graph_summary,
                "output": graph_output,
            },
        },
        "metric_deltas": numeric_metric_deltas(native_summary, graph_summary),
        "bucket_metric_deltas": bucket_metric_deltas(native_summary, graph_summary),
    }


def bucket_metric_deltas(native: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    native_buckets = native.get("buckets")
    graph_buckets = graph.get("buckets")
    if not isinstance(native_buckets, dict) or not isinstance(graph_buckets, dict):
        return {}
    deltas: dict[str, Any] = {}
    for bucket in sorted(set(native_buckets) | set(graph_buckets)):
        native_bucket = native_buckets.get(bucket)
        graph_bucket = graph_buckets.get(bucket)
        if not isinstance(native_bucket, dict) or not isinstance(graph_bucket, dict):
            continue
        bucket_deltas = numeric_metric_deltas(native_bucket, graph_bucket)
        if bucket_deltas:
            deltas[bucket] = bucket_deltas
    return deltas
