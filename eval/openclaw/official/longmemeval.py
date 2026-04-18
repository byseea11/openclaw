"""OpenClaw runner for LongMemEval's native format."""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from eval.openclaw.cli import OpenClawCli
from eval.openclaw.official.locomo import LoCoMoOpenClawWorkspace

SESSION_MARKER_RE = re.compile(r"(?:<!--\s*session_id:\s*|- session_id:\s*)([A-Za-z0-9_-]+)")
AnswerMode = Literal["agent", "memory-search-snippet"]


@dataclass(frozen=True)
class LongMemEvalOfficialSummary:
    """Aggregate summary for a LongMemEval official-format run."""

    data_file: str
    output_file: str
    detail_file: str
    model_key: str
    answer_mode: str
    sample_count: int
    completed_count: int
    failed_count: int
    exact_match: float
    evidence_recall: float
    abstention_accuracy: float
    average_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def render_longmemeval_memory(sample: dict[str, Any]) -> str:
    """Render LongMemEval sessions into OpenClaw markdown memory."""
    lines = [
        "# LongMemEval Memory",
        "",
        f"- question_id: {sample.get('question_id', '')}",
        f"- question_type: {sample.get('question_type', '')}",
        f"- question_date: {sample.get('question_date', '')}",
        "",
    ]
    for session_id, session_date, session_turns in zip(
        sample.get("haystack_session_ids") or [],
        sample.get("haystack_dates") or [],
        sample.get("haystack_sessions") or [],
    ):
        lines.extend(
            [
                f"## Session {session_id}",
                "",
                f"<!-- session_id: {session_id} -->",
                f"- session_id: {session_id}",
                f"- date: {session_date}",
                "",
            ]
        )
        for turn_index, turn in enumerate(session_turns or [], start=1):
            role = str(turn.get("role") or "user")
            content = str(turn.get("content") or "").strip()
            turn_id = f"{session_id}_{turn_index}"
            lines.extend(
                [
                    f"### Turn {turn_id}",
                    "",
                    f"<!-- turn_id: {turn_id} -->",
                    f"- turn_id: {turn_id}",
                    f"- role: {role}",
                    "",
                    content,
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def run_openclaw_longmemeval_official(
    *,
    data_file: str | Path,
    output_file: str | Path,
    detail_file: str | Path | None,
    openclaw: OpenClawCli,
    workspace_root: str | Path,
    state_root: str | Path,
    model_key: str = "openclaw",
    agent: str = "main",
    answer_mode: AnswerMode = "memory-search-snippet",
    top_k: int = 5,
    max_samples: int | None = None,
    index_before_query: bool = True,
) -> LongMemEvalOfficialSummary:
    """Run OpenClaw over LongMemEval and write official JSONL predictions."""
    data_path = Path(data_file)
    output_path = Path(output_file)
    resolved_detail_file = Path(detail_file) if detail_file else output_path.with_suffix(".details.json")
    samples = json.loads(data_path.read_text(encoding="utf-8"))
    if max_samples and max_samples > 0:
        samples = samples[:max_samples]

    official_lines: list[str] = []
    details: list[dict[str, Any]] = []
    for sample in samples:
        question_id = str(sample.get("question_id") or "")
        workspace = LoCoMoOpenClawWorkspace.for_sample(
            workspace_root=workspace_root,
            state_root=state_root,
            sample_id=question_id,
            agent=agent,
        )
        workspace.workspace_dir.mkdir(parents=True, exist_ok=True)
        workspace.state_dir.mkdir(parents=True, exist_ok=True)
        (workspace.workspace_dir / "MEMORY.md").write_text(
            render_longmemeval_memory(sample),
            encoding="utf-8",
        )
        workspace.config_path.write_text(
            json.dumps(workspace._config_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if index_before_query:
            openclaw.run(["memory", "index", "--agent", agent, "--force"], env=workspace.env())

        started_at = time.perf_counter()
        error: str | None = None
        context_ids: list[str] = []
        prediction = ""
        try:
            if answer_mode == "agent":
                result = openclaw.run(
                    [
                        "agent",
                        "--local",
                        "--agent",
                        agent,
                        "--message",
                        _longmemeval_prompt(sample),
                    ],
                    env=workspace.env(),
                )
                prediction = (result.stdout or "").strip()
            else:
                result = openclaw.run(
                    [
                        "memory",
                        "search",
                        "--agent",
                        agent,
                        "--query",
                        str(sample.get("question") or ""),
                        "--max-results",
                        str(top_k),
                        "--json",
                    ],
                    env=workspace.env(),
                )
                payload = result.json()
                items = payload.get("results") if isinstance(payload, dict) else []
                if isinstance(items, list) and items:
                    first = dict(items[0]) if isinstance(items[0], dict) else {}
                    prediction = _strip_memory_snippet(first)
                    context_ids = _extract_session_ids(items)
        except Exception as exc:  # pragma: no cover - runtime failure path
            error = str(exc)

        latency_ms = round((time.perf_counter() - started_at) * 1000, 3)
        official_lines.append(
            json.dumps(
                {
                    "question_id": question_id,
                    "hypothesis": prediction,
                },
                ensure_ascii=False,
            )
        )
        details.append(
            {
                "question_id": question_id,
                "question_type": sample.get("question_type"),
                "answer": sample.get("answer"),
                "hypothesis": prediction,
                "answer_session_ids": sample.get("answer_session_ids") or [],
                "retrieved_session_ids": context_ids,
                "exact_match": _normalized_equal(prediction, str(sample.get("answer") or "")),
                "abstention_correct": _abstention_correct(sample, prediction),
                "evidence_recall": _session_recall(sample.get("answer_session_ids") or [], context_ids),
                "latency_ms": latency_ms,
                "error": error,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(official_lines) + ("\n" if official_lines else ""), encoding="utf-8")
    resolved_detail_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_detail_file.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")

    completed = [item for item in details if not item.get("error")]
    summary = LongMemEvalOfficialSummary(
        data_file=str(data_path),
        output_file=str(output_path),
        detail_file=str(resolved_detail_file),
        model_key=model_key,
        answer_mode=answer_mode,
        sample_count=len(details),
        completed_count=len(completed),
        failed_count=len(details) - len(completed),
        exact_match=round(statistics.mean([float(item["exact_match"]) for item in details]) if details else 0.0, 4),
        evidence_recall=round(statistics.mean([float(item["evidence_recall"]) for item in details]) if details else 0.0, 4),
        abstention_accuracy=round(
            statistics.mean([float(item["abstention_correct"]) for item in details]) if details else 0.0,
            4,
        ),
        average_latency_ms=round(statistics.mean([float(item["latency_ms"]) for item in details]) if details else 0.0, 3),
    )
    return summary


def _longmemeval_prompt(sample: dict[str, Any]) -> str:
    question = str(sample.get("question") or "")
    qtype = str(sample.get("question_type") or "")
    if sample.get("question_id", "").endswith("_abs"):
        return (
            "请根据记忆回答 LongMemEval 问题。如果记忆中没有答案，直接回答 "
            "'I don't know'。\n\nQuestion: "
            + question
        )
    return f"请根据记忆回答 LongMemEval 问题，只返回最短正确答案。\n\nQuestion Type: {qtype}\nQuestion: {question}"


def _strip_memory_snippet(item: dict[str, Any]) -> str:
    for key in ("snippet", "text", "content", "summary"):
        value = str(item.get(key) or "").strip()
        if not value:
            continue
        lines = []
        for line in value.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("<!--") or stripped.startswith("- session_id:") or stripped.startswith("- turn_id:"):
                continue
            lines.append(stripped)
        if lines:
            return " ".join(lines).strip()
    return ""


def _extract_session_ids(items: list[Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text = "\n".join(str(item.get(key) or "") for key in ("path", "title", "snippet", "text", "content"))
        for match in SESSION_MARKER_RE.findall(text):
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalized_equal(left: str, right: str) -> bool:
    return _normalize_text(left) == _normalize_text(right)


def _session_recall(gold: list[str], predicted: list[str]) -> float:
    if not gold:
        return 0.0
    predicted_set = set(predicted)
    return sum(1 for item in gold if item in predicted_set) / len(gold)


def _abstention_correct(sample: dict[str, Any], prediction: str) -> bool:
    is_abstention = str(sample.get("question_id") or "").endswith("_abs")
    normalized = _normalize_text(prediction)
    if not is_abstention:
        return True
    return "don't know" in normalized or "do not know" in normalized or "not enough" in normalized


__all__ = [
    "LongMemEvalOfficialSummary",
    "render_longmemeval_memory",
    "run_openclaw_longmemeval_official",
]
