from __future__ import annotations

from pathlib import Path
from typing import Any

from .eval_common import build_raw_rag_answer
from .io_utils import read_json, read_jsonl, write_json
from .schemas import validate_collected_messages_v3, validate_query_benchmark


def run_raw_message_rag(
    *,
    case_dir: str | Path,
    collected_messages: list[dict[str, Any]] | None = None,
    query_benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(case_dir)
    messages = validate_collected_messages_v3(collected_messages or read_jsonl(root / "data" / "collected_messages.jsonl"))
    benchmark = validate_query_benchmark(query_benchmark or read_json(root / "gold" / "query_benchmark.json"))
    query_reports = []
    for query in benchmark["queries"]:
        answer = build_raw_rag_answer(messages, query)
        query_reports.append(
            {
                "query_id": query["query_id"],
                "answer_text": answer["answer_text"],
                "citations": answer["citations"],
                "retrieved_messages": answer["retrieved_messages"],
            }
        )
    report = {
        "case_id": benchmark["case_id"],
        "baseline_mode": "raw_message_rag",
        "queries": query_reports,
    }
    write_json(root / "reports" / "raw_message_rag_report.json", report)
    return report
