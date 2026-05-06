from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .io_utils import read_json, read_jsonl
from .schemas import validate_case_manifest, validate_openclaw_message_ingress


def replay_runtime(case_dir: str | Path) -> dict[str, Any]:
    root = Path(case_dir)
    validate_case_manifest(read_json(root / "case_manifest.json"))
    validate_openclaw_message_ingress(read_jsonl(root / "data" / "openclaw_message_ingress.jsonl"))
    wrapper = Path(__file__).resolve().parent / "runtime_replay_v3.cjs"
    completed = subprocess.run(
        ["node", str(wrapper), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"replay runtime failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return {
        "case_id": read_json(root / "case_spec.json")["case_id"],
        "candidate_events": read_jsonl(root / "predictions" / "candidate_events.jsonl"),
        "session_events": read_jsonl(root / "predictions" / "session_events.jsonl"),
        "session_wiki_state": read_json(root / "predictions" / "session_wiki_state.json"),
        "task_index_state": read_json(root / "predictions" / "task_index_state.json"),
        "task_wiki_state": read_json(root / "predictions" / "task_wiki_state.json"),
    }
