"""Run OpenClaw on LoCoMo's native QA format."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import typer

from eval.openclaw.cli import OpenClawCli
from eval.openclaw.official.locomo import run_openclaw_locomo_official

app = typer.Typer(help="Run OpenClaw official-format LoCoMo QA baseline.")


@app.command()
def main(
    data_file: str = typer.Argument(
        "locomo/data/locomo10.json",
        help="Path to LoCoMo's original locomo10.json file.",
    ),
    output_file: str = typer.Option(
        "outputs/openclaw_official/locomo/openclaw_locomo_predictions.json",
        "--output",
        help="Where to write LoCoMo-style predictions JSON.",
    ),
    stats_file: str | None = typer.Option(
        None,
        "--stats-output",
        help="Where to write aggregate stats JSON. Defaults beside --output.",
    ),
    openclaw_root: str = typer.Option(
        "openclaw-main",
        "--openclaw-root",
        help="Path to the OpenClaw source or built package root.",
    ),
    openclaw_command: str | None = typer.Option(
        None,
        "--openclaw-command",
        help="Optional explicit OpenClaw command, e.g. 'openclaw' or 'node /path/openclaw.mjs'.",
    ),
    workspace_root: str = typer.Option(
        "outputs/openclaw_official/locomo/workspaces",
        "--workspace-root",
        help="Where per-sample OpenClaw workspaces are materialized.",
    ),
    state_root: str = typer.Option(
        "outputs/openclaw_official/locomo/state",
        "--state-root",
        help="Where per-sample OpenClaw state/config is materialized.",
    ),
    model_key: str = typer.Option(
        "openclaw",
        "--model-key",
        help="Prefix used for LoCoMo prediction/f1 fields.",
    ),
    agent: str = typer.Option("main", "--agent", help="OpenClaw agent id."),
    answer_mode: Literal["agent", "memory-search-snippet"] = typer.Option(
        "memory-search-snippet",
        "--answer-mode",
        help="Use OpenClaw agent answers or first memory_search snippet as prediction.",
    ),
    top_k: int = typer.Option(5, "--top-k", help="memory_search max results."),
    max_samples: int | None = typer.Option(None, "--max-samples", help="Quick-run sample limit."),
    max_qas_per_sample: int | None = typer.Option(
        None,
        "--max-qas-per-sample",
        help="Quick-run QA limit per sample.",
    ),
    no_index: bool = typer.Option(False, "--no-index", help="Skip OpenClaw memory reindex."),
    timeout_seconds: float = typer.Option(180.0, "--timeout", help="Timeout per OpenClaw command."),
) -> None:
    """Run OpenClaw against LoCoMo and write native prediction/stat files."""
    command = tuple(openclaw_command.split()) if openclaw_command else None
    summary = run_openclaw_locomo_official(
        data_file=Path(data_file),
        output_file=Path(output_file),
        stats_file=Path(stats_file) if stats_file else None,
        openclaw=OpenClawCli.from_path(
            openclaw_root,
            command=command,
            timeout_seconds=timeout_seconds,
        ),
        workspace_root=workspace_root,
        state_root=state_root,
        model_key=model_key,
        agent=agent,
        answer_mode=answer_mode,
        top_k=top_k,
        max_samples=max_samples,
        max_qas_per_sample=max_qas_per_sample,
        index_before_query=not no_index,
    )
    typer.echo(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
