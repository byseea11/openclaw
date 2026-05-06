from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .eval_common import normalize_text
from .io_utils import ensure_dir, read_jsonl, write_json
from .schemas import validate_collected_messages_v3, validate_query_benchmark


def _materialize_openclaw_memory_workspace(
    *,
    workspace_dir: Path,
    collected_messages: list[dict[str, Any]],
) -> dict[str, list[str]]:
    ensure_dir(workspace_dir / "memory")
    line_index: dict[str, list[str]] = {}
    memory_md_lines = ["# Durable Memory", ""]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in collected_messages:
        grouped.setdefault(row["session_id"], []).append(row)
    for session_index, (session_id, rows) in enumerate(sorted(grouped.items()), start=1):
        relpath = f"memory/2026-05-06-session-{session_index:02d}.md"
        file_lines = [f"# Session {session_id}", ""]
        message_ids: list[str] = []
        for row in sorted(rows, key=lambda item: item["sequence_no"]):
            message_ids.append(row["message_id"])
            file_lines.append(f"- [{row['message_id']}] {row['content_text']}")
        (workspace_dir / relpath).write_text("\n".join(file_lines) + "\n", encoding="utf-8")
        line_map: list[str] = []
        for line in file_lines:
            if line.startswith("- [") and "] " in line:
                line_map.append(line.split("[", 1)[1].split("]", 1)[0])
            else:
                line_map.append("")
        line_index[relpath] = line_map
        memory_md_lines.append(f"- {session_id}: {rows[0]['topic_key']} / {rows[-1]['content_text']}")
    (workspace_dir / "MEMORY.md").write_text("\n".join(memory_md_lines) + "\n", encoding="utf-8")
    line_index["MEMORY.md"] = [""] * len(memory_md_lines)
    write_json(workspace_dir / "benchmark_line_index.json", line_index)
    return line_index


def _map_memory_hits_to_message_ids(line_index: dict[str, list[str]], result: dict[str, Any]) -> list[str]:
    relpath = normalize_text(result.get("path"))
    entries = line_index.get(relpath) or []
    start = max(1, int(result.get("startLine") or 1))
    end = max(start, int(result.get("endLine") or start))
    message_ids = []
    for line_no in range(start, min(len(entries), end) + 1):
        value = normalize_text(entries[line_no - 1])
        if value and value not in message_ids:
            message_ids.append(value)
    return message_ids


def _fallback_memory_search(workspace_dir: Path, query_text: str, line_index: dict[str, list[str]]) -> dict[str, Any]:
    query_tokens = set(normalize_text(query_text).split())
    results = []
    reads = []
    for relpath, line_map in line_index.items():
        file_path = workspace_dir / relpath
        if not file_path.exists():
            continue
        lines = file_path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            normalized = normalize_text(line)
            if not normalized:
                continue
            overlap = len(query_tokens & set(normalized.split()))
            if overlap <= 0 and query_text not in normalized:
                continue
            results.append(
                {
                    "path": relpath,
                    "startLine": idx,
                    "endLine": idx,
                    "score": float(max(overlap, 1)),
                    "snippet": normalized,
                }
            )
            reads.append({"path": relpath, "text": normalized})
    results.sort(key=lambda item: (-item["score"], item["path"], item["startLine"]))
    return {"results": results[:5], "reads": reads[:3], "backend": "materialized_memory_fallback"}


def run_memory_md_baseline(
    *,
    case_dir: str | Path,
    collected_messages: list[dict[str, Any]] | None = None,
    query_benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(case_dir)
    messages = validate_collected_messages_v3(collected_messages or read_jsonl(root / "data" / "collected_messages.jsonl"))
    benchmark = validate_query_benchmark(query_benchmark or json.loads((root / "gold" / "query_benchmark.json").read_text(encoding="utf-8")))
    workspace_dir = root / "baselines" / "openclaw_memory_md" / "workspace"
    line_index = _materialize_openclaw_memory_workspace(workspace_dir=workspace_dir, collected_messages=messages)
    wrapper = Path(__file__).resolve().parent / "query_memory_core_v3.ts"

    query_reports = []
    runner_backend = "openclaw_real"
    runner_attempt = "memory_core_query"
    fallback_reason: str | None = None
    use_fallback_only = False
    for query in benchmark["queries"]:
        payload = json.dumps({"workspaceDir": str(workspace_dir), "query": query["query_text"], "maxResults": 5}, ensure_ascii=False)
        if use_fallback_only:
            response = _fallback_memory_search(workspace_dir, query["query_text"], line_index)
            runner_backend = response.get("backend") or "materialized_memory_fallback"
        else:
            try:
                completed = subprocess.run(
                    ["node", "--import", "tsx/esm", str(wrapper), payload],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
                response = json.loads(completed.stdout.strip() or "{}")
            except Exception as exc:
                use_fallback_only = True
                fallback_reason = str(exc) or exc.__class__.__name__
                response = _fallback_memory_search(workspace_dir, query["query_text"], line_index)
                runner_backend = response.get("backend") or "materialized_memory_fallback"
        results = response.get("results") or []
        reads = response.get("reads") or []
        citations = []
        message_ids = []
        for hit in results:
            citations.append(f"{hit.get('path')}:{hit.get('startLine')}-{hit.get('endLine')}")
            message_ids.extend(_map_memory_hits_to_message_ids(line_index, hit))
        answer_text = "；".join(normalize_text(item.get("text")) for item in reads if normalize_text(item.get("text")))
        query_reports.append(
            {
                "query_id": query["query_id"],
                "answer_text": answer_text or "未从 OpenClaw memory corpus 检索到稳定答案。",
                "citations": citations,
                "traceability_message_ids": sorted(set(message_ids)),
                "used_memory_sections": sorted({normalize_text(hit.get("path")) for hit in results if normalize_text(hit.get("path"))}),
            }
        )
    report = {
        "case_id": benchmark["case_id"],
        "baseline_mode": "openclaw_real",
        "runner_attempt": runner_attempt,
        "runner_backend": runner_backend,
        "fallback_reason": fallback_reason,
        "workspace_dir": str(workspace_dir),
        "queries": query_reports,
    }
    write_json(root / "reports" / "memory_md_baseline_report.json", report)
    return report
