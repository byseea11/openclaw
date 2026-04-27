"""Small subprocess wrapper for OpenClaw CLI eval runs."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class OpenClawCommandResult:
    """Completed OpenClaw CLI command."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> Any:
        text = (self.stdout or "").strip()
        if not text:
            raise OpenClawCliError("OpenClaw command returned empty stdout", self)
        return json.loads(text)


class OpenClawCliError(RuntimeError):
    """Raised when an OpenClaw CLI command fails."""

    def __init__(self, message: str, result: OpenClawCommandResult | None = None):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class OpenClawCli:
    """Invoke the local OpenClaw CLI with isolated eval state."""

    openclaw_root: Path = _repo_root() / "openclaw-main"
    command: tuple[str, ...] | None = None
    timeout_seconds: float = 180.0

    @classmethod
    def from_path(
        cls,
        openclaw_root: str | Path | None = None,
        *,
        command: Sequence[str] | None = None,
        timeout_seconds: float = 180.0,
    ) -> OpenClawCli:
        root = Path(openclaw_root or (_repo_root() / "openclaw-main")).expanduser().resolve()
        return cls(
            openclaw_root=root,
            command=tuple(command) if command else None,
            timeout_seconds=timeout_seconds,
        )

    def base_command(self) -> list[str]:
        if self.command:
            return list(self.command)
        launcher = self.openclaw_root / "openclaw.mjs"
        return ["node", str(launcher)]

    def run(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        check: bool = True,
    ) -> OpenClawCommandResult:
        cmd = [*self.base_command(), *[str(item) for item in args]]
        merged_env = os.environ.copy()
        if env:
            merged_env.update({key: str(value) for key, value in env.items()})
        completed = subprocess.run(
            cmd,
            cwd=self.openclaw_root,
            env=merged_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds or self.timeout_seconds,
        )
        result = OpenClawCommandResult(
            args=cmd,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise OpenClawCliError(
                detail or f"OpenClaw command failed with exit code {result.returncode}",
                result,
            )
        return result
