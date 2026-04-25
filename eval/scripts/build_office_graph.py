"""Build a deterministic graph from a frozen office snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.office_graph import build_snapshot_graph
from eval.scorers.common import dump_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a graph artifact from a frozen office snapshot.")
    parser.add_argument("--root-dir", default="eval/office_dataset")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--output", help="Defaults to <snapshot>/graph.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    graph = build_snapshot_graph(root_dir=args.root_dir, snapshot_id=args.snapshot_id)
    output_path = Path(args.output) if args.output else Path(args.root_dir) / "snapshots" / args.snapshot_id / "graph.json"
    dump_json(graph, output_path)
    print(f"Wrote graph to {output_path}")


if __name__ == "__main__":
    main()
