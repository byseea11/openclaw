"""LongMemEval benchmark input adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval_old.base import InputStep, MemAdapter
from eval_old.openclaw_client import OpenClawEvalResponse


class LongMemEvalAdapter(MemAdapter):
    """Adapt LongMemEval samples into raw OpenClaw history/query inputs."""

    benchmark_name = "longmemeval"
    message_channel = "feishu"

    def load_dataset(self, input_path: str | Path) -> list[dict[str, Any]]:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("LongMemEval input must be a JSON list.")
        return [dict(item) for item in data if isinstance(item, dict)]

    def make_sample_id(self, sample: Any) -> str:
        return str(sample.get("question_id") or "question")

    def build_history_inputs(self, sample: Any) -> list[InputStep]:
        session_ids = list(sample.get("haystack_session_ids") or [])
        session_dates = list(sample.get("haystack_dates") or [])
        session_turns = list(sample.get("haystack_sessions") or [])

        steps: list[InputStep] = []
        for session_id, session_date, turns in zip(session_ids, session_dates, session_turns):
            input_items: list[dict[str, Any]] = [
                {
                    "type": "message",
                    "role": "system",
                    "content": f"LongMemEval session {session_id}. Session date: {session_date}.",
                }
            ]
            if isinstance(turns, list):
                for turn in turns:
                    if not isinstance(turn, dict):
                        continue
                    role = str(turn.get("role") or "user")
                    content = str(turn.get("content") or "").strip()
                    if not content:
                        continue
                    normalized_role = role if role in {"system", "user", "assistant"} else "user"
                    prefix = self._message_prefix(
                        session_id=str(session_id),
                        session_date=str(session_date),
                        role=normalized_role,
                    )
                    input_items.append(
                        {
                            "type": "message",
                            "role": normalized_role,
                            "content": f"{prefix} {content}",
                        }
                    )
            steps.append(
                InputStep(
                    kind="history",
                    input_items=input_items,
                    metadata={"session_id": session_id, "session_date": session_date},
                )
            )
        return steps

    def build_query_input(self, sample: Any) -> InputStep:
        question = str(sample.get("question") or "").strip()
        question_type = str(sample.get("question_type") or "").strip()
        question_id = str(sample.get("question_id") or "")
        if question_id.endswith("_abs"):
            instructions = (
                "Answer the LongMemEval question using only the history already provided. "
                "Before answering, call the memory_search tool exactly once with the question "
                "and use any relevant recall results as supporting evidence. "
                "If the answer is not available in the history, reply with 'I don't know'."
            )
        else:
            instructions = (
                "Answer the LongMemEval question using only the history already provided. "
                "Before answering, call the memory_search tool exactly once with the question "
                "and use any relevant recall results as supporting evidence. "
                "Return the shortest correct answer."
            )
        return InputStep(
            kind="query",
            instructions=instructions,
            input_items=[
                {
                    "type": "message",
                    "role": "user",
                    "content": f"Question Type: {question_type}\nQuestion: {question}",
                }
            ],
            metadata={"question_type": question_type},
        )

    @staticmethod
    def _message_prefix(*, session_id: str, session_date: str, role: str) -> str:
        parts = [f"LongMemEval session {session_id}"]
        if session_date:
            parts.append(f"Session date: {session_date}")
        parts.append(f"role: {role}")
        return "[" + "; ".join(parts) + "]"

    def parse_prediction(self, sample: Any, response: OpenClawEvalResponse) -> dict[str, Any]:
        prediction = (response.text or "").strip()
        return {
            "question_id": str(sample.get("question_id") or ""),
            "question_type": str(sample.get("question_type") or ""),
            "question": str(sample.get("question") or ""),
            "gold_answer": str(sample.get("answer") or ""),
            "gold_session_ids": list(sample.get("answer_session_ids") or []),
            "hypothesis": prediction,
            "response_id": response.response_id,
            "latency_ms": response.latency_ms,
            "raw": response.raw_payload,
        }
