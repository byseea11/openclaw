"""OpenClaw benchmark adapters for interactive frameworks."""
from eval_old.openclaw.agents.tau2_agent import (
    OpenClawTau2Agent,
    OpenClawTau2SoloAgent,
    make_openclaw_tau2_agent_factory,
    make_openclaw_tau2_solo_agent_factory,
)

try:
    from eval_old.openclaw.agents.toolsandbox_role import OpenClawToolSandboxRole
except ImportError:  # pragma: no cover - optional ToolSandbox dependency
    OpenClawToolSandboxRole = None  # type: ignore[assignment]

__all__ = [
    "OpenClawTau2Agent",
    "OpenClawTau2SoloAgent",
    "OpenClawToolSandboxRole",
    "make_openclaw_tau2_agent_factory",
    "make_openclaw_tau2_solo_agent_factory",
]
