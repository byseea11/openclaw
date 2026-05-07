"""Thin evaluation abstractions for benchmark adapters and scorers.

The eval layer only adapts benchmark samples into raw OpenClaw inputs and
maps OpenClaw outputs back into benchmark-specific scoring formats.
It must not precompute or replace OpenClaw's internal memory pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval_old.openclaw_client import OpenClawEvalResponse


@dataclass(frozen=True)
class InputStep:
    """One raw request step that should be sent to OpenClaw."""

    kind: str
    input_items: list[dict[str, Any]]
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BenchAdapter(ABC):
    """Base contract shared by every benchmark adapter."""

    benchmark_name: str
    message_channel: str = "feishu"

    @abstractmethod
    def load_dataset(self, input_path: str | Path) -> list[Any]:
        """Load benchmark-native samples from disk."""

    @abstractmethod
    def make_sample_id(self, sample: Any) -> str:
        """Return a stable per-sample identifier used for OpenClaw sessions."""


class MemAdapter(BenchAdapter):
    """Adapter for memory-style benchmarks such as LoCoMo and LongMemEval."""

    @abstractmethod
    def build_history_inputs(self, sample: Any) -> list[InputStep]:
        """Return history steps that should be sent before the final query."""

    @abstractmethod
    def build_query_input(self, sample: Any) -> InputStep:
        """Return the final query step for the sample."""

    @abstractmethod
    def parse_prediction(
        self,
        sample: Any,
        response: OpenClawEvalResponse,
    ) -> dict[str, Any]:
        """Convert the final OpenClaw response into benchmark-facing fields."""


@dataclass(frozen=True)
class ToolAdapterResult:
    """Result of handling one OpenClaw response inside an interactive benchmark."""

    done: bool
    next_step: InputStep | None = None
    result: dict[str, Any] | None = None


class ToolAdapter(BenchAdapter):
    """Adapter for tool / environment benchmarks such as tau2 and ToolSandbox."""

    @abstractmethod
    def init_runtime(self, sample: Any) -> Any:
        """Create benchmark-owned runtime state for one sample."""

    @abstractmethod
    def build_initial_input(self, sample: Any, runtime: Any) -> InputStep:
        """Build the first request sent to OpenClaw for the sample."""

    @abstractmethod
    def handle_response(
        self,
        sample: Any,
        runtime: Any,
        response: OpenClawEvalResponse,
    ) -> ToolAdapterResult:
        """Interpret one OpenClaw response and return the next external step."""


class BenchmarkScorer(ABC):
    """Base contract for benchmark-specific scoring and output emission."""

    benchmark_name: str

    @abstractmethod
    def save_outputs(self, rows: list[dict[str, Any]], output_path: str | Path) -> None:
        """Write benchmark-specific outputs to disk."""

    @abstractmethod
    def score(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Return aggregate benchmark metrics."""
