"""Generate reusable validation candidate skeletons from a frozen office snapshot."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval_old.office_dataset import load_snapshot_bundle
from eval_old.scorers.common import dump_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate validation candidate skeletons from a frozen office snapshot.")
    parser.add_argument("--root-dir", default="eval/office_dataset")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--output")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    bundle = load_snapshot_bundle(args.root_dir, args.snapshot_id)
    events = bundle["events"]

    by_thread: dict[str, list[dict]] = defaultdict(list)
    by_task: dict[str, list[dict]] = defaultdict(list)

    for event in events:
        thread_id = str(event.get("thread_id") or "").strip()
        if thread_id:
            by_thread[thread_id].append(event)
        for task in event.get("task_refs", []) or []:
            task_id = str(task.get("id") or "").strip()
            if task_id:
                by_task[task_id].append(event)

    candidates: list[dict] = []

    for thread_id, thread_events in sorted(by_thread.items()):
        if len(thread_events) < 2:
            continue
        candidates.append(
            {
                "case_id": f"thread-{thread_id}",
                "snapshot_id": args.snapshot_id,
                "ability_tag": "cross_thread_relation",
                "question": f"What happened in thread {thread_id} most recently?",
                "expected_answer": "",
                "history_window": {"thread_ids": [thread_id]},
                "evidence_event_ids": [str(thread_events[-1].get("event_id") or "")],
                "notes": "Fill expected_answer after manual review.",
            }
        )

    for task_id, task_events in sorted(by_task.items()):
        if len(task_events) < 2:
            continue
        evidence = [str(event.get("event_id") or "") for event in task_events[-3:]]
        candidates.append(
            {
                "case_id": f"task-{task_id}",
                "snapshot_id": args.snapshot_id,
                "ability_tag": "long_horizon_status",
                "question": f"What is the latest status of {task_id}?",
                "expected_answer": "",
                "history_window": {"event_ids": evidence},
                "evidence_event_ids": evidence,
                "notes": "Fill expected_answer after manual review.",
            }
        )

    output_path = (
        Path(args.output)
        if args.output
        else Path(args.root_dir) / "snapshots" / args.snapshot_id / "validation_candidates.jsonl"
    )
    dump_jsonl(candidates, output_path)
    print(f"Wrote {len(candidates)} validation candidates to {output_path}")


if __name__ == "__main__":
    main()
