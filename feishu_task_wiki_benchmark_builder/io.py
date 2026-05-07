from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    file_path = Path(path)
    ensure_dir(file_path.parent)
    file_path.write_text(content, encoding="utf-8")


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    ensure_dir(file_path.parent)
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    lines = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        if not isinstance(value, dict):
            raise TypeError(f"Expected JSON object line in {path}")
        lines.append(value)
    return lines


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    file_path = Path(path)
    ensure_dir(file_path.parent)
    serialized = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    file_path.write_text(serialized + ("\n" if serialized else ""), encoding="utf-8")
