"""Run OpenClaw stock memory search against the shared memory eval harness."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from eval_old.memory_harness import (
    MemoryEvalDataset,
    MemoryEvalHarness,
    MemoryEvalSample,
    load_locomo_qa_dataset,
    load_memory_eval_dataset,
    write_memory_eval_report,
)
from eval_old.methods.openclaw_memory import OpenClawMemorySearchBaseline
from eval_old.office_schema import load_office_memory_eval_dataset

app = typer.Typer(help="Run OpenClaw memory_search evaluation.")


def _slice_dataset(
    dataset: MemoryEvalDataset,
    *,
    max_samples: int | None,
    max_queries_per_sample: int | None,
) -> MemoryEvalDataset:
    samples = dataset.samples[:max_samples] if max_samples and max_samples > 0 else list(dataset.samples)
    if max_queries_per_sample and max_queries_per_sample > 0:
        samples = [
            MemoryEvalSample(
                id=sample.id,
                history=sample.history,
                queries=sample.queries[:max_queries_per_sample],
                metadata=sample.metadata,
            )
            for sample in samples
        ]
    return MemoryEvalDataset(name=dataset.name, samples=samples, metadata=dataset.metadata)


def _load_dataset(
    *,
    dataset_path: Path | None,
    dataset_format: str,
    evidence_path: Path | None,
    eval_cases_path: Path | None,
) -> MemoryEvalDataset:
    fmt = dataset_format.lower().strip()
    if fmt == "office-memory":
        if evidence_path is None or eval_cases_path is None:
            raise typer.BadParameter(
                "office-memory format requires --evidence-path and --eval-cases-path"
            )
        return load_office_memory_eval_dataset(
            evidence_path=evidence_path,
            eval_cases_path=eval_cases_path,
        )

    if dataset_path is None:
        raise typer.BadParameter("dataset_path is required unless --dataset-format office-memory is used")
    if not dataset_path.exists():
        raise typer.BadParameter(f"Dataset not found: {dataset_path}")
    if fmt == "auto":
        fmt = "locomo" if "locomo" in dataset_path.name.lower() else "memory-eval"
    if fmt == "locomo":
        return load_locomo_qa_dataset(dataset_path)
    if fmt == "memory-eval":
        return load_memory_eval_dataset(dataset_path)
    raise typer.BadParameter("dataset-format must be one of: auto, memory-eval, locomo, office-memory")


@app.command()
def main(
    dataset_path: str | None = typer.Argument(
        None,
        help="Path to a memory-eval or LoCoMo dataset. Omit for --dataset-format office-memory.",
    ),
    dataset_format: str = typer.Option(
        "auto",
        "--dataset-format",
        help="Dataset format: auto, memory-eval, locomo, or office-memory.",
    ),
    evidence_path: str | None = typer.Option(
        None,
        "--evidence-path",
        help="MemoryEvidence JSONL path for office-memory format.",
    ),
    eval_cases_path: str | None = typer.Option(
        None,
        "--eval-cases-path",
        help="EvalCase JSONL path for office-memory format.",
    ),
    openclaw_root: str = typer.Option(
        "openclaw-main",
        "--openclaw-root",
        help="Path to the OpenClaw repository root.",
    ),
    workspace_root: str = typer.Option(
        "outputs/openclaw_eval/workspaces",
        "--workspace-root",
        help="Where per-sample OpenClaw workspaces are materialized.",
    ),
    state_root: str = typer.Option(
        "outputs/openclaw_eval/state",
        "--state-root",
        help="Where per-sample OpenClaw state/config is materialized.",
    ),
    output_path: str = typer.Option(
        "outputs/openclaw_eval/report.json",
        "--output",
        help="Where to write the JSON report.",
    ),
    agent: str = typer.Option("main", "--agent", help="OpenClaw agent id."),
    max_results: int = typer.Option(5, "--max-results", help="OpenClaw memory search max results."),
    min_score: float | None = typer.Option(None, "--min-score", help="Optional min score filter."),
    no_index: bool = typer.Option(False, "--no-index", help="Skip `openclaw memory index --force`."),
    answer_with_agent: bool = typer.Option(
        False,
        "--answer-with-agent",
        help="Also call `openclaw agent --message` for answer metrics.",
    ),
    recall_k: int = typer.Option(5, "--recall-k", help="k used for Recall@k and OracleHit@k."),
    max_samples: int | None = typer.Option(None, "--max-samples", help="Quick-run sample limit."),
    max_queries_per_sample: int | None = typer.Option(
        None,
        "--max-queries-per-sample",
        help="Quick-run query limit per sample.",
    ),
    timeout_seconds: float = typer.Option(180.0, "--timeout", help="Timeout per OpenClaw command."),
) -> None:
    """Run OpenClaw stock memory search as an eval method."""
    dataset = _load_dataset(
        dataset_path=Path(dataset_path) if dataset_path else None,
        dataset_format=dataset_format,
        evidence_path=Path(evidence_path) if evidence_path else None,
        eval_cases_path=Path(eval_cases_path) if eval_cases_path else None,
    )
    dataset = _slice_dataset(
        dataset,
        max_samples=max_samples,
        max_queries_per_sample=max_queries_per_sample,
    )
    method = OpenClawMemorySearchBaseline.from_paths(
        openclaw_root=openclaw_root,
        workspace_root=workspace_root,
        state_root=state_root,
        agent=agent,
        max_results=max_results,
        min_score=min_score,
        index_before_search=not no_index,
        answer_with_agent=answer_with_agent,
        timeout_seconds=timeout_seconds,
    )

    report = MemoryEvalHarness(recall_k=recall_k).run_sync(dataset, [method])
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    write_memory_eval_report(report, out_file)
    payload = {
        "dataset_name": report.dataset_name,
        "recall_k": report.recall_k,
        "summary": [summary.to_dict() for summary in report.summaries],
        "output_path": str(out_file),
        "sample_count": len(dataset.samples),
        "query_count": sum(len(sample.queries) for sample in dataset.samples),
        "answer_with_agent": answer_with_agent,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
