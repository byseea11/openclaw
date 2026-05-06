from __future__ import annotations

from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .schemas import validate_overall_eval


def build_reports(case_dir: str | Path) -> dict[str, Any]:
    root = Path(case_dir)
    event_alignment = read_json(root / "reports" / "event_alignment.json")
    event_eval = read_json(root / "reports" / "event_eval.json")
    block_eval = read_json(root / "reports" / "block_eval.json")
    qa_eval = read_json(root / "reports" / "qa_eval.json")
    value_eval = read_json(root / "reports" / "value_eval.json")
    overall = validate_overall_eval(
        {
            "case_id": event_eval["case_id"],
            "remembered_assessment": {
                "event": event_eval["overall"],
                "block": block_eval["overall"],
                "qa": qa_eval["overall"],
            },
            "value_assessment": value_eval["overall"],
            "artifacts": {
                "event_alignment": "reports/event_alignment.json",
                "event_eval": "reports/event_eval.json",
                "block_eval": "reports/block_eval.json",
                "qa_eval": "reports/qa_eval.json",
                "value_eval": "reports/value_eval.json",
            },
        }
    )
    final_report = {
        "case_id": overall["case_id"],
        "remembered": overall["remembered_assessment"],
        "valuable": overall["value_assessment"],
        "summary": {
            "remembered_definition": "本系统对“记住了”的定义不是生成一段摘要，而是形成可验证、可追溯、可更新、可检索的任务记忆。",
            "value_definition": "本系统对“产生效能”的定义不是主观感觉，而是相对于无记忆和普通 RAG baseline，在回答准确率、引用成功率、stale current-state 率和污染率上取得可量化提升。",
        },
    }
    write_json(root / "reports" / "overall_eval.json", overall)
    write_json(root / "reports" / "final_benchmark_report.json", final_report)
    return {
        "event_alignment": event_alignment,
        "event_eval": event_eval,
        "block_eval": block_eval,
        "qa_eval": qa_eval,
        "value_eval": value_eval,
        "overall_eval": overall,
        "final_benchmark_report": final_report,
    }
