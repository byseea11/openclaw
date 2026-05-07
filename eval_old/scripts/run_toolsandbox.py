"""Run ToolSandbox with OpenClaw Gateway using the new eval adapter module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval_old.adapters.toolsandbox import build_toolsandbox_role
from eval_old.env import resolve_openclaw_token
from eval_old.scorers.common import dump_json
from eval_old.scorers.toolsandbox import ToolSandboxScorer


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_toolsandbox_imports() -> None:
    root = _repo_root()
    toolsandbox_root = root / "ToolSandbox"
    if not toolsandbox_root.exists():
        raise SystemExit(f"ToolSandbox directory does not exist: {toolsandbox_root}")
    for path in (root, toolsandbox_root):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ToolSandbox with OpenClaw Gateway.")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--gateway-token")
    parser.add_argument("--agent", default="main")
    parser.add_argument("--model-override")
    parser.add_argument("--user-type", default="GPT_4_o_2024_05_13")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--tool-backend", default="DEFAULT")
    parser.add_argument("--output-dir", default=str(_repo_root() / "outputs" / "openclaw_eval" / "toolsandbox"))
    return parser


def main() -> None:
    _ensure_toolsandbox_imports()
    from tool_sandbox.cli.utils import USER_TYPE_TO_FACTORY, resolve_scenarios
    from tool_sandbox.common.execution_context import RoleType
    from tool_sandbox.common.tool_discovery import ToolBackend
    from tool_sandbox.roles.execution_environment import ExecutionEnvironment

    args = build_parser().parse_args()
    gateway_token = resolve_openclaw_token(args.gateway_token)
    if args.user_type not in USER_TYPE_TO_FACTORY:
        raise SystemExit(f"Unknown user_type={args.user_type}.")

    role_cls = build_toolsandbox_role(
        gateway_base_url=args.gateway_url,
        gateway_token=gateway_token,
        openclaw_agent_id=args.agent,
        model_override=args.model_override,
    )
    scenarios = resolve_scenarios(args.scenarios, preferred_tool_backend=ToolBackend(args.tool_backend))
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for scenario_name, scenario in scenarios.items():
        roles = {
            RoleType.USER: USER_TYPE_TO_FACTORY[args.user_type](),
            RoleType.EXECUTION_ENVIRONMENT: ExecutionEnvironment(),
            RoleType.AGENT: role_cls(),
        }
        try:
            result = scenario.play_and_evaluate(
                roles=roles,
                output_directory=output_dir,
                scenario_name=scenario_name,
            )
            rows.append(
                {
                    "name": scenario_name,
                    "categories": list(scenario.categories),
                    "similarity": result.evaluation_result.similarity,
                    "milestone_similarity": result.evaluation_result.milestone_similarity,
                    "minefield_similarity": result.evaluation_result.minefield_similarity,
                    "turn_count": result.evaluation_result.turn_count,
                    "error": None,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "name": scenario_name,
                    "categories": list(scenario.categories),
                    "similarity": 0.0,
                    "milestone_similarity": 0.0,
                    "minefield_similarity": 0.0,
                    "turn_count": getattr(scenario, "max_messages", 0),
                    "error": str(exc),
                }
            )
        finally:
            for role in roles.values():
                teardown = getattr(role, "teardown", None)
                if callable(teardown):
                    teardown()

    scorer = ToolSandboxScorer()
    summary = scorer.score(rows)
    scorer.save_outputs(rows, output_dir / "result_summary.json")
    dump_json(summary, output_dir / "summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
