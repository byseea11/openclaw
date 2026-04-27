"""Small helpers for loading eval environment variables."""

from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_dotenv(path: str | Path | None = None) -> None:
    env_path = Path(path) if path is not None else _repo_root() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def resolve_openclaw_token(explicit_token: str | None) -> str | None:
    if explicit_token:
        return explicit_token
    load_dotenv()
    return os.environ.get("OPENCLAW_TOKEN") or None
