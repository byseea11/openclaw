"""用 OpenClaw Gateway OpenResponses 跑 ToolSandbox。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_local_paths() -> None:
    root = _repo_root()
    toolsandbox_root = root / "ToolSandbox"
    if not toolsandbox_root.exists():
        raise SystemExit(f"ToolSandbox 目录不存在：{toolsandbox_root}")
    for path in (root, toolsandbox_root):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


_ensure_local_paths()

from tool_sandbox.cli.utils import USER_TYPE_TO_FACTORY, resolve_scenarios  # noqa: E402
from tool_sandbox.common.execution_context import RoleType  # noqa: E402
from tool_sandbox.common.tool_discovery import ToolBackend  # noqa: E402
from tool_sandbox.roles.execution_environment import ExecutionEnvironment  # noqa: E402

from eval.openclaw.agents.toolsandbox_role import OpenClawToolSandboxRole  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 OpenClaw Gateway 运行 ToolSandbox。")
    parser.add_argument("--gateway-base-url", default="http://127.0.0.1:18789")
    parser.add_argument("--gateway-token")
    parser.add_argument("--openclaw-agent-id", default="main")
    parser.add_argument("--model-override")
    parser.add_argument("--user-type", default="GPT_4_o_2024_05_13")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--tool-backend", default="DEFAULT")
    parser.add_argument(
        "--output-dir",
        default=str(_repo_root() / "outputs" / "openclaw_official" / "toolsandbox"),
    )
    return parser


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    args = build_parser().parse_args()
    if args.user_type not in USER_TYPE_TO_FACTORY:
        raise SystemExit(f"未知 user_type={args.user_type}，请使用 ToolSandbox 已有 user 实现。")
    scenarios = resolve_scenarios(args.scenarios, preferred_tool_backend=ToolBackend(args.tool_backend))
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    for scenario_name, scenario in scenarios.items():
        roles = {
            RoleType.USER: USER_TYPE_TO_FACTORY[args.user_type](),
            RoleType.EXECUTION_ENVIRONMENT: ExecutionEnvironment(),
            RoleType.AGENT: OpenClawToolSandboxRole(
                gateway_base_url=args.gateway_base_url,
                gateway_token=args.gateway_token,
                openclaw_agent_id=args.openclaw_agent_id,
                model_override=args.model_override,
            ),
        }
        try:
            result = scenario.play_and_evaluate(
                roles=roles,
                output_directory=output_dir,
                scenario_name=scenario_name,
            )
            summaries.append(
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
        except Exception as exc:  # pragma: no cover
            summaries.append(
                {
                    "name": scenario_name,
                    "categories": list(scenario.categories),
                    "similarity": 0.0,
                    "milestone_similarity": 0.0,
                    "minefield_similarity": 0.0,
                    "turn_count": scenario.max_messages,
                    "error": str(exc),
                }
            )
        finally:
            for role in roles.values():
                role.teardown()

    summary_payload = {
        "scenario_count": len(summaries),
        "success_count": sum(1 for item in summaries if not item["error"]),
        "average_similarity": _mean([float(item["similarity"]) for item in summaries]),
        "average_milestone_similarity": _mean(
            [float(item["milestone_similarity"]) for item in summaries]
        ),
        "average_minefield_similarity": _mean(
            [float(item["minefield_similarity"]) for item in summaries]
        ),
        "categories": dict(Counter(category for item in summaries for category in item["categories"])),
        "results": summaries,
    }
    output_file = output_dir / "result_summary.json"
    output_file.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
