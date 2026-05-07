"""Upgrade CrossDeptMem fixture into a Feishu-like raw-message schema.

Keeps semantic `history` / `queries` untouched so existing scorers still work.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval_old.cross_dept_mem_feishu import enrich_cross_dept_dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upgrade CrossDeptMem fixture to include Feishu-like raw chat/messages."
    )
    parser.add_argument(
        "--input",
        default="eval/fixtures/cross_dept_mem_bench.json",
        help="Path to the source CrossDeptMem dataset.",
    )
    parser.add_argument(
        "--output",
        help="Optional output path. Defaults to overwriting --input.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("CrossDeptMem fixture must be a JSON object with a samples array.")

    upgraded = enrich_cross_dept_dataset(data)
    output_path.write_text(
        json.dumps(upgraded, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Upgraded CrossDeptMem dataset written to {output_path}")


if __name__ == "__main__":
    main()
