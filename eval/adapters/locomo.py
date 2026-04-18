"""LoCoMo benchmark input adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.base import InputStep, MemAdapter
from eval.openclaw_client import OpenClawEvalResponse


class LoCoMoAdapter(MemAdapter):
    """Adapt LoCoMo's native conversation + QA format into raw OpenClaw inputs."""

    benchmark_name = "locomo"
    message_channel = "feishu"

    def load_dataset(self, input_path: str | Path) -> list[dict[str, Any]]:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("LoCoMo input must be a JSON list.")

        rows: list[dict[str, Any]] = []
        for sample in data:
            if not isinstance(sample, dict):
                continue
            qas = sample.get("qa") or []
            if not isinstance(qas, list):
                continue
            for qa_index, qa in enumerate(qas):
                if not isinstance(qa, dict):
                    continue
                rows.append(
                    {
                        "sample_id": str(sample.get("sample_id") or f"sample-{len(rows)}"),
                        "qa_index": qa_index,
                        "conversation": dict(sample.get("conversation") or {}),
                        "qa": qa,
                    }
                )
        return rows

    def make_sample_id(self, sample: Any) -> str:
        sample_id = str(sample.get("sample_id") or "sample")
        qa_index = int(sample.get("qa_index") or 0)
        return f"{sample_id}-q{qa_index}"

    def build_history_inputs(self, sample: Any) -> list[InputStep]:
        conversation = dict(sample.get("conversation") or {})
        speaker_a = str(conversation.get("speaker_a") or "speaker_a")
        speaker_b = str(conversation.get("speaker_b") or "speaker_b")
        session_numbers = self._session_numbers(conversation)

        steps: list[InputStep] = []
        for session_num in session_numbers:
            session_key = f"session_{session_num}"
            session_date = str(conversation.get(f"{session_key}_date_time") or "").strip()
            turns = conversation.get(session_key) or []
            if not isinstance(turns, list):
                continue

            input_items: list[dict[str, Any]] = []
            if session_date:
                input_items.append(
                    {
                        "type": "message",
                        "role": "system",
                        "content": f"LoCoMo conversation session {session_num}. Session date: {session_date}.",
                    }
                )

            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                speaker = str(turn.get("speaker") or "").strip()
                text = str(turn.get("text") or "").strip()
                if not text:
                    continue
                role = self._speaker_role(speaker, speaker_a, speaker_b)
                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": f"{speaker or 'speaker'}: {text}",
                    }
                )

            if input_items:
                steps.append(
                    InputStep(
                        kind="history",
                        input_items=input_items,
                        metadata={"session": session_num, "session_date": session_date},
                    )
                )
        return steps

    def build_query_input(self, sample: Any) -> InputStep:
        qa = dict(sample.get("qa") or {})
        question = str(qa.get("question") or "").strip()
        category = int(qa.get("category") or 0)
        if category == 2:
            question += " Use the conversation date if an approximate date is needed."
        elif category == 5:
            question += " If the answer is not mentioned, answer 'No information available'."
        return InputStep(
            kind="query",
            instructions=(
                "Answer the LoCoMo question using only the conversation history already provided. "
                "Return the shortest correct answer."
            ),
            input_items=[{"type": "message", "role": "user", "content": question}],
            metadata={"category": category},
        )

    def parse_prediction(self, sample: Any, response: OpenClawEvalResponse) -> dict[str, Any]:
        qa = dict(sample.get("qa") or {})
        prediction = (response.text or "").strip()
        return {
            "sample_id": str(sample.get("sample_id") or ""),
            "qa_index": int(sample.get("qa_index") or 0),
            "question": str(qa.get("question") or ""),
            "gold_answer": str(qa.get("answer") or ""),
            "gold_evidence": list(qa.get("evidence") or []),
            "category": int(qa.get("category") or 0),
            "prediction": prediction,
            "response_id": response.response_id,
            "latency_ms": response.latency_ms,
            "raw": response.raw_payload,
        }

    @staticmethod
    def _session_numbers(conversation: dict[str, Any]) -> list[int]:
        numbers: list[int] = []
        for key in conversation:
            if key.startswith("session_") and key.count("_") == 1:
                try:
                    numbers.append(int(key.split("_", 1)[1]))
                except ValueError:
                    continue
        return sorted(numbers)

    @staticmethod
    def _speaker_role(speaker: str, speaker_a: str, speaker_b: str) -> str:
        if speaker == speaker_a:
            return "user"
        if speaker == speaker_b:
            return "assistant"
        return "user"
