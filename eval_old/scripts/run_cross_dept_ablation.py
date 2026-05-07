"""Run CrossDeptMem ablation test: native vs graph-index OpenClaw."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval_old.adapters.cross_dept_mem import CrossDeptMemAdapter
from eval_old.cross_dept_mem_ablation import run_cross_dept_mem_variant
from eval_old.env import resolve_openclaw_token
from eval_old.scorers.common import dump_json
from eval_old.scorers.cross_dept_mem import CrossDeptMemScorer
from eval_old.variants import EvalVariant, build_efficiency_comparison, build_quality_comparison


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare native, graph, and graph+ordering OpenClaw variants on CrossDeptMem."
    )
    parser.add_argument(
        "--input",
        default="eval/fixtures/cross_dept_mem_bench.json",
        help="Path to CrossDeptMem dataset JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="eval/reports/cross_dept_ablation",
        help="Output directory for results.",
    )
    parser.add_argument("--max-samples", type=int, help="Limit number of samples to test.")
    parser.add_argument("--timeout", type=float, default=180.0, help="Request timeout in seconds.")
    parser.add_argument(
        "--inter-step-delay-ms",
        type=float,
        default=500.0,
        help="Delay after each history step (for graph projection).",
    )
    parser.add_argument(
        "--detach-query-context",
        action="store_true",
        help="Send query without previous_response_id (force memory recall).",
    )

    # Variant configuration
    parser.add_argument("--native-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--graph-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--graph-ordering-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--native-agent", default="main")
    parser.add_argument("--graph-agent", default="main")
    parser.add_argument("--graph-ordering-agent", default="main")
    parser.add_argument("--native-gateway-token")
    parser.add_argument("--graph-gateway-token")
    parser.add_argument("--graph-ordering-gateway-token")

    parser.add_argument(
        "--variants",
        default="native,graph,graph_ordering",
        help="Comma-separated list of variants to run (native, graph, graph_ordering).",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()

    # Setup
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        print("Run: python eval/scripts/generate_cross_dept_dataset.py first")
        sys.exit(1)

    # Load dataset
    adapter = CrossDeptMemAdapter()
    scorer = CrossDeptMemScorer()
    samples = adapter.load_dataset(input_path)

    if args.max_samples:
        samples = samples[: args.max_samples]

    print(f"Loaded {len(samples)} samples from {input_path}")

    # Define variants
    native_token = resolve_openclaw_token(args.native_gateway_token)
    graph_token = resolve_openclaw_token(args.graph_gateway_token)
    graph_ordering_token = resolve_openclaw_token(args.graph_ordering_gateway_token)

    variants_to_run = [v.strip() for v in args.variants.split(",") if v.strip()]

    results: dict[str, Any] = {}

    # Run native variant
    if "native" in variants_to_run:
        print("\n=== Running NATIVE variant ===")
        native_variant = EvalVariant(
            name="native",
            gateway_url=args.native_gateway_url,
            agent=args.native_agent,
            gateway_token=native_token,
        )

        native_output = output_dir / "native.jsonl"
        native_summary = run_cross_dept_mem_variant(
            variant=native_variant,
            adapter=adapter,
            scorer=scorer,
            samples=samples,
            output_path=native_output,
            timeout_seconds=args.timeout,
            inter_step_delay_ms=args.inter_step_delay_ms,
            detach_query_context=args.detach_query_context,
        )

        results["native"] = {
            "summary": native_summary,
            "output": str(native_output),
        }

        print(f"\nNative results:")
        print(f"  Exact Match: {native_summary.get('exact_match', 0):.2%}")
        print(f"  F1: {native_summary.get('average_f1', 0):.2%}")
        print(f"  Recall@5: {native_summary.get('average_recall_at_5', 0):.2%}")
        print(f"  Recall@10: {native_summary.get('average_recall_at_10', 0):.2%}")
        print(f"  Avg Prompt Tokens: {native_summary.get('average_prompt_tokens', 0):.0f}")
        print(f"  Avg Memory Tool Calls: {native_summary.get('average_memory_tool_calls', 0):.2f}")

    # Run graph variant
    if "graph" in variants_to_run:
        print("\n=== Running GRAPH variant ===")
        graph_variant = EvalVariant(
            name="graph",
            gateway_url=args.graph_gateway_url,
            agent=args.graph_agent,
            gateway_token=graph_token,
        )

        graph_output = output_dir / "graph.jsonl"
        graph_summary = run_cross_dept_mem_variant(
            variant=graph_variant,
            adapter=adapter,
            scorer=scorer,
            samples=samples,
            output_path=graph_output,
            timeout_seconds=args.timeout,
            inter_step_delay_ms=args.inter_step_delay_ms,
            detach_query_context=args.detach_query_context,
        )

        results["graph"] = {
            "summary": graph_summary,
            "output": str(graph_output),
        }

        print(f"\nGraph results:")
        print(f"  Exact Match: {graph_summary.get('exact_match', 0):.2%}")
        print(f"  F1: {graph_summary.get('average_f1', 0):.2%}")
        print(f"  Recall@5: {graph_summary.get('average_recall_at_5', 0):.2%}")
        print(f"  Recall@10: {graph_summary.get('average_recall_at_10', 0):.2%}")
        print(f"  Avg Prompt Tokens: {graph_summary.get('average_prompt_tokens', 0):.0f}")
        print(f"  Avg Memory Tool Calls: {graph_summary.get('average_memory_tool_calls', 0):.2f}")

    # Run graph + ordering variant
    if "graph_ordering" in variants_to_run:
        print("\n=== Running GRAPH_ORDERING variant ===")
        graph_ordering_variant = EvalVariant(
            name="graph_ordering",
            gateway_url=args.graph_ordering_gateway_url,
            agent=args.graph_ordering_agent,
            gateway_token=graph_ordering_token,
        )

        graph_ordering_output = output_dir / "graph_ordering.jsonl"
        graph_ordering_summary = run_cross_dept_mem_variant(
            variant=graph_ordering_variant,
            adapter=adapter,
            scorer=scorer,
            samples=samples,
            output_path=graph_ordering_output,
            timeout_seconds=args.timeout,
            inter_step_delay_ms=args.inter_step_delay_ms,
            detach_query_context=args.detach_query_context,
        )

        results["graph_ordering"] = {
            "summary": graph_ordering_summary,
            "output": str(graph_ordering_output),
        }

        print(f"\nGraph+Ordering results:")
        print(f"  Exact Match: {graph_ordering_summary.get('exact_match', 0):.2%}")
        print(f"  F1: {graph_ordering_summary.get('average_f1', 0):.2%}")
        print(f"  Recall@5: {graph_ordering_summary.get('average_recall_at_5', 0):.2%}")
        print(f"  Recall@10: {graph_ordering_summary.get('average_recall_at_10', 0):.2%}")
        print(
            f"  Avg Prompt Tokens: {graph_ordering_summary.get('average_prompt_tokens', 0):.0f}"
        )
        print(
            f"  Avg Memory Tool Calls: {graph_ordering_summary.get('average_memory_tool_calls', 0):.2f}"
        )

    # Build quality comparison if both native and graph_ordering ran
    if "native" in results and "graph_ordering" in results:
        quality_comparison = build_quality_comparison(
            benchmark="cross_dept_mem",
            native_summary=results["native"]["summary"],
            graph_ordering_summary=results["graph_ordering"]["summary"],
            native_output=results["native"]["output"],
            graph_ordering_output=results["graph_ordering"]["output"],
        )

        comparison_path = output_dir / "quality.comparison.json"
        dump_json(quality_comparison, comparison_path)

        print(f"\n=== Quality Comparison (native vs graph_ordering) ===")
        for metric, delta_info in quality_comparison.get("metric_deltas", {}).items():
            delta = delta_info.get("delta", 0)
            native_val = delta_info.get("native", 0)
            graph_val = delta_info.get("graph_ordering", 0)
            print(f"  {metric}: {native_val:.4f} -> {graph_val:.4f} ({delta:+.4f})")
        print(f"\nQuality comparison saved to: {comparison_path}")

    # Build efficiency comparison if native, graph, and graph_ordering all ran
    if "native" in results and "graph" in results and "graph_ordering" in results:
        efficiency_comparison = build_efficiency_comparison(
            benchmark="cross_dept_mem",
            native_summary=results["native"]["summary"],
            graph_summary=results["graph"]["summary"],
            graph_ordering_summary=results["graph_ordering"]["summary"],
            native_output=results["native"]["output"],
            graph_output=results["graph"]["output"],
            graph_ordering_output=results["graph_ordering"]["output"],
        )
        efficiency_path = output_dir / "efficiency.comparison.json"
        dump_json(efficiency_comparison, efficiency_path)

        print(f"\n=== Efficiency Comparison ===")
        context_saving = efficiency_comparison.get("graph_index_context_saving", {})
        ordering_saving = efficiency_comparison.get("ordering_tool_call_saving", {})
        print(
            "  graph_index_context_saving: "
            f"{context_saving.get('native', 0):.1f} -> {context_saving.get('graph', 0):.1f} "
            f"({context_saving.get('delta', 0):+.1f})"
        )
        print(
            "  ordering_tool_call_saving: "
            f"{ordering_saving.get('graph', 0):.2f} -> {ordering_saving.get('graph_ordering', 0):.2f} "
            f"({ordering_saving.get('delta', 0):+.2f})"
        )
        print(f"\nEfficiency comparison saved to: {efficiency_path}")

    print(f"\nAll results saved to: {output_dir}")


if __name__ == "__main__":
    main()
