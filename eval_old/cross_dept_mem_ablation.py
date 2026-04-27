"""CrossDeptMem-specific memory ablation runner."""

from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Any

from eval_old.adapters.cross_dept_mem import CrossDeptMemAdapter
from eval_old.base import BenchmarkScorer
from eval_old.graph_usage import summarize_response_graph_usage, summarize_rows_graph_usage
from eval_old.openclaw_client import OpenClawEvalClient
from eval_old.variants import EvalVariant


def _replay_history(
    *,
    client: OpenClawEvalClient,
    adapter: CrossDeptMemAdapter,
    history_steps: list[Any],
    session_key: str,
    inter_step_delay_ms: float,
) -> str | None:
    previous_response_id = None
    for h_idx, step in enumerate(history_steps):
        print(f"    history step {h_idx + 1}/{len(history_steps)} ...", end=" ", flush=True)
        history_response = client.send(
            session_key=session_key,
            message_channel=adapter.message_channel,
            input_items=step.input_items,
            instructions=step.instructions,
            tools=step.tools,
            previous_response_id=previous_response_id,
        )
        print(f"ok ({history_response.latency_ms:.0f}ms)")
        previous_response_id = history_response.response_id
        if inter_step_delay_ms > 0:
            sleep(inter_step_delay_ms / 1000.0)
    return previous_response_id


def run_cross_dept_mem_variant(
    *,
    adapter: CrossDeptMemAdapter,
    scorer: BenchmarkScorer,
    samples: list[Any],
    variant: EvalVariant,
    output_path: str | Path,
    timeout_seconds: float,
    inter_step_delay_ms: float = 0.0,
    detach_query_context: bool = False,
) -> dict[str, Any]:
    """Run CrossDeptMem benchmark with one variant.

    CrossDeptMem has multiple queries per sample, so we need to handle that differently
    from standard memory benchmarks.
    """
    client = OpenClawEvalClient(
        variant.gateway_url,
        agent=variant.agent,
        token=variant.gateway_token,
        model_override=variant.model_override,
        timeout_seconds=timeout_seconds,
    )

    outputs: list[dict[str, Any]] = []
    session_keys: set[str] = set()

    total_samples = len(samples)
    for sample_idx, sample in enumerate(samples):
        sample_id = adapter.make_sample_id(sample)
        session_key = f"eval-{variant.name}-{adapter.benchmark_name}-{sample_id}"
        session_keys.add(session_key)

        history_steps = adapter.build_history_inputs(sample)
        queries = sample.get("queries", [])
        print(
            f"  [{sample_idx + 1}/{total_samples}] sample={sample_id} "
            f"history={len(history_steps)} steps, queries={len(queries)}"
        )

        # Send history steps once per sample
        previous_response_id = _replay_history(
            client=client,
            adapter=adapter,
            history_steps=history_steps,
            session_key=session_key,
            inter_step_delay_ms=inter_step_delay_ms,
        )

        # Run each query for this sample
        for q_idx, query in enumerate(queries):
            gold_evidence_items = adapter.resolve_gold_evidence(sample, query)

            probe_query_id = str(query.get("query_id") or f"q{q_idx + 1}")
            probe_session_key = (
                f"eval-{variant.name}-{adapter.benchmark_name}-{sample_id}-{probe_query_id}-probe"
            )
            session_keys.add(probe_session_key)
            print(
                f"    probe {q_idx + 1}/{len(queries)} [{query.get('query_type')}] "
                f"{query.get('question', '')[:60]} ...",
                end=" ",
                flush=True,
            )
            probe_previous_id = _replay_history(
                client=client,
                adapter=adapter,
                history_steps=history_steps,
                session_key=probe_session_key,
                inter_step_delay_ms=inter_step_delay_ms,
            )
            probe_step = adapter.build_retrieval_probe_input_for_query(sample, query)
            probe_response = client.invoke_tool(
                session_key=probe_session_key,
                message_channel=adapter.message_channel,
                tool="memory_search",
                args={
                    "query": probe_step.metadata.get("question") or query.get("question") or "",
                    "maxResults": 10,
                },
            )
            print(f"ok ({probe_response.latency_ms:.0f}ms)")
            probe = adapter.parse_retrieval_probe_result(sample, query, probe_response.result)

            query_step = adapter.build_query_input_for_query(sample, query)

            # Optionally detach query from history context
            query_previous_id = None if detach_query_context else previous_response_id

            print(
                f"    query {q_idx + 1}/{len(queries)} [{query.get('query_type')}] "
                f"{query.get('question', '')[:60]} ...",
                end=" ",
                flush=True,
            )
            query_response = client.send(
                session_key=session_key,
                message_channel=adapter.message_channel,
                input_items=query_step.input_items,
                instructions=query_step.instructions,
                tools=query_step.tools or [
                    {"type": "function", "name": "memory_search"},
                    {"type": "function", "name": "memory_get"},
                ],
                previous_response_id=query_previous_id,
            )
            print(f"ok ({query_response.latency_ms:.0f}ms)")

            # Parse prediction
            prediction = adapter.parse_prediction(sample, query_response)

            # Build output row
            row = {
                "sample_id": sample_id,
                "query_id": query.get("query_id"),
                "query_type": query.get("query_type"),
                "question": query.get("question"),
                "gold_answer": query.get("gold_answer"),
                "predicted_answer": prediction.get("predicted_answer"),
                "exact_match": None,  # Will be computed by scorer
                "f1": None,  # Will be computed by scorer
                "latency_ms": query_response.latency_ms,
                "prompt_tokens": prediction.get("prompt_tokens", 0),
                "completion_tokens": prediction.get("completion_tokens", 0),
                "tool_calls": prediction.get("tool_calls", []),
                "gold_evidence_refs": [item.get("ref") for item in gold_evidence_items],
                "gold_evidence_items": gold_evidence_items,
                "retrieval_results": probe.get("results", []),
                "retrieval_probe_status": probe.get("status"),
                "retrieval_probe_source": probe.get("source"),
                "retrieval_probe_error": probe.get("error"),
                "memory_search_calls": None,  # Will be computed by scorer
                "memory_get_calls": None,  # Will be computed by scorer
                "memory_tool_calls": None,  # Will be computed by scorer
                "recall_at_5": None,  # Will be computed by scorer
                "recall_at_10": None,  # Will be computed by scorer
                "graph_usage": summarize_response_graph_usage(query_response),
            }

            outputs.append(row)

    # Score all outputs
    summary = scorer.score(outputs)
    scorer.save_outputs(outputs, output_path)

    # Add graph usage summary
    summary["graph_usage"] = summarize_rows_graph_usage(outputs)

    return summary
