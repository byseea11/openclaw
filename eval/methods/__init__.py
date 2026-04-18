"""Built-in evaluation methods."""
from eval.methods.current_baseline import CurrentNanobotBaseline
from eval.methods.memory_aware_v1 import MemoryAwareV1
from eval.methods.openclaw_memory import OpenClawMemorySearchBaseline
from eval.methods.staged_memory import (
    MemoryAwareV2,
    RetrieveCompressV1,
    SelectorOnlyV1,
)

__all__ = [
    "CurrentNanobotBaseline",
    "MemoryAwareV1",
    "SelectorOnlyV1",
    "RetrieveCompressV1",
    "MemoryAwareV2",
    "OpenClawMemorySearchBaseline",
]
