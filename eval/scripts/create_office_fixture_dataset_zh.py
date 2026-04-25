"""Create the deterministic Chinese Yunhe Q2 office fixture snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.office_fixture_dataset_zh import (
    YUNHE_Q2_OPS_ZH_SNAPSHOT_ID,
    write_yunhe_q2_ops_zh_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a frozen Chinese realistic enterprise office dataset snapshot.")
    parser.add_argument("--root-dir", default="eval/office_dataset")
    parser.add_argument("--snapshot-id", default=YUNHE_Q2_OPS_ZH_SNAPSHOT_ID)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    snapshot_dir = write_yunhe_q2_ops_zh_snapshot(root_dir=args.root_dir, snapshot_id=args.snapshot_id)
    print(f"Wrote frozen Chinese office fixture snapshot to {snapshot_dir}")


if __name__ == "__main__":
    main()
