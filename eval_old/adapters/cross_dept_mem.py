"""CrossDeptMem benchmark input adapter."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval_old.base import InputStep, MemAdapter
from eval_old.cross_dept_mem_feishu import enrich_cross_dept_sample
from eval_old.openclaw_client import OpenClawEvalResponse, OpenClawToolOutput


_STRUCTURED_ID_RE = re.compile(r"\b(?:[A-Z][A-Z0-9]+-\d+|AP-\d+|TASK-\d+)\b")


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _result_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "matches", "hits", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    details = payload.get("details")
    if isinstance(details, dict):
        return _result_items(details)
    return []


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candidate_text(item: dict[str, Any]) -> str:
    for key in ("snippet", "text", "content", "summary", "body"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_probe_result(item: dict[str, Any]) -> dict[str, Any] | None:
    snippet = _candidate_text(item)
    path = str(item.get("path") or item.get("source") or "").strip()
    start_line = _safe_int(item.get("startLine") or item.get("start_line"))
    end_line = _safe_int(item.get("endLine") or item.get("end_line"))
    corpus = str(item.get("corpus") or "memory").strip() or "memory"
    graph_meta = item.get("graphMeta")
    if not isinstance(graph_meta, dict):
        graph_meta = item.get("graph_meta")
    if not isinstance(graph_meta, dict):
        graph_meta = None
    if not snippet and not path:
        return None
    return {
        "path": path,
        "startLine": start_line,
        "endLine": end_line,
        "snippet": snippet,
        "corpus": corpus,
        "graphMeta": graph_meta,
    }


def _normalize_probe_results(payload: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, int | None, str]] = set()
    for item in _result_items(payload):
        normalized = _normalize_probe_result(item)
        if normalized is None:
            continue
        key = (
            str(normalized.get("path") or ""),
            normalized.get("startLine"),
            normalized.get("endLine"),
            str(normalized.get("snippet") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)
    return results


def _unwrap_probe_payload(payload: Any) -> Any:
    current = payload
    for _ in range(4):
        if not isinstance(current, dict):
            return current
        nested = current.get("result")
        if nested is None:
            return current
        current = nested
    return current


class CrossDeptMemAdapter(MemAdapter):
    """Adapt CrossDeptMem samples into raw OpenClaw history/query inputs."""

    benchmark_name = "cross_dept_mem"
    message_channel = "feishu"

    def load_dataset(self, input_path: str | Path) -> list[dict[str, Any]]:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and "samples" in data:
            samples = data["samples"]
        elif isinstance(data, list):
            samples = data
        else:
            raise ValueError("CrossDeptMem input must be a JSON list or dict with 'samples' key.")
        return [
            enrich_cross_dept_sample(dict(item))
            for item in samples
            if isinstance(item, dict)
        ]

    def make_sample_id(self, sample: Any) -> str:
        return str(sample.get("sample_id") or "sample")

    def build_history_inputs(self, sample: Any) -> list[InputStep]:
        """Build history steps from Feishu-like raw messages when available."""
        steps: list[InputStep] = []

        messages = list(sample.get("messages") or [])
        if messages:
            for item in messages:
                sender = item.get("sender") or {}
                display_name = str(sender.get("display_name") or "Unknown")
                department = str(sender.get("department") or "")
                content = str(item.get("content_text") or "").strip()
                if not content:
                    continue
                message_type = str(item.get("message_type") or "text")
                if message_type == "interactive":
                    message_text = f"{display_name} 发了一条审批卡片：{content}"
                elif message_type == "post":
                    message_text = f"{display_name} 发了一条群公告：{content}"
                else:
                    message_text = f"{display_name}: {content}"

                steps.append(
                    InputStep(
                        kind="history",
                        input_items=[
                            {
                                "type": "message",
                                "role": "user",
                                "content": message_text,
                            }
                        ],
                        metadata={
                            "message_id": item.get("message_id"),
                            "chat_id": item.get("chat_id"),
                            "thread_id": item.get("thread_id"),
                            "root_id": item.get("root_id"),
                            "parent_id": item.get("parent_id"),
                            "sender_open_id": sender.get("open_id"),
                            "sender_actor_ref": sender.get("actor_ref"),
                            "department": department,
                            "created_at": item.get("created_at"),
                            "message_type": message_type,
                            "semantic_refs": item.get("semantic_refs", {}),
                        },
                    )
                )
            return steps

        history = list(sample.get("history") or [])
        for item in history:
            timestamp = str(item.get("timestamp") or "")
            actor = str(item.get("actor") or "")
            department = str(item.get("department") or "")
            content = str(item.get("content") or "").strip()

            if not content:
                continue

            # Format message with metadata
            message_text = f"[{timestamp}] {actor} ({department}): {content}"

            input_items: list[dict[str, Any]] = [
                {
                    "type": "message",
                    "role": "user",
                    "content": message_text,
                }
            ]

            steps.append(
                InputStep(
                    kind="history",
                    input_items=input_items,
                    metadata={
                        "timestamp": timestamp,
                        "actor": actor,
                        "department": department,
                        "entities": item.get("entities", []),
                        "events": item.get("events", []),
                    },
                )
            )

        return steps

    def build_query_input(self, sample: Any) -> InputStep:
        """Build query step for a specific query from the sample."""
        # This will be called multiple times for each query in the sample
        # The query should be passed via metadata
        raise NotImplementedError(
            "Use build_query_input_for_query() instead - CrossDeptMem has multiple queries per sample"
        )

    def build_query_input_for_query(self, sample: Any, query: dict[str, Any]) -> InputStep:
        """Build query step for a specific query."""
        question = str(query.get("question") or "").strip()
        query_type = str(query.get("query_type") or "").strip()
        query_id = str(query.get("query_id") or "")

        instructions = (
            "Answer the question using the conversation history provided. "
            "You may use memory_search or memory_get tools if needed. "
            "Provide a concise, accurate answer based on the evidence."
        )

        return InputStep(
            kind="query",
            instructions=instructions,
            input_items=[
                {
                    "type": "message",
                    "role": "user",
                    "content": f"Query Type: {query_type}\nQuestion: {question}",
                }
            ],
            metadata={
                "query_id": query_id,
                "query_type": query_type,
                "gold_answer": query.get("gold_answer"),
                "gold_evidence": query.get("gold_evidence", []),
                "reasoning": query.get("reasoning"),
            },
        )

    def build_retrieval_probe_input_for_query(self, sample: Any, query: dict[str, Any]) -> InputStep:
        question = str(query.get("question") or "").strip()
        query_type = str(query.get("query_type") or "").strip()
        query_id = str(query.get("query_id") or "")

        instructions = (
            "Use the memory_search tool exactly once with the user's question. "
            "After retrieval, respond with JSON only and no commentary. "
            'Return {"results":[{"path":"","startLine":1,"endLine":1,"snippet":"","corpus":"memory","graphMeta":null}]}. '
            "If nothing relevant is found, return {\"results\":[]}."
        )

        return InputStep(
            kind="probe",
            instructions=instructions,
            input_items=[
                {
                    "type": "message",
                    "role": "user",
                    "content": f"Query Type: {query_type}\nQuestion: {question}",
                }
            ],
            tools=[{"type": "function", "name": "memory_search"}],
            metadata={
                "query_id": query_id,
                "query_type": query_type,
                "question": question,
            },
        )

    def resolve_gold_evidence(self, sample: Any, query: dict[str, Any]) -> list[dict[str, Any]]:
        history = list(sample.get("history") or [])
        messages = list(sample.get("messages") or [])
        by_history_index: dict[int, list[str]] = defaultdict(list)
        for message in messages:
            semantic_refs = message.get("semantic_refs")
            if not isinstance(semantic_refs, dict):
                continue
            history_index = semantic_refs.get("history_index")
            if not isinstance(history_index, int):
                continue
            content_text = str(message.get("content_text") or "").strip()
            if content_text:
                by_history_index[history_index].append(content_text)

        resolved: list[dict[str, Any]] = []
        for ref in query.get("gold_evidence", []) or []:
            if not isinstance(ref, str):
                continue
            texts: list[str] = []
            if ref.startswith("history[") and ref.endswith("]"):
                try:
                    index = int(ref[len("history[") : -1])
                except ValueError:
                    index = -1
                if 0 <= index < len(history):
                    history_text = str((history[index] or {}).get("content") or "").strip()
                    if history_text:
                        texts.append(history_text)
                    texts.extend(by_history_index.get(index, []))
            deduped = list(dict.fromkeys(texts))
            resolved.append({"ref": ref, "texts": deduped})
        return resolved

    def parse_retrieval_probe(
        self,
        sample: Any,
        query: dict[str, Any],
        response: OpenClawEvalResponse,
    ) -> dict[str, Any]:
        del sample, query
        for tool_output in response.tool_outputs:
            if tool_output.name != "memory_search":
                continue
            results = _normalize_probe_results(tool_output.output)
            if results or (
                isinstance(tool_output.output, dict) and isinstance(tool_output.output.get("results"), list)
            ):
                return {
                    "status": "ok",
                    "source": "tool_output",
                    "results": results,
                }

        text = _strip_json_fence(response.text)
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            results = _normalize_probe_results(payload)
            if results or (isinstance(payload, dict) and isinstance(payload.get("results"), list)):
                return {
                    "status": "ok",
                    "source": "assistant_json",
                    "results": results,
                }

        return {
            "status": "missing_tool_output",
            "source": None,
            "results": [],
            "error": "probe response did not contain parseable memory_search results",
        }

    def parse_retrieval_probe_result(
        self,
        sample: Any,
        query: dict[str, Any],
        payload: Any,
    ) -> dict[str, Any]:
        del sample, query
        normalized_payload = _unwrap_probe_payload(payload)
        results = _normalize_probe_results(normalized_payload)
        if results or (
            isinstance(normalized_payload, dict)
            and isinstance(normalized_payload.get("results"), list)
        ):
            return {
                "status": "ok",
                "source": "tools_invoke",
                "results": results,
            }
        return {
            "status": "missing_tool_output",
            "source": "tools_invoke",
            "results": [],
            "error": "tools.invoke memory_search payload did not contain parseable results",
        }

    def parse_prediction(
        self,
        sample: Any,
        response: OpenClawEvalResponse,
    ) -> dict[str, Any]:
        """Convert the final OpenClaw response into benchmark-facing fields."""
        # response.text is already extracted by OpenClawEvalClient
        predicted_answer = response.text.strip()

        # response.tool_calls is already parsed by OpenClawEvalClient
        tool_calls = [
            {"tool": tc.name, "arguments": tc.arguments}
            for tc in response.tool_calls
        ]

        usage = response.usage or {}
        # Gateway returns input_tokens/output_tokens; map to prompt/completion for scorer
        prompt_tokens = (
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 0
        )
        completion_tokens = (
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )

        return {
            "predicted_answer": predicted_answer,
            "tool_calls": tool_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    def extract_structured_ids(self, text: str) -> list[str]:
        return sorted({match.group(0) for match in _STRUCTURED_ID_RE.finditer(text or "")})
