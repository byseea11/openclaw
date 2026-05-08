"""Workspace materialization helpers for OpenClaw memory evals."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval_old.memory_harness import MemoryEvalSample

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(value: str) -> str:
    """Return a path-safe, stable identifier."""
    cleaned = _SAFE_NAME_RE.sub("_", value.strip())
    return cleaned.strip("._") or "sample"


def render_memory_markdown(sample: MemoryEvalSample) -> str:
    """Render a harness sample into OpenClaw-indexable Markdown memory."""
    lines = [
        "# Eval Memory",
        "",
        f"- sample_id: {sample.id}",
        f"- source: {sample.metadata.get('source', 'memory_eval')}",
        "",
    ]
    for idx, turn in enumerate(sample.history, start=1):
        turn_id = str(turn.get("turn_id") or f"turn-{idx}")
        role = str(turn.get("role") or "user")
        speaker = str(turn.get("speaker") or role)
        content = str(turn.get("content") or "").strip()
        lines.extend(
            [
                f"## Evidence {turn_id}",
                "",
                f"<!-- turn_id: {turn_id} -->",
                f"- turn_id: {turn_id}",
                f"- role: {role}",
                f"- speaker: {speaker}",
            ]
        )
        for key in ("session_id", "session_datetime", "timestamp"):
            value = str(turn.get(key) or "").strip()
            if value:
                lines.append(f"- {key}: {value}")
        metadata = turn.get("metadata")
        if isinstance(metadata, dict):
            for key in ("project_id", "memory_type", "status", "visibility"):
                value = metadata.get(key)
                if value is not None and str(value).strip():
                    lines.append(f"- {key}: {value}")
        lines.extend(["", content, ""])
    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class OpenClawEvalWorkspace:
    """Isolated OpenClaw state/config/workspace for one eval sample."""

    workspace_dir: Path
    state_dir: Path
    agent: str = "main"

    @property
    def config_path(self) -> Path:
        return self.state_dir / "openclaw.json"

    @classmethod
    def for_sample(
        cls,
        *,
        workspace_root: str | Path,
        state_root: str | Path,
        sample: MemoryEvalSample,
        agent: str = "main",
    ) -> OpenClawEvalWorkspace:
        sample_name = safe_name(sample.id)
        return cls(
            workspace_dir=Path(workspace_root).expanduser().resolve() / sample_name / "workspace",
            state_dir=Path(state_root).expanduser().resolve() / sample_name / "state",
            agent=agent,
        )

    def env(self) -> dict[str, str]:
        return {
            "OPENCLAW_STATE_DIR": str(self.state_dir),
            "OPENCLAW_CONFIG_PATH": str(self.config_path),
        }

    def prepare(self, sample: MemoryEvalSample) -> None:
        """Write workspace memory and minimal OpenClaw config."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        memory_file = self.workspace_dir / "MEMORY.md"
        memory_file.write_text(render_memory_markdown(sample), encoding="utf-8")
        self.config_path.write_text(
            json.dumps(self._config_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _config_payload(self) -> dict[str, Any]:
        return {
            "agents": {
                "defaults": {
                    "workspace": str(self.workspace_dir),
                    "memorySearch": {
                        "enabled": True,
                        "fallback": "fts",
                        "maxResults": 20,
                        "watch": False,
                    },
                },
                "profiles": {
                    self.agent: {
                        "workspace": str(self.workspace_dir),
                    }
                },
            },
            "plugins": {
                "slots": {
                    "memory": "memory-core",
                }
            },
        }
