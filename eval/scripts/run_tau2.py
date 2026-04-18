"""Run tau2-bench with OpenClaw Gateway using the new eval adapter module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.adapters.tau2 import make_openclaw_tau2_agent_factory, make_openclaw_tau2_solo_agent_factory
from eval.env import resolve_openclaw_token
from eval.scorers.common import dump_json


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_tau2_imports() -> None:
    tau2_src = _repo_root() / "tau2-bench" / "src"
    if not tau2_src.exists():
        raise SystemExit(f"tau2-bench source directory does not exist: {tau2_src}")
    for path in (_repo_root(), tau2_src):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _parse_json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit("--agent-llm-args/--user-llm-args must be a JSON object.")
    return parsed


def _normalize_run_name(raw: str) -> str:
    path = Path(raw)
    return path.name or raw


def build_parser() -> argparse.ArgumentParser:
    _ensure_tau2_imports()
    from tau2.evaluator.evaluator import EvaluationType

    parser = argparse.ArgumentParser(description="Run tau2-bench with OpenClaw Gateway.")
    parser.add_argument("--domain", default="mock")
    parser.add_argument("--user-model")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--gateway-token")
    parser.add_argument("--agent", default="main")
    parser.add_argument("--model-override")
    parser.add_argument("--agent-name", default="openclaw_tau2_agent")
    parser.add_argument("--solo-mode", action="store_true")
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--num-tasks", type=int)
    parser.add_argument("--task-ids", nargs="*")
    parser.add_argument("--task-split-name", default="base")
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--max-errors", type=int, default=10)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--save-to")
    parser.add_argument("--output-dir", default=str(_repo_root() / "outputs" / "openclaw_eval" / "tau2"))
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
    _ensure_tau2_imports()
    from tau2.data_model.simulation import TextRunConfig
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.metrics.agent_metrics import compute_metrics
    from tau2.registry import registry
    from tau2.runner import get_tasks, make_run_name
    from tau2.runner.batch import run_tasks
    from tau2.user.user_simulator import DummyUser

    args = build_parser().parse_args()
    gateway_token = resolve_openclaw_token(args.gateway_token)
    if not args.solo_mode and not args.user_model:
        raise SystemExit("Non-solo mode requires --user-model.")

    class OpenClawCompatDummyUser(DummyUser):
        def __init__(self, **_kwargs):
            super().__init__()

    requested_run_name = args.save_to
    user_name = "openclaw_dummy_user" if args.solo_mode else "user_simulator"
    config = TextRunConfig(
        domain=args.domain,
        agent=args.agent_name,
        user=user_name,
        llm_agent="openclaw",
        llm_user=args.user_model or "dummy",
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
        save_to=requested_run_name,
        log_level=args.log_level,
    )
    run_name = _normalize_run_name(requested_run_name or make_run_name(config))
    config.save_to = run_name
    output_root = Path(args.output_dir).expanduser().resolve()
    results_dir = output_root / run_name

    if args.solo_mode:
        try:
            registry.register_user(OpenClawCompatDummyUser, user_name)
        except ValueError:
            pass
        factory = make_openclaw_tau2_solo_agent_factory(
            gateway_base_url=args.gateway_url,
            gateway_token=gateway_token,
            openclaw_agent_id=args.agent,
            model_override=args.model_override,
        )
        solo_cls = getattr(factory, "agent_class")
        registry.register_agent_factory(
            factory,
            args.agent_name,
            task_filter=solo_cls.check_valid_task,
            metadata={"solo_mode": True},
        )
    else:
        registry.register_agent_factory(
            make_openclaw_tau2_agent_factory(
                gateway_base_url=args.gateway_url,
                gateway_token=gateway_token,
                openclaw_agent_id=args.agent,
                model_override=args.model_override,
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
        save_path=results_dir / "results.json",
        save_dir=results_dir,
        evaluation_type=EvaluationType(args.evaluation_type),
    )
    metrics = compute_metrics(results)
    results_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_name": run_name,
        "domain": args.domain,
        "solo_mode": args.solo_mode,
        "user": user_name,
        "evaluation_type": args.evaluation_type,
        "avg_reward": metrics.avg_reward,
        "pass_hat_1": metrics.pass_hat_ks.get(1),
        "results_dir": str(results_dir),
    }
    dump_json(summary, results_dir / "summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
