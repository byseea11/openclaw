"""Evaluation harness for long-horizon memory experiments."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_ARTICLES_RE = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s\u4e00-\u9fff]", re.UNICODE)
_LOCOMO_QUESTION_TYPES = {
    1: "multi_hop",
    2: "temporal",
    3: "commonsense_world_knowledge",
    4: "single_hop",
    5: "adversarial",
}


def _coerce_turn_ids(values: list[str | int] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            result.append(text)
    return result


def normalize_answer(text: str | None) -> str:
    """Normalize answers for EM/F1 comparison."""
    value = (text or "").strip().lower()
    value = _ARTICLES_RE.sub(" ", value)
    value = _PUNCT_RE.sub(" ", value)
    value = " ".join(value.split())
    return value


def _answer_tokens(text: str | None) -> list[str]:
    normalized = normalize_answer(text)
    return _TOKEN_RE.findall(normalized)


def answer_exact_match(prediction: str | None, gold_answer: str | None) -> float:
    """Return 1.0 when normalized answers match exactly, else 0.0."""
    return float(normalize_answer(prediction) == normalize_answer(gold_answer))


def answer_f1(prediction: str | None, gold_answer: str | None) -> float:
    """Token-level F1 score between prediction and gold answer."""
    pred_tokens = _answer_tokens(prediction)
    gold_tokens = _answer_tokens(gold_answer)
    if not pred_tokens and not gold_tokens:
        return 1.0
    if not pred_tokens or not gold_tokens:
        return 0.0

    pred_counts: dict[str, int] = {}
    gold_counts: dict[str, int] = {}
    for token in pred_tokens:
        pred_counts[token] = pred_counts.get(token, 0) + 1
    for token in gold_tokens:
        gold_counts[token] = gold_counts.get(token, 0) + 1

    overlap = 0
    for token, pred_count in pred_counts.items():
        overlap += min(pred_count, gold_counts.get(token, 0))
    if overlap <= 0:
        return 0.0

    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return (2 * precision * recall) / (precision + recall)


def recall_at_k(
    predicted_turn_ids: list[str | int] | None,
    gold_turn_ids: list[str | int] | None,
    *,
    k: int,
) -> float:
    """Return fraction of gold evidence retrieved in top-k."""
    gold = set(_coerce_turn_ids(gold_turn_ids))
    if not gold:
        return 1.0
    predicted = _coerce_turn_ids(predicted_turn_ids)[: max(0, k)]
    if not predicted:
        return 0.0
    hits = len(gold & set(predicted))
    return hits / len(gold)


def oracle_hit_at_k(
    predicted_turn_ids: list[str | int] | None,
    gold_turn_ids: list[str | int] | None,
    *,
    k: int,
) -> float:
    """Return 1.0 when any gold evidence appears in top-k."""
    gold = set(_coerce_turn_ids(gold_turn_ids))
    if not gold:
        return 1.0
    predicted = _coerce_turn_ids(predicted_turn_ids)[: max(0, k)]
    return float(any(turn_id in gold for turn_id in predicted))


def reciprocal_rank(
    predicted_turn_ids: list[str | int] | None,
    gold_turn_ids: list[str | int] | None,
) -> float:
    """Return reciprocal rank of the first relevant retrieved item."""
    gold = set(_coerce_turn_ids(gold_turn_ids))
    if not gold:
        return 1.0
    for idx, turn_id in enumerate(_coerce_turn_ids(predicted_turn_ids), start=1):
        if turn_id in gold:
            return 1.0 / idx
    return 0.0


def gold_in_prompt(
    prompt_turn_ids: list[str | int] | None,
    gold_turn_ids: list[str | int] | None,
) -> float:
    """Return 1.0 when any gold evidence appears anywhere in the final prompt."""
    gold = set(_coerce_turn_ids(gold_turn_ids))
    if not gold:
        return 1.0
    prompt_turns = _coerce_turn_ids(prompt_turn_ids)
    return float(any(turn_id in gold for turn_id in prompt_turns))


def recall_over_all_kept_turns(
    prompt_turn_ids: list[str | int] | None,
    gold_turn_ids: list[str | int] | None,
) -> float:
    """Return evidence coverage across every turn kept in the final prompt."""
    gold = set(_coerce_turn_ids(gold_turn_ids))
    if not gold:
        return 1.0
    prompt_turns = set(_coerce_turn_ids(prompt_turn_ids))
    if not prompt_turns:
        return 0.0
    return len(gold & prompt_turns) / len(gold)


@dataclass(frozen=True)
class MemoryEvalQuery:
    """One memory-focused query associated with a long conversation."""

    id: str
    prompt: str
    gold_answer: str
    gold_turn_ids: list[str] = field(default_factory=list)
    question_type: str = ""
    requires_tool_memory: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEvalQuery:
        return cls(
            id=str(data["id"]),
            prompt=str(data["prompt"]),
            gold_answer=str(data.get("gold_answer", "")),
            gold_turn_ids=_coerce_turn_ids(data.get("gold_turn_ids")),
            question_type=str(data.get("question_type", "")),
            requires_tool_memory=bool(data.get("requires_tool_memory", False)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MemoryEvalSample:
    """One long-history sample plus its evaluation queries."""

    id: str
    history: list[dict[str, Any]]
    queries: list[MemoryEvalQuery]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEvalSample:
        queries = [MemoryEvalQuery.from_dict(item) for item in data.get("queries", [])]
        history = [dict(item) for item in data.get("history", [])]
        return cls(
            id=str(data["id"]),
            history=history,
            queries=queries,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MemoryEvalDataset:
    """A dataset of long-horizon memory samples."""

    name: str
    samples: list[MemoryEvalSample]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEvalDataset:
        raw_samples = data.get("samples")
        if raw_samples is None:
            raw_samples = data.get("items", [])
        samples = [MemoryEvalSample.from_dict(item) for item in raw_samples]
        return cls(
            name=str(data.get("name") or "memory-eval"),
            samples=samples,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RetrievalResult:
    """Retrieval-stage output for one query."""

    predicted_turn_ids: list[str] = field(default_factory=list)
    prompt_turn_ids: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnswerResult:
    """Answer-stage output for one query."""

    answer: str
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MemoryEvalMethod(Protocol):
    """Protocol implemented by retrieval/answer methods used in the harness."""

    name: str

    async def retrieve(
        self,
        *,
        sample: MemoryEvalSample,
        query: MemoryEvalQuery,
    ) -> RetrievalResult:
        """Return top-k retrieved turn IDs or evidence chunks."""

    async def answer(
        self,
        *,
        sample: MemoryEvalSample,
        query: MemoryEvalQuery,
        retrieval: RetrievalResult,
    ) -> AnswerResult:
        """Return the final answer and accounting signals for one query."""


@dataclass(frozen=True)
class MemoryEvalRecord:
    """Per-query evaluation result for one method."""

    method: str
    dataset_name: str
    sample_id: str
    query_id: str
    question_type: str
    requires_tool_memory: bool
    gold_turn_ids: list[str]
    predicted_turn_ids: list[str]
    prompt_turn_ids: list[str]
    recall_at_k: float
    oracle_hit_at_k: float
    reciprocal_rank: float
    gold_in_prompt: float
    recall_over_all_kept_turns: float
    exact_match: float
    f1: float
    retrieval_latency_ms: float
    answer_latency_ms: float
    total_latency_ms: float
    retrieval_prompt_tokens: int
    answer_prompt_tokens: int
    completion_tokens: int
    total_prompt_tokens: int
    cost: float
    gold_answer: str
    predicted_answer: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryEvalSummary:
    """Aggregate metrics for one evaluated method."""

    method: str
    dataset_name: str
    query_count: int
    metrics: dict[str, float]
    primary_metrics: dict[str, float] = field(default_factory=dict)
    auxiliary_metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryEvalReport:
    """Full evaluation report."""

    dataset_name: str
    recall_k: int
    records: list[MemoryEvalRecord]
    summaries: list[MemoryEvalSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "recall_k": self.recall_k,
            "records": [record.to_dict() for record in self.records],
            "summaries": [summary.to_dict() for summary in self.summaries],
        }


def load_memory_eval_dataset(path: str | Path) -> MemoryEvalDataset:
    """Load a memory-eval dataset from JSON or JSONL."""
    dataset_path = Path(path)
    raw = dataset_path.read_text(encoding="utf-8")
    if dataset_path.suffix.lower() == ".jsonl":
        samples = [MemoryEvalSample.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]
        return MemoryEvalDataset(name=dataset_path.stem, samples=samples)

    data = json.loads(raw)
    if isinstance(data, list):
        return MemoryEvalDataset(name=dataset_path.stem, samples=[MemoryEvalSample.from_dict(item) for item in data])
    return MemoryEvalDataset.from_dict(data)


def load_locomo_qa_dataset(path: str | Path) -> MemoryEvalDataset:
    """Adapt a LoCoMo QA JSON file into the local memory-eval schema."""
    dataset_path = Path(path)
    raw_samples = json.loads(dataset_path.read_text(encoding="utf-8"))

    samples: list[MemoryEvalSample] = []
    for sample in raw_samples:
        conversation = dict(sample.get("conversation") or {})
        session_summary_raw = dict(sample.get("session_summary") or {})
        observation_raw = dict(sample.get("observation") or {})
        speaker_a = str(conversation.get("speaker_a") or "speaker_a")
        speaker_b = str(conversation.get("speaker_b") or "speaker_b")
        history: list[dict[str, Any]] = []

        session_summaries: dict[str, str] = {}
        for key, value in session_summary_raw.items():
            if not key.startswith("session_") or not key.endswith("_summary"):
                continue
            session_key = key[: -len("_summary")]
            session_summaries[session_key] = str(value or "")

        session_observations: dict[str, list[str]] = {}
        observation_by_turn: dict[str, list[str]] = {}
        for key, value in observation_raw.items():
            if not key.startswith("session_") or not key.endswith("_observation"):
                continue
            session_key = key[: -len("_observation")]
            session_lines: list[str] = []
            for facts in dict(value or {}).values():
                for fact in list(facts or []):
                    if not isinstance(fact, list | tuple) or len(fact) < 2:
                        continue
                    fact_text = str(fact[0] or "").strip()
                    turn_id = str(fact[1] or "").strip()
                    if fact_text:
                        session_lines.append(fact_text)
                    if fact_text and turn_id:
                        observation_by_turn.setdefault(turn_id, []).append(fact_text)
            session_observations[session_key] = session_lines

        session_numbers: list[int] = []
        for key in conversation:
            if key.startswith("session_") and key.count("_") == 1:
                try:
                    session_numbers.append(int(key.split("_", 1)[1]))
                except ValueError:
                    continue
        session_numbers.sort()

        for session_num in session_numbers:
            session_key = f"session_{session_num}"
            session_turns = conversation.get(session_key) or []
            session_datetime = str(conversation.get(f"{session_key}_date_time") or "")
            for turn in session_turns:
                speaker = str(turn.get("speaker") or "")
                history.append({
                    "turn_id": str(turn.get("dia_id") or ""),
                    "role": "user" if speaker == speaker_a else "assistant" if speaker == speaker_b else "user",
                    "speaker": speaker,
                    "content": str(turn.get("text") or ""),
                    "session_id": session_key,
                    "session_datetime": session_datetime,
                    "metadata": {
                        "img_url": turn.get("img_url"),
                        "blip_caption": turn.get("blip_caption"),
                    },
                })

        queries: list[MemoryEvalQuery] = []
        for idx, qa in enumerate(sample.get("qa", [])):
            category = int(qa.get("category", 0) or 0)
            gold_answer = qa.get("answer")
            if gold_answer is None and category == 5:
                gold_answer = qa.get("adversarial_answer", "")
            queries.append(
                MemoryEvalQuery(
                    id=f"{sample['sample_id']}-q{idx}",
                    prompt=str(qa.get("question") or ""),
                    gold_answer=str(gold_answer or ""),
                    gold_turn_ids=_coerce_turn_ids(qa.get("evidence")),
                    question_type=_LOCOMO_QUESTION_TYPES.get(category, f"category_{category}"),
                    requires_tool_memory=False,
                    metadata={
                        "source": "locomo",
                        "category": category,
                        "adversarial_answer": qa.get("adversarial_answer"),
                    },
                )
            )

        samples.append(
            MemoryEvalSample(
                id=str(sample["sample_id"]),
                history=history,
                queries=queries,
                metadata={
                    "source": "locomo",
                    "speaker_a": speaker_a,
                    "speaker_b": speaker_b,
                    "session_summaries": session_summaries,
                    "session_observations": session_observations,
                    "observation_by_turn": observation_by_turn,
                    "event_summary": dict(sample.get("event_summary") or {}),
                },
            )
        )

    return MemoryEvalDataset(
        name=dataset_path.stem,
        samples=samples,
        metadata={"source": "locomo"},
    )


def aggregate_records(
    records: list[MemoryEvalRecord],
    *,
    dataset_name: str,
) -> list[MemoryEvalSummary]:
    """Aggregate record-level metrics by method."""
    grouped: dict[str, list[MemoryEvalRecord]] = {}
    for record in records:
        grouped.setdefault(record.method, []).append(record)

    summaries: list[MemoryEvalSummary] = []
    for method_name, method_records in grouped.items():
        count = len(method_records)
        primary_metrics = {
            "recall_at_k": sum(item.recall_at_k for item in method_records) / count,
            "oracle_hit_at_k": sum(item.oracle_hit_at_k for item in method_records) / count,
            "mrr": sum(item.reciprocal_rank for item in method_records) / count,
            "gold_in_prompt": sum(item.gold_in_prompt for item in method_records) / count,
            "recall_over_all_kept_turns": (
                sum(item.recall_over_all_kept_turns for item in method_records) / count
            ),
            "avg_retrieval_prompt_tokens": (
                sum(item.retrieval_prompt_tokens for item in method_records) / count
            ),
            "avg_answer_prompt_tokens": (
                sum(item.answer_prompt_tokens for item in method_records) / count
            ),
            "avg_total_prompt_tokens": sum(item.total_prompt_tokens for item in method_records) / count,
            "avg_retrieval_latency_ms": sum(item.retrieval_latency_ms for item in method_records) / count,
            "avg_answer_latency_ms": sum(item.answer_latency_ms for item in method_records) / count,
            "avg_total_latency_ms": sum(item.total_latency_ms for item in method_records) / count,
            "avg_completion_tokens": sum(item.completion_tokens for item in method_records) / count,
            "avg_cost": sum(item.cost for item in method_records) / count,
        }
        auxiliary_metrics = {
            "exact_match": sum(item.exact_match for item in method_records) / count,
            "f1": sum(item.f1 for item in method_records) / count,
        }
        metrics = {**primary_metrics, **auxiliary_metrics}
        summaries.append(
            MemoryEvalSummary(
                method=method_name,
                dataset_name=dataset_name,
                query_count=count,
                metrics=metrics,
                primary_metrics=primary_metrics,
                auxiliary_metrics=auxiliary_metrics,
            )
        )
    summaries.sort(key=lambda item: item.method)
    return summaries


def write_memory_eval_report(report: MemoryEvalReport, path: str | Path) -> None:
    """Persist a full report as JSON for later comparison."""
    out_path = Path(path)
    out_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class MemoryEvalHarness:
    """Run memory-focused retrieval + answer evaluation asynchronously."""

    def __init__(self, *, recall_k: int = 5):
        self.recall_k = max(1, recall_k)

    async def run(
        self,
        dataset: MemoryEvalDataset,
        methods: list[MemoryEvalMethod],
    ) -> MemoryEvalReport:
        """Evaluate all methods against every query in the dataset."""
        records: list[MemoryEvalRecord] = []
        for method in methods:
            for sample in dataset.samples:
                for query in sample.queries:
                    retrieval = await method.retrieve(sample=sample, query=query)
                    answer = await method.answer(
                        sample=sample,
                        query=query,
                        retrieval=retrieval,
                    )
                    record = self._build_record(
                        dataset_name=dataset.name,
                        method_name=method.name,
                        sample=sample,
                        query=query,
                        retrieval=retrieval,
                        answer=answer,
                    )
                    records.append(record)
        summaries = aggregate_records(records, dataset_name=dataset.name)
        return MemoryEvalReport(
            dataset_name=dataset.name,
            recall_k=self.recall_k,
            records=records,
            summaries=summaries,
        )

    def run_sync(
        self,
        dataset: MemoryEvalDataset,
        methods: list[MemoryEvalMethod],
    ) -> MemoryEvalReport:
        """Convenience wrapper for synchronous callers."""
        return asyncio.run(self.run(dataset, methods))

    def _build_record(
        self,
        *,
        dataset_name: str,
        method_name: str,
        sample: MemoryEvalSample,
        query: MemoryEvalQuery,
        retrieval: RetrievalResult,
        answer: AnswerResult,
    ) -> MemoryEvalRecord:
        predicted_turn_ids = _coerce_turn_ids(retrieval.predicted_turn_ids)
        prompt_turn_ids = _coerce_turn_ids(retrieval.prompt_turn_ids) or predicted_turn_ids
        gold_turn_ids = _coerce_turn_ids(query.gold_turn_ids)
        retrieval_prompt_tokens = max(0, int(retrieval.prompt_tokens))
        answer_prompt_tokens = max(0, int(answer.prompt_tokens))
        completion_tokens = max(0, int(answer.completion_tokens))
        metadata = {
            "sample_metadata": sample.metadata,
            "query_metadata": query.metadata,
            "retrieval_metadata": retrieval.metadata,
            "answer_metadata": answer.metadata,
            "retrieved_evidence": retrieval.evidence,
        }
        return MemoryEvalRecord(
            method=method_name,
            dataset_name=dataset_name,
            sample_id=sample.id,
            query_id=query.id,
            question_type=query.question_type,
            requires_tool_memory=query.requires_tool_memory,
            gold_turn_ids=gold_turn_ids,
            predicted_turn_ids=predicted_turn_ids,
            prompt_turn_ids=prompt_turn_ids,
            recall_at_k=recall_at_k(predicted_turn_ids, gold_turn_ids, k=self.recall_k),
            oracle_hit_at_k=oracle_hit_at_k(predicted_turn_ids, gold_turn_ids, k=self.recall_k),
            reciprocal_rank=reciprocal_rank(predicted_turn_ids, gold_turn_ids),
            gold_in_prompt=gold_in_prompt(prompt_turn_ids, gold_turn_ids),
            recall_over_all_kept_turns=recall_over_all_kept_turns(prompt_turn_ids, gold_turn_ids),
            exact_match=answer_exact_match(answer.answer, query.gold_answer),
            f1=answer_f1(answer.answer, query.gold_answer),
            retrieval_latency_ms=float(retrieval.latency_ms),
            answer_latency_ms=float(answer.latency_ms),
            total_latency_ms=float(retrieval.latency_ms) + float(answer.latency_ms),
            retrieval_prompt_tokens=retrieval_prompt_tokens,
            answer_prompt_tokens=answer_prompt_tokens,
            completion_tokens=completion_tokens,
            total_prompt_tokens=retrieval_prompt_tokens + answer_prompt_tokens,
            cost=float(answer.cost),
            gold_answer=query.gold_answer,
            predicted_answer=answer.answer,
            metadata=metadata,
        )
