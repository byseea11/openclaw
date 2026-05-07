"""OpenClaw runner for LoCoMo's original QA format.
This module deliberately avoids the shared MemoryEvalDataset abstraction. It
keeps LoCoMo's native sample/qa shape, writes each conversation into an
OpenClaw workspace, runs OpenClaw, and writes a LoCoMo-style output JSON with
`<model>_prediction`, `<model>_prediction_context`, and `<model>_f1` fields.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from eval_old.openclaw.cli import OpenClawCli
from eval_old.openclaw.workspace import safe_name

DIALOG_ID_RE = re.compile(r"\bD\d+:\d+\b")
SESSION_ID_RE = re.compile(r"\bS?(\d+)\b")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)
PUNCT_RE = re.compile(r"[^\w\s\u4e00-\u9fff]", re.UNICODE)
ARTICLE_RE = re.compile(r"\b(a|an|the|and)\b", re.IGNORECASE)


AnswerMode = Literal["agent", "memory-search-snippet"]


@dataclass(frozen=True)
class LoCoMoOfficialSummary:
    """Aggregate LoCoMo official-format result summary."""

    data_file: str
    output_file: str
    stats_file: str
    model_key: str
    answer_mode: str
    sample_count: int
    qa_count: int
    completed_qa_count: int
    failed_qa_count: int
    average_f1: float
    average_recall: float
    average_latency_ms: float
    category_f1: dict[str, float]
    category_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_openclaw_locomo_official(
    *,
    data_file: str | Path,
    output_file: str | Path,
    stats_file: str | Path | None = None,
    openclaw: OpenClawCli,
    workspace_root: str | Path,
    state_root: str | Path,
    model_key: str = "openclaw",
    agent: str = "main",
    answer_mode: AnswerMode = "memory-search-snippet",
    top_k: int = 5,
    max_samples: int | None = None,
    max_qas_per_sample: int | None = None,
    index_before_query: bool = True,
) -> LoCoMoOfficialSummary:
    """Run OpenClaw over LoCoMo samples and write native LoCoMo-style outputs."""
    data_path = Path(data_file)
    output_path = Path(output_file)
    resolved_stats_file = Path(stats_file) if stats_file else output_path.with_name(
        output_path.stem + "_stats.json"
    )
    samples = json.loads(data_path.read_text(encoding="utf-8"))
    if max_samples and max_samples > 0:
        samples = samples[:max_samples]

    prediction_key = f"{model_key}_prediction"
    context_key = f"{prediction_key}_context"
    f1_key = f"{model_key}_f1"
    recall_key = f"{model_key}_recall"
    latency_key = f"{model_key}_latency_ms"
    error_key = f"{model_key}_error"

    out_samples: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "sample")
        workspace = LoCoMoOpenClawWorkspace.for_sample(
            workspace_root=workspace_root,
            state_root=state_root,
            sample_id=sample_id,
            agent=agent,
        )
        workspace.prepare(sample)
        if index_before_query:
            openclaw.run(["memory", "index", "--agent", agent, "--force"], env=workspace.env())

        out_sample = {"sample_id": sample_id, "qa": [dict(item) for item in sample.get("qa", [])]}
        qas = out_sample["qa"]
        if max_qas_per_sample and max_qas_per_sample > 0:
            qas = qas[:max_qas_per_sample]
            out_sample["qa"] = qas

        for qa in qas:
            started_at = time.perf_counter()
            try:
                answer, context_ids = _answer_question(
                    openclaw=openclaw,
                    workspace=workspace,
                    qa=qa,
                    agent=agent,
                    answer_mode=answer_mode,
                    top_k=top_k,
                )
                qa[prediction_key] = answer
                qa[context_key] = context_ids
                qa[f1_key] = round(_locomo_f1_for_qa(qa, answer), 3)
                qa[recall_key] = round(_context_recall(qa.get("evidence") or [], context_ids), 3)
            except Exception as exc:
                qa[prediction_key] = ""
                qa[context_key] = []
                qa[f1_key] = 0.0
                qa[recall_key] = 0.0
                qa[error_key] = str(exc)
            qa[latency_key] = round((time.perf_counter() - started_at) * 1000, 3)
        out_samples.append(out_sample)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out_samples, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = _summarize_outputs(
        data_file=str(data_path),
        output_file=str(output_path),
        stats_file=str(resolved_stats_file),
        model_key=model_key,
        answer_mode=answer_mode,
        samples=out_samples,
        f1_key=f1_key,
        recall_key=recall_key,
        latency_key=latency_key,
        error_key=error_key,
    )
    resolved_stats_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_stats_file.write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


@dataclass(frozen=True)
class LoCoMoOpenClawWorkspace:
    """Per-sample OpenClaw state for LoCoMo official runs."""

    workspace_dir: Path
    state_dir: Path
    agent: str = "main"

    @property
    def config_path(self) -> Path:
        return self.state_dir / "openclaw.json"

    @classmethod
    def for_sample(
        cls,
        *,
        workspace_root: str | Path,
        state_root: str | Path,
        sample_id: str,
        agent: str = "main",
    ) -> LoCoMoOpenClawWorkspace:
        sample_name = safe_name(sample_id)
        return cls(
            workspace_dir=Path(workspace_root).expanduser().resolve() / sample_name / "workspace",
            state_dir=Path(state_root).expanduser().resolve() / sample_name / "state",
            agent=agent,
        )

    def env(self) -> dict[str, str]:
        return {
            "OPENCLAW_STATE_DIR": str(self.state_dir),
            "OPENCLAW_CONFIG_PATH": str(self.config_path),
        }

    def prepare(self, sample: dict[str, Any]) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "MEMORY.md").write_text(
            render_locomo_memory(sample),
            encoding="utf-8",
        )
        self.config_path.write_text(
            json.dumps(self._config_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _config_payload(self) -> dict[str, Any]:
        return {
            "agents": {
                "defaults": {
                    "workspace": str(self.workspace_dir),
                    "memorySearch": {
                        "enabled": True,
                        "fallback": "none",
                        "sync": {
                            "watch": False,
                        },
                        "query": {
                            "maxResults": 20,
                        },
                    },
                },
                "list": [
                    {
                        "id": self.agent,
                        "workspace": str(self.workspace_dir),
                    }
                ],
            },
            "plugins": {
                "entries": {
                    "memory-core": {
                        "enabled": True,
                    }
                },
                "slots": {
                    "memory": "memory-core",
                }
            },
        }


def render_locomo_memory(sample: dict[str, Any]) -> str:
    """Render LoCoMo's original conversation object as OpenClaw Markdown memory."""
    conversation = dict(sample.get("conversation") or {})
    speaker_a = str(conversation.get("speaker_a") or "speaker_a")
    speaker_b = str(conversation.get("speaker_b") or "speaker_b")
    lines = [
        "# LoCoMo Conversation Memory",
        "",
        f"- sample_id: {sample.get('sample_id', '')}",
        f"- speaker_a: {speaker_a}",
        f"- speaker_b: {speaker_b}",
        "",
    ]
    for session_num in _session_numbers(conversation):
        session_key = f"session_{session_num}"
        session_date = str(conversation.get(f"{session_key}_date_time") or "")
        lines.extend([f"## Session {session_num}", "", f"- session_id: S{session_num}"])
        if session_date:
            lines.append(f"- date: {session_date}")
        lines.append("")
        for turn in conversation.get(session_key) or []:
            dia_id = str(turn.get("dia_id") or "").strip()
            speaker = str(turn.get("speaker") or "").strip()
            text = str(turn.get("text") or "").strip()
            if not dia_id and not text:
                continue
            lines.extend(
                [
                    f"### Dialog {dia_id or 'unknown'}",
                    "",
                    f"<!-- turn_id: {dia_id} -->",
                    f"- dia_id: {dia_id}",
                    f"- speaker: {speaker}",
                    f"- session_id: S{session_num}",
                ]
            )
            caption = str(turn.get("blip_caption") or "").strip()
            if caption:
                lines.append(f"- image_caption: {caption}")
            lines.extend(["", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _session_numbers(conversation: dict[str, Any]) -> list[int]:
    numbers: list[int] = []
    for key in conversation:
        if key.startswith("session_") and key.count("_") == 1:
            try:
                numbers.append(int(key.split("_", 1)[1]))
            except ValueError:
                continue
    return sorted(numbers)


def _answer_question(
    *,
    openclaw: OpenClawCli,
    workspace: LoCoMoOpenClawWorkspace,
    qa: dict[str, Any],
    agent: str,
    answer_mode: AnswerMode,
    top_k: int,
) -> tuple[str, list[str]]:
    if answer_mode == "agent":
        return _answer_with_agent(
            openclaw=openclaw,
            workspace=workspace,
            qa=qa,
            agent=agent,
        )
    return _answer_with_memory_search(
        openclaw=openclaw,
        workspace=workspace,
        qa=qa,
        agent=agent,
        top_k=top_k,
    )


def _answer_with_memory_search(
    *,
    openclaw: OpenClawCli,
    workspace: LoCoMoOpenClawWorkspace,
    qa: dict[str, Any],
    agent: str,
    top_k: int,
) -> tuple[str, list[str]]:
    result = openclaw.run(
        [
            "memory",
            "search",
            "--agent",
            agent,
            "--query",
            _question_for_locomo(qa),
            "--max-results",
            str(top_k),
            "--json",
        ],
        env=workspace.env(),
    )
    payload = result.json()
    items = _search_items(payload)
    context_ids = _context_ids_from_search_items(items)
    answer = _snippet_answer(items)
    return answer, context_ids


def _answer_with_agent(
    *,
    openclaw: OpenClawCli,
    workspace: LoCoMoOpenClawWorkspace,
    qa: dict[str, Any],
    agent: str,
) -> tuple[str, list[str]]:
    prompt = (
        "Answer the LoCoMo memory question using OpenClaw memory. "
        "First use memory_search and memory_get if needed. "
        "Return only the shortest supported answer; if the answer is not in memory, "
        "say 'No information available'.\n\n"
        f"Question: {_question_for_locomo(qa)}"
    )
    result = openclaw.run(
        ["agent", "--local", "--agent", agent, "--message", prompt],
        env=workspace.env(),
    )
    return (result.stdout or "").strip(), []


def _question_for_locomo(qa: dict[str, Any]) -> str:
    question = str(qa.get("question") or "")
    if int(qa.get("category", 0) or 0) == 2:
        return question + " Use DATE of CONVERSATION to answer with an approximate date."
    if int(qa.get("category", 0) or 0) == 5:
        return question + " If not mentioned in the conversation, answer 'No information available'."
    return question


def _search_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    value = payload.get("results")
    return [dict(item) for item in value] if isinstance(value, list) else []


def _context_ids_from_search_items(items: list[dict[str, Any]]) -> list[str]:
    context_ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = "\n".join(
            str(item.get(key) or "")
            for key in ("path", "title", "snippet", "text", "content")
        )
        for match in DIALOG_ID_RE.findall(text):
            if match not in seen:
                seen.add(match)
                context_ids.append(match)
    return context_ids


def _snippet_answer(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    first = items[0]
    for key in ("snippet", "text", "content", "summary"):
        value = str(first.get(key) or "").strip()
        if value:
            return _strip_metadata_lines(value)
    return ""


def _strip_metadata_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.startswith("- dia_id:") or stripped.startswith("- speaker:"):
            continue
        if stripped.startswith("- session_id:"):
            continue
        lines.append(stripped)
    return " ".join(lines)


def _normalize_answer(text: str | int | float | None) -> str:
    value = str(text or "").lower()
    value = ARTICLE_RE.sub(" ", value)
    value = PUNCT_RE.sub(" ", value)
    return " ".join(value.split())


def _tokens(text: str | int | float | None) -> list[str]:
    return TOKEN_RE.findall(_normalize_answer(text))


def _f1_score(prediction: str, gold: str | int | float) -> float:
    pred_tokens = _tokens(prediction)
    gold_tokens = _tokens(gold)
    if not pred_tokens and not gold_tokens:
        return 1.0
    if not pred_tokens or not gold_tokens:
        return 0.0
    pred_counts = Counter(pred_tokens)
    gold_counts = Counter(gold_tokens)
    overlap = sum((pred_counts & gold_counts).values())
    if overlap <= 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return (2 * precision * recall) / (precision + recall)


def _multi_answer_f1(prediction: str, gold: str | int | float) -> float:
    predictions = [item.strip() for item in str(prediction or "").split(",") if item.strip()]
    golds = [item.strip() for item in str(gold or "").split(",") if item.strip()]
    if not predictions or not golds:
        return _f1_score(prediction, gold)
    return statistics.mean(max(_f1_score(prediction_part, gold_part) for prediction_part in predictions) for gold_part in golds)


def _locomo_f1_for_qa(qa: dict[str, Any], prediction: str) -> float:
    category = int(qa.get("category", 0) or 0)
    answer = qa.get("answer", "")
    if category in {2, 3, 4}:
        if category == 3:
            answer = str(answer).split(";")[0].strip()
        return _f1_score(prediction, answer)
    if category == 1:
        return _multi_answer_f1(prediction, answer)
    if category == 5:
        lowered = prediction.lower()
        return float("no information available" in lowered or "not mentioned" in lowered)
    return _f1_score(prediction, answer)


def _context_recall(gold_evidence: list[Any], context_ids: list[str]) -> float:
    gold = {str(item).replace("(", "").replace(")", "") for item in gold_evidence if str(item).strip()}
    if not gold:
        return 1.0
    retrieved = set(context_ids)
    return sum(item in retrieved for item in gold) / len(gold)


def _summarize_outputs(
    *,
    data_file: str,
    output_file: str,
    stats_file: str,
    model_key: str,
    answer_mode: str,
    samples: list[dict[str, Any]],
    f1_key: str,
    recall_key: str,
    latency_key: str,
    error_key: str,
) -> LoCoMoOfficialSummary:
    f1_values: list[float] = []
    recall_values: list[float] = []
    latency_values: list[float] = []
    category_values: dict[str, list[float]] = {}
    failed = 0
    for sample in samples:
        for qa in sample.get("qa", []):
            category = str(qa.get("category", "unknown"))
            f1_value = float(qa.get(f1_key) or 0.0)
            recall_value = float(qa.get(recall_key) or 0.0)
            latency_value = float(qa.get(latency_key) or 0.0)
            f1_values.append(f1_value)
            recall_values.append(recall_value)
            latency_values.append(latency_value)
            category_values.setdefault(category, []).append(f1_value)
            if error_key in qa:
                failed += 1
    qa_count = len(f1_values)
    return LoCoMoOfficialSummary(
        data_file=data_file,
        output_file=output_file,
        stats_file=stats_file,
        model_key=model_key,
        answer_mode=answer_mode,
        sample_count=len(samples),
        qa_count=qa_count,
        completed_qa_count=qa_count - failed,
        failed_qa_count=failed,
        average_f1=round(statistics.mean(f1_values), 4) if f1_values else 0.0,
        average_recall=round(statistics.mean(recall_values), 4) if recall_values else 0.0,
        average_latency_ms=round(statistics.mean(latency_values), 3) if latency_values else 0.0,
        category_f1={
            category: round(statistics.mean(values), 4)
            for category, values in sorted(category_values.items())
        },
        category_counts={category: len(values) for category, values in sorted(category_values.items())},
    )
