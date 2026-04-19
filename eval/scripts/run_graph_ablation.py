"""Run native OpenClaw vs graph-index OpenClaw eval comparisons."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from eval.adapters.locomo import LoCoMoAdapter
from eval.adapters.longmemeval import LongMemEvalAdapter
from eval.env import resolve_openclaw_token
from eval.memory_ablation import run_memory_variant
from eval.scorers.common import dump_json
from eval.scorers.locomo import LoCoMoScorer
from eval.scorers.longmemeval import LongMemEvalScorer
from eval.variants import EvalVariant, build_comparison


BENCHMARKS = ("locomo", "longmemeval", "tau2", "toolsandbox")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare native OpenClaw against graph-index OpenClaw across eval suites."
    )
    parser.add_argument(
        "--benchmark",
        choices=[*BENCHMARKS, "all"],
        default="all",
        help="Benchmark to run. `all` runs every benchmark with configured inputs.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_repo_root() / "outputs" / "openclaw_eval" / "graph_ablation"),
    )
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--inter-step-delay-ms",
        type=float,
        default=0.0,
        help=(
            "Optional delay after each memory history step. Useful for graph-index "
            "evals because afterTurn projection observers complete after the turn."
        ),
    )
    parser.add_argument(
        "--detach-query-context",
        action="store_true",
        help=(
            "Send the final memory query without previous_response_id so the answer "
            "must come from OpenClaw memory recall instead of the live transcript."
        ),
    )

    parser.add_argument("--native-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--graph-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--native-agent", default="main")
    parser.add_argument("--graph-agent", default="main")
    parser.add_argument("--native-gateway-token")
    parser.add_argument("--graph-gateway-token")
    parser.add_argument("--native-model-override")
    parser.add_argument("--graph-model-override")
    parser.add_argument("--native-trace-path")
    parser.add_argument("--graph-trace-path")
    parser.add_argument(
        "--result-log-path",
        help="Optional JSON log file that receives the final comparison payload.",
    )

    parser.add_argument("--locomo-input", default="locomo/data/locomo10.json")
    parser.add_argument("--longmemeval-input")
    parser.add_argument(
        "--input",
        help="Compatibility alias for the selected memory benchmark input path.",
    )

    parser.add_argument(
        "--tau2-extra-args",
        default="",
        help="Extra args forwarded to eval.scripts.run_tau2, for example: \"--domain mock --solo-mode --num-tasks 5\".",
    )
    parser.add_argument(
        "--toolsandbox-extra-args",
        default="",
        help="Extra args forwarded to eval.scripts.run_toolsandbox, for example: \"--scenario single_tool_call\".",
    )
    return parser


def _selected_benchmarks(raw: str) -> list[str]:
    return list(BENCHMARKS) if raw == "all" else [raw]


def _variants(args: argparse.Namespace) -> tuple[EvalVariant, EvalVariant]:
    native_token = resolve_openclaw_token(args.native_gateway_token)
    graph_token = resolve_openclaw_token(args.graph_gateway_token)
    return (
        EvalVariant(
            name="native",
            gateway_url=args.native_gateway_url,
            agent=args.native_agent,
            gateway_token=native_token,
            model_override=args.native_model_override,
            trace_path=args.native_trace_path,
        ),
        EvalVariant(
            name="graph",
            gateway_url=args.graph_gateway_url,
            agent=args.graph_agent,
            gateway_token=graph_token,
            model_override=args.graph_model_override,
            trace_path=args.graph_trace_path,
        ),
    )


def _limit_samples(samples: list[Any], max_samples: int | None) -> list[Any]:
    if max_samples is None:
        return samples
    return samples[: max(0, max_samples)]


def _run_memory_benchmark(
    *,
    benchmark: str,
    args: argparse.Namespace,
    native: EvalVariant,
    graph: EvalVariant,
    output_dir: Path,
) -> dict[str, Any]:
    if benchmark == "locomo":
        adapter = LoCoMoAdapter()
        scorer = LoCoMoScorer()
        input_path = args.input or args.locomo_input
        output_suffix = ".json"
    elif benchmark == "longmemeval":
        input_path = args.input or args.longmemeval_input
        if not input_path:
            raise SystemExit("--longmemeval-input is required for LongMemEval.")
        adapter = LongMemEvalAdapter()
        scorer = LongMemEvalScorer()
        output_suffix = ".jsonl"
    else:
        raise ValueError(f"Unsupported memory benchmark: {benchmark}")

    samples = _limit_samples(adapter.load_dataset(input_path), args.max_samples)
    benchmark_dir = output_dir / benchmark
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    native_result = run_memory_variant(
        adapter=adapter,
        scorer=scorer,
        samples=samples,
        variant=native,
        output_path=benchmark_dir / f"native.predictions{output_suffix}",
        timeout_seconds=args.timeout,
        inter_step_delay_ms=args.inter_step_delay_ms,
        detach_query_context=args.detach_query_context,
    )
    graph_result = run_memory_variant(
        adapter=adapter,
        scorer=scorer,
        samples=samples,
        variant=graph,
        output_path=benchmark_dir / f"graph.predictions{output_suffix}",
        timeout_seconds=args.timeout,
        inter_step_delay_ms=args.inter_step_delay_ms,
        detach_query_context=args.detach_query_context,
    )
    comparison = build_comparison(
        benchmark=benchmark,
        native_summary=native_result["summary"],
        graph_summary=graph_result["summary"],
        native_output=native_result["output"],
        graph_output=graph_result["output"],
    )
    dump_json(comparison, benchmark_dir / "comparison.json")
    return comparison


def _run_subprocess(command: list[str]) -> None:
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"Command failed with exit={proc.returncode}: {' '.join(command)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def _variant_gateway_args(variant: EvalVariant) -> list[str]:
    parts = ["--gateway-url", variant.gateway_url, "--agent", variant.agent]
    if variant.gateway_token:
        parts.extend(["--gateway-token", variant.gateway_token])
    if variant.model_override:
        parts.extend(["--model-override", variant.model_override])
    return parts


def _run_tau2(
    *,
    args: argparse.Namespace,
    native: EvalVariant,
    graph: EvalVariant,
    output_dir: Path,
) -> dict[str, Any]:
    benchmark_dir = output_dir / "tau2"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    extra = shlex.split(args.tau2_extra_args)

    def run_variant(variant: EvalVariant) -> dict[str, Any]:
        summary_path = benchmark_dir / variant.name / "summary.json"
        command = [
            sys.executable,
            "-m",
            "eval.scripts.run_tau2",
            *_variant_gateway_args(variant),
            "--output-dir",
            str(benchmark_dir),
            *extra,
            "--save-to",
            variant.name,
        ]
        _run_subprocess(command)
        return json.loads(summary_path.read_text(encoding="utf-8"))

    native_summary = run_variant(native)
    graph_summary = run_variant(graph)
    comparison = build_comparison(
        benchmark="tau2",
        native_summary=native_summary,
        graph_summary=graph_summary,
        native_output=str(benchmark_dir / "native"),
        graph_output=str(benchmark_dir / "graph"),
    )
    dump_json(comparison, benchmark_dir / "comparison.json")
    return comparison


def _run_toolsandbox(
    *,
    args: argparse.Namespace,
    native: EvalVariant,
    graph: EvalVariant,
    output_dir: Path,
) -> dict[str, Any]:
    benchmark_dir = output_dir / "toolsandbox"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    extra = shlex.split(args.toolsandbox_extra_args)

    def run_variant(variant: EvalVariant) -> dict[str, Any]:
        variant_dir = benchmark_dir / variant.name
        summary_path = variant_dir / "summary.json"
        command = [
            sys.executable,
            "-m",
            "eval.scripts.run_toolsandbox",
            *_variant_gateway_args(variant),
            "--output-dir",
            str(variant_dir),
            *extra,
        ]
        _run_subprocess(command)
        return json.loads(summary_path.read_text(encoding="utf-8"))

    native_summary = run_variant(native)
    graph_summary = run_variant(graph)
    comparison = build_comparison(
        benchmark="toolsandbox",
        native_summary=native_summary,
        graph_summary=graph_summary,
        native_output=str(benchmark_dir / "native"),
        graph_output=str(benchmark_dir / "graph"),
    )
    dump_json(comparison, benchmark_dir / "comparison.json")
    return comparison


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    native, graph = _variants(args)
    comparisons: dict[str, Any] = {}

    for benchmark in _selected_benchmarks(args.benchmark):
        if benchmark in {"locomo", "longmemeval"}:
            comparisons[benchmark] = _run_memory_benchmark(
                benchmark=benchmark,
                args=args,
                native=native,
                graph=graph,
                output_dir=output_dir,
            )
        elif benchmark == "tau2":
            comparisons[benchmark] = _run_tau2(
                args=args,
                native=native,
                graph=graph,
                output_dir=output_dir,
            )
        elif benchmark == "toolsandbox":
            comparisons[benchmark] = _run_toolsandbox(
                args=args,
                native=native,
                graph=graph,
                output_dir=output_dir,
            )

    combined = {
        "benchmarks": comparisons,
        "output_dir": str(output_dir),
        "variant_note": (
            "Use separate Gateway configs for a clean native-vs-graph comparison; "
            "the runner intentionally does not mutate OpenClaw config."
        ),
    }
    dump_json(combined, output_dir / "comparison.json")
    if args.result_log_path:
        result_log_path = Path(args.result_log_path).expanduser().resolve()
        result_log_path.parent.mkdir(parents=True, exist_ok=True)
        dump_json(combined, result_log_path)
    print(json.dumps(combined, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
