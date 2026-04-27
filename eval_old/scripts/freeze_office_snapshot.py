"""Freeze a live office capture into an immutable snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval_old.office_dataset import freeze_capture_to_snapshot
from eval_old.scorers.common import dump_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze a live office capture into an immutable snapshot.")
    parser.add_argument("--root-dir", default="eval/office_dataset")
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--employees", required=True, help="Path to employees.json source.")
    parser.add_argument("--validation-manifest", help="Optional validation manifest draft to freeze.")
    parser.add_argument("--workspace-id")
    parser.add_argument("--summary-output")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = freeze_capture_to_snapshot(
        root_dir=args.root_dir,
        capture_id=args.capture_id,
        snapshot_id=args.snapshot_id,
        employees_path=args.employees,
        validation_manifest_path=args.validation_manifest,
        workspace_id=args.workspace_id,
    )
    if args.summary_output:
        dump_json(summary, args.summary_output)
    print(f"Frozen snapshot {args.snapshot_id} under {Path(args.root_dir) / 'snapshots' / args.snapshot_id}")


if __name__ == "__main__":
    main()
