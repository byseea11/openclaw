"""Run read-only validation against a frozen office snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval_old.env import resolve_openclaw_token
from eval_old.office_validation import run_validation_variant
from eval_old.openclaw_client import OpenClawEvalClient
from eval_old.scorers.common import dump_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run read-only validation on a frozen office snapshot.")
    parser.add_argument("--root-dir", default="eval/office_dataset")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--output-dir", default="eval/reports/office_validation")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--inter-step-delay-ms", type=float, default=0.0)
    parser.add_argument("--detach-query-context", action="store_true")
    parser.add_argument("--native-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--graph-gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--native-gateway-token")
    parser.add_argument("--graph-gateway-token")
    parser.add_argument("--native-agent", default="main")
    parser.add_argument("--graph-agent", default="main")
    parser.add_argument("--variants", default="native,graph")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    variants_to_run = [item.strip() for item in args.variants.split(",") if item.strip()]
    summaries: dict[str, dict] = {}

    if "native" in variants_to_run:
        native_client = OpenClawEvalClient(
            args.native_gateway_url,
            agent=args.native_agent,
            token=resolve_openclaw_token(args.native_gateway_token),
            timeout_seconds=args.timeout,
        )
        summaries["native"] = run_validation_variant(
            client=native_client,
            root_dir=args.root_dir,
            snapshot_id=args.snapshot_id,
            output_dir=output_dir,
            variant_name="native",
            agent=args.native_agent,
            inter_step_delay_ms=args.inter_step_delay_ms,
            detach_query_context=args.detach_query_context,
        )

    if "graph" in variants_to_run:
        graph_client = OpenClawEvalClient(
            args.graph_gateway_url,
            agent=args.graph_agent,
            token=resolve_openclaw_token(args.graph_gateway_token),
            timeout_seconds=args.timeout,
        )
        summaries["graph"] = run_validation_variant(
            client=graph_client,
            root_dir=args.root_dir,
            snapshot_id=args.snapshot_id,
            output_dir=output_dir,
            variant_name="graph",
            agent=args.graph_agent,
            inter_step_delay_ms=args.inter_step_delay_ms,
            detach_query_context=args.detach_query_context,
        )

    dump_json(summaries, output_dir / "summary.json")
    print(f"Wrote office validation summaries to {output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
