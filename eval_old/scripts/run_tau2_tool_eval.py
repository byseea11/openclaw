"""Run tau2-bench with a custom nanobot-backed text agent."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_local_paths() -> None:
    root = _repo_root()
    tau2_src = root / "tau2-bench" / "src"
    if not tau2_src.exists():
        raise SystemExit(
            f"tau2-bench source not found at {tau2_src}. "
            "Clone or place tau2-bench under the repo root first."
        )
    for path in (root, tau2_src):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


_ensure_local_paths()

from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.metrics.agent_metrics import compute_metrics  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner import get_tasks, make_run_name  # noqa: E402
from tau2.runner.batch import run_tasks  # noqa: E402

from eval_old.tau2_adapter import make_nanobot_tau2_agent_factory  # noqa: E402


def _parse_json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit("Expected a JSON object for --agent-llm-args/--user-llm-args.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run tau2-bench with nanobot as the evaluated text agent.",
    )
    parser.add_argument("--domain", default="mock")
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--user-model", required=True)
    parser.add_argument("--nanobot-config")
    parser.add_argument("--nanobot-workspace")
    parser.add_argument(
        "--memory-context-mode",
        choices=[
            "baseline",
            "selector_only_v1",
            "retrieve_compress_v1",
            "memory_aware_v2",
        ],
    )
    parser.add_argument("--agent-name", default="nanobot_tau2_agent")
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--num-tasks", type=int)
    parser.add_argument("--task-ids", nargs="*")
    parser.add_argument("--task-split-name", default="base")
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--max-errors", type=int, default=10)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--save-to")
    parser.add_argument("--log-level", default="ERROR")
    parser.add_argument(
        "--evaluation-type",
        default=EvaluationType.ALL.value,
        choices=[item.value for item in EvaluationType],
    )
    parser.add_argument("--agent-llm-args")
    parser.add_argument("--user-llm-args")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    config = TextRunConfig(
        domain=args.domain,
        agent=args.agent_name,
        llm_agent=args.agent_model,
        llm_user=args.user_model,
        llm_args_agent=_parse_json_dict(args.agent_llm_args),
        llm_args_user=_parse_json_dict(args.user_llm_args),
        num_trials=args.num_trials,
        num_tasks=args.num_tasks,
        task_ids=args.task_ids,
        task_split_name=args.task_split_name,
        max_steps=args.max_steps,
        max_errors=args.max_errors,
        max_concurrency=args.max_concurrency,
        timeout=args.timeout,
        save_to=args.save_to,
        log_level=args.log_level,
    )
    run_name = args.save_to or make_run_name(config)
    workspace = args.nanobot_workspace
    if not workspace:
        workspace = str(
            _repo_root()
            / "tau2-bench"
            / "data"
            / "nanobot-workspaces"
            / run_name
        )

    registry.register_agent_factory(
        make_nanobot_tau2_agent_factory(
            config_path=args.nanobot_config,
            workspace=workspace,
            memory_context_mode=args.memory_context_mode,
        ),
        args.agent_name,
    )

    tasks = get_tasks(
        task_set_name=config.task_set_name or config.domain,
        task_split_name=config.task_split_name,
        task_ids=config.task_ids,
        num_tasks=config.num_tasks,
    )
    results = run_tasks(
        config,
        tasks,
        save_path=(
            _repo_root()
            / "tau2-bench"
            / "data"
            / "simulations"
            / run_name
            / "results.json"
        ),
        save_dir=_repo_root() / "tau2-bench" / "data" / "simulations" / run_name,
        evaluation_type=EvaluationType(args.evaluation_type),
    )
    metrics = compute_metrics(results)

    print(f"run_name={run_name}")
    print(f"nanobot_workspace={workspace}")
    print(f"memory_context_mode={args.memory_context_mode or 'config-default'}")
    print(f"evaluation_type={args.evaluation_type}")
    print(f"avg_reward={metrics.avg_reward:.4f}")
    if 1 in metrics.pass_hat_ks:
        print(f"pass^1={metrics.pass_hat_ks[1]:.4f}")
    print(
        f"results_dir={_repo_root() / 'tau2-bench' / 'data' / 'simulations' / run_name}"
    )


if __name__ == "__main__":
    main()
