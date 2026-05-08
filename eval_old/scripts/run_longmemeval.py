"""Run LongMemEval against OpenClaw Gateway using the new eval abstractions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval_old.adapters.longmemeval import LongMemEvalAdapter
from eval_old.env import resolve_openclaw_token
from eval_old.openclaw_client import OpenClawEvalClient
from eval_old.scorers.common import dump_json
from eval_old.scorers.longmemeval import LongMemEvalScorer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run LongMemEval with OpenClaw Gateway.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="outputs/openclaw_eval/longmemeval/predictions.jsonl")
    parser.add_argument("--summary-output")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:18789")
    parser.add_argument("--gateway-token")
    parser.add_argument("--agent", default="main")
    parser.add_argument("--model-override")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    gateway_token = resolve_openclaw_token(args.gateway_token)
    adapter = LongMemEvalAdapter()
    scorer = LongMemEvalScorer()
    client = OpenClawEvalClient(
        args.gateway_url,
        agent=args.agent,
        token=gateway_token,
        model_override=args.model_override,
        timeout_seconds=args.timeout,
    )

    rows = adapter.load_dataset(args.input)
    if args.max_samples is not None:
        rows = rows[: max(0, args.max_samples)]

    outputs: list[dict] = []
    for sample in rows:
        session_key = f"eval-{adapter.benchmark_name}-{adapter.make_sample_id(sample)}"
        previous_response_id = None

        for step in adapter.build_history_inputs(sample):
            history_response = client.send(
                session_key=session_key,
                message_channel=adapter.message_channel,
                input_items=step.input_items,
                instructions=step.instructions,
                tools=step.tools,
                previous_response_id=previous_response_id,
            )
            previous_response_id = history_response.response_id

        query_step = adapter.build_query_input(sample)
        response = client.send(
            session_key=session_key,
            message_channel=adapter.message_channel,
            input_items=query_step.input_items,
            instructions=query_step.instructions,
            tools=query_step.tools,
            previous_response_id=previous_response_id,
        )
        outputs.append(adapter.parse_prediction(sample, response))

    summary = scorer.score(outputs)
    scorer.save_outputs(outputs, args.output)
    summary_path = args.summary_output or str(Path(args.output).with_suffix(".summary.json"))
    dump_json(summary, summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
