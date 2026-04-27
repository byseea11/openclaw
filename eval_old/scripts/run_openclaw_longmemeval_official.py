"""运行 OpenClaw 的 LongMemEval 官方格式 baseline。"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from eval_old.openclaw.cli import OpenClawCli
from eval_old.openclaw.official.longmemeval import run_openclaw_longmemeval_official

app = typer.Typer(help="运行 OpenClaw 的 LongMemEval 官方格式 baseline。")


@app.command()
def main(
    data_file: str = typer.Argument(..., help="LongMemEval 原始 JSON 数据文件。"),
    output_file: str = typer.Option(
        "outputs/openclaw_official/longmemeval/predictions.jsonl",
        "--output",
        help="官方提交格式 JSONL 输出路径。",
    ),
    detail_file: str | None = typer.Option(
        None,
        "--detail-output",
        help="包含上下文召回和本地分析的详细 JSON 输出路径。",
    ),
    openclaw_root: str = typer.Option("openclaw-main", "--openclaw-root"),
    openclaw_command: str | None = typer.Option(None, "--openclaw-command"),
    workspace_root: str = typer.Option(
        "outputs/openclaw_official/longmemeval/workspaces",
        "--workspace-root",
    ),
    state_root: str = typer.Option(
        "outputs/openclaw_official/longmemeval/state",
        "--state-root",
    ),
    model_key: str = typer.Option("openclaw", "--model-key"),
    agent: str = typer.Option("main", "--agent"),
    answer_mode: str = typer.Option("memory-search-snippet", "--answer-mode"),
    top_k: int = typer.Option(5, "--top-k"),
    max_samples: int | None = typer.Option(None, "--max-samples"),
    no_index: bool = typer.Option(False, "--no-index"),
    timeout_seconds: float = typer.Option(180.0, "--timeout"),
) -> None:
    command = tuple(openclaw_command.split()) if openclaw_command else None
    summary = run_openclaw_longmemeval_official(
        data_file=Path(data_file),
        output_file=Path(output_file),
        detail_file=Path(detail_file) if detail_file else None,
        openclaw=OpenClawCli.from_path(
            openclaw_root,
            command=command,
            timeout_seconds=timeout_seconds,
        ),
        workspace_root=workspace_root,
        state_root=state_root,
        model_key=model_key,
        agent=agent,
        answer_mode=answer_mode,  # type: ignore[arg-type]
        top_k=top_k,
        max_samples=max_samples,
        index_before_query=not no_index,
    )
    typer.echo(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
