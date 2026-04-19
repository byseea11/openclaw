"""Graph-index usage extraction for OpenClaw eval runs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from eval.openclaw_client import OpenClawEvalResponse


GRAPH_STATE_MARKER = "[Graph state]"
GRAPH_EVENT_MARKER = "[Graph event]"


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def summarize_response_graph_usage(response: OpenClawEvalResponse) -> dict[str, Any]:
    """Return lightweight graph-usage signals visible in one OpenResponses payload."""

    payload_text = _json_text(response.raw_payload)
    tool_names = [tool.name for tool in response.tool_calls]
    graph_state_hits = payload_text.count(GRAPH_STATE_MARKER)
    graph_event_hits = payload_text.count(GRAPH_EVENT_MARKER)
    memory_search_calls = sum(1 for name in tool_names if name == "memory_search")
    memory_get_calls = sum(1 for name in tool_names if name == "memory_get")
    return {
        "used_graph": graph_state_hits > 0 or graph_event_hits > 0,
        "memory_search_calls": memory_search_calls,
        "memory_get_calls": memory_get_calls,
        "graph_state_hits": graph_state_hits,
        "graph_event_hits": graph_event_hits,
        "graph_hit_markers": graph_state_hits + graph_event_hits,
        "tool_calls": tool_names,
    }


def summarize_rows_graph_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "used_graph_count": 0,
            "graph_hit_rate": 0.0,
            "memory_search_calls": 0,
            "memory_get_calls": 0,
            "graph_state_hits": 0,
            "graph_event_hits": 0,
        }
    used_graph_count = 0
    totals = Counter()
    for row in rows:
        usage = row.get("graph_usage")
        if not isinstance(usage, dict):
            continue
        if usage.get("used_graph"):
            used_graph_count += 1
        for key in ("memory_search_calls", "memory_get_calls", "graph_state_hits", "graph_event_hits"):
            totals[key] += int(usage.get(key) or 0)
    return {
        "sample_count": len(rows),
        "used_graph_count": used_graph_count,
        "graph_hit_rate": round(used_graph_count / len(rows), 4),
        "memory_search_calls": totals["memory_search_calls"],
        "memory_get_calls": totals["memory_get_calls"],
        "graph_state_hits": totals["graph_state_hits"],
        "graph_event_hits": totals["graph_event_hits"],
    }


def summarize_trace_file(trace_path: str | Path | None, session_keys: set[str]) -> dict[str, Any]:
    """Summarize GRAPH_INDEX_IMPL JSONL events for the eval sessions we created."""

    if not trace_path:
        return {"available": False, "reason": "trace_path_not_configured"}
    path = Path(trace_path).expanduser()
    if not path.exists():
        return {"available": False, "reason": "trace_file_missing", "path": str(path)}

    stage_counts: Counter[str] = Counter()
    per_session: dict[str, Counter[str]] = defaultdict(Counter)
    graph_hits = 0
    graph_rendered_hits = 0
    extractor_events = 0
    malformed = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if event.get("tag") != "GRAPH_INDEX_IMPL":
            continue
        source_id = event.get("source_id")
        if session_keys and source_id not in session_keys:
            continue
        stage = str(event.get("stage") or "unknown")
        stage_counts[stage] += 1
        if isinstance(source_id, str):
            per_session[source_id][stage] += 1
        search = event.get("search") if isinstance(event.get("search"), dict) else {}
        extract = event.get("extract") if isinstance(event.get("extract"), dict) else {}
        graph_hits += int(search.get("hits") or 0)
        graph_rendered_hits += int(search.get("rendered") or 0)
        extractor_events += int(extract.get("events") or 0)

    return {
        "available": True,
        "path": str(path),
        "stage_counts": dict(stage_counts),
        "session_count": len(per_session),
        "graph_hits": graph_hits,
        "graph_rendered_hits": graph_rendered_hits,
        "extractor_events": extractor_events,
        "malformed_lines": malformed,
    }

