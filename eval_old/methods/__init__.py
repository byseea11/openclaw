"""Built-in evaluation methods."""
from eval_old.methods.current_baseline import CurrentNanobotBaseline
from eval_old.methods.memory_aware_v1 import MemoryAwareV1
from eval_old.methods.openclaw_memory import OpenClawMemorySearchBaseline
from eval_old.methods.staged_memory import (
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
