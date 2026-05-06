from __future__ import annotations

from typing import Any


def build_benchmark_report(
    *,
    case_spec: dict[str, Any],
    capability_brief: dict[str, Any],
    replay_eval: dict[str, Any],
    baseline_eval: dict[str, Any],
    value_eval: dict[str, Any],
) -> str:
    lines = [
        f"# {case_spec['case_id']} Benchmark Report",
        "",
        "## Case Summary",
        f"- family_id: `{case_spec['family_id']}`",
        f"- task_id: `{case_spec['task_id']}`",
        f"- difficulty: `{case_spec['difficulty']}`",
        "",
        "## Project Requirement Mapping",
        f"- report_display_name: {capability_brief['report_display_name']}",
        f"- benchmark_requirement_name: {capability_brief['benchmark_requirement_name']}",
        f"- benchmark_requirement_summary: {capability_brief['benchmark_requirement_summary']}",
        "",
        "## Capability Under Test",
        capability_brief["capability_under_test"],
        "",
        "## Replay Result",
        f"- query_success_rate: {replay_eval['metrics']['query_success_rate']}",
        f"- evidence_trace_rate: {replay_eval['metrics']['evidence_trace_rate']}",
        f"- current_state_accuracy: {replay_eval['metrics']['current_state_accuracy']}",
        "",
        "## Baseline Comparison",
    ]
    for row in baseline_eval["results"]:
        metrics = row["metrics"]
        lines.append(
            f"- {row['baseline_mode']}: query={metrics['query_success_rate']}, evidence={metrics['evidence_trace_rate']}, current_state={metrics['current_state_accuracy']}"
        )
    lines.extend(
        [
            "",
            "## Value Summary",
            f"- vs_openclaw_memory_md: {value_eval['task_wiki_advantage']['vs_openclaw_memory_md']}",
            f"- vs_raw_message_rag: {value_eval['task_wiki_advantage']['vs_raw_message_rag']}",
            "",
            value_eval["summary"],
            "",
        ]
    )
    return "\n".join(lines)
