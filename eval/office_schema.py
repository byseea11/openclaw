"""Office-memory dataset adapters used by enterprise memory evals.
The schema mirrors the three-layer plan in memory.md:

- RawOfficeEvent: source event captured from Feishu/docs/tasks/tools
- MemoryEvidence: normalized, retrievable proposition with provenance
- EvalCase: query + gold evidence ids used by the harness
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.memory_harness import MemoryEvalDataset, MemoryEvalQuery, MemoryEvalSample


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def load_jsonl_objects(path: str | Path) -> list[dict[str, Any]]:
    """Load a UTF-8 JSONL file into dictionaries."""
    file_path = Path(path)
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError(f"{file_path}:{line_no} must contain a JSON object")
        rows.append(value)
    return rows


@dataclass(frozen=True)
class RawOfficeEvent:
    """Raw office event captured before memory extraction."""

    event_id: str
    source_type: str
    source_id: str = ""
    source_name: str = ""
    timestamp: str = ""
    actor: dict[str, Any] = field(default_factory=dict)
    content_type: str = "text"
    content: Any = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawOfficeEvent:
        known = {
            "event_id",
            "source_type",
            "source_id",
            "source_name",
            "timestamp",
            "actor",
            "content_type",
            "content",
        }
        return cls(
            event_id=str(data["event_id"]),
            source_type=str(data.get("source_type") or ""),
            source_id=str(data.get("source_id") or ""),
            source_name=str(data.get("source_name") or ""),
            timestamp=str(data.get("timestamp") or ""),
            actor=dict(data.get("actor") or {}),
            content_type=str(data.get("content_type") or "text"),
            content=data.get("content", ""),
            metadata={key: value for key, value in data.items() if key not in known},
        )


@dataclass(frozen=True)
class MemoryEvidence:
    """Normalized memory proposition with source, state, and retrieval metadata."""

    memory_id: str
    project_id: str
    memory_type: str
    proposition: str
    summary: str = ""
    entities: list[str] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    time: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    supersedes: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    retrieval_keys: list[str] = field(default_factory=list)
    importance: float = 0.0
    confidence: float = 0.0
    visibility: str = "internal"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEvidence:
        known = {
            "memory_id",
            "project_id",
            "memory_type",
            "proposition",
            "summary",
            "entities",
            "participants",
            "departments",
            "relations",
            "time",
            "status",
            "supersedes",
            "source_refs",
            "retrieval_keys",
            "importance",
            "confidence",
            "visibility",
        }
        return cls(
            memory_id=str(data["memory_id"]),
            project_id=str(data.get("project_id") or "default"),
            memory_type=str(data.get("memory_type") or "fact"),
            proposition=str(data.get("proposition") or ""),
            summary=str(data.get("summary") or ""),
            entities=_string_list(data.get("entities")),
            participants=_string_list(data.get("participants")),
            departments=_string_list(data.get("departments")),
            relations=[dict(item) for item in _as_list(data.get("relations")) if isinstance(item, dict)],
            time=dict(data.get("time") or {}),
            status=str(data.get("status") or "active"),
            supersedes=_string_list(data.get("supersedes")),
            source_refs=[dict(item) for item in _as_list(data.get("source_refs")) if isinstance(item, dict)],
            retrieval_keys=_string_list(data.get("retrieval_keys")),
            importance=float(data.get("importance") or 0.0),
            confidence=float(data.get("confidence") or 0.0),
            visibility=str(data.get("visibility") or "internal"),
            metadata={key: value for key, value in data.items() if key not in known},
        )

    def to_history_turn(self) -> dict[str, Any]:
        """Render evidence as a harness history turn keyed by memory_id."""
        lines = [
            f"[memory_id: {self.memory_id}]",
            f"[memory_type: {self.memory_type}]",
            f"[status: {self.status}]",
            f"[project_id: {self.project_id}]",
        ]
        if self.time:
            lines.append(f"[time: {json.dumps(self.time, ensure_ascii=False, sort_keys=True)}]")
        if self.participants:
            lines.append(f"[participants: {', '.join(self.participants)}]")
        if self.entities:
            lines.append(f"[entities: {', '.join(self.entities)}]")
        if self.retrieval_keys:
            lines.append(f"[retrieval_keys: {', '.join(self.retrieval_keys)}]")
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        lines.append(f"Proposition: {self.proposition}")

        return {
            "turn_id": self.memory_id,
            "role": "system",
            "speaker": "memory",
            "content": "\n".join(lines),
            "metadata": {
                "source": "memory_evidence",
                "project_id": self.project_id,
                "memory_type": self.memory_type,
                "status": self.status,
                "visibility": self.visibility,
                "source_refs": self.source_refs,
                "importance": self.importance,
                "confidence": self.confidence,
            },
        }


@dataclass(frozen=True)
class EvalCase:
    """One enterprise memory eval query and its gold evidence."""

    case_id: str
    project_id: str
    query: str
    ability: str
    gold_answer: str = ""
    gold_memory_ids: list[str] = field(default_factory=list)
    must_mention: list[str] = field(default_factory=list)
    must_not_mention: list[str] = field(default_factory=list)
    should_abstain: bool = False
    answer_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        known = {
            "case_id",
            "project_id",
            "query",
            "ability",
            "gold_answer",
            "gold_memory_ids",
            "must_mention",
            "must_not_mention",
            "should_abstain",
            "answer_type",
        }
        return cls(
            case_id=str(data["case_id"]),
            project_id=str(data.get("project_id") or "default"),
            query=str(data.get("query") or ""),
            ability=str(data.get("ability") or "memory_recall"),
            gold_answer=str(data.get("gold_answer") or ""),
            gold_memory_ids=_string_list(data.get("gold_memory_ids")),
            must_mention=_string_list(data.get("must_mention")),
            must_not_mention=_string_list(data.get("must_not_mention")),
            should_abstain=bool(data.get("should_abstain", False)),
            answer_type=str(data.get("answer_type") or ""),
            metadata={key: value for key, value in data.items() if key not in known},
        )

    def to_query(self) -> MemoryEvalQuery:
        return MemoryEvalQuery(
            id=self.case_id,
            prompt=self.query,
            gold_answer=self.gold_answer,
            gold_turn_ids=self.gold_memory_ids,
            question_type=self.ability,
            requires_tool_memory=self.ability == "tool_result_reuse",
            metadata={
                "source": "office_eval_case",
                "project_id": self.project_id,
                "must_mention": self.must_mention,
                "must_not_mention": self.must_not_mention,
                "should_abstain": self.should_abstain,
                "answer_type": self.answer_type,
                **self.metadata,
            },
        )


def load_office_memory_eval_dataset(
    *,
    evidence_path: str | Path,
    eval_cases_path: str | Path,
    name: str | None = None,
) -> MemoryEvalDataset:
    """Adapt MemoryEvidence + EvalCase JSONL files into the harness schema."""
    evidence = [MemoryEvidence.from_dict(row) for row in load_jsonl_objects(evidence_path)]
    cases = [EvalCase.from_dict(row) for row in load_jsonl_objects(eval_cases_path)]

    evidence_by_project: dict[str, list[MemoryEvidence]] = {}
    cases_by_project: dict[str, list[EvalCase]] = {}
    for item in evidence:
        evidence_by_project.setdefault(item.project_id, []).append(item)
    for item in cases:
        cases_by_project.setdefault(item.project_id, []).append(item)

    samples: list[MemoryEvalSample] = []
    for project_id in sorted(set(evidence_by_project) | set(cases_by_project)):
        project_evidence = evidence_by_project.get(project_id, [])
        project_cases = cases_by_project.get(project_id, [])
        samples.append(
            MemoryEvalSample(
                id=project_id,
                history=[item.to_history_turn() for item in project_evidence],
                queries=[item.to_query() for item in project_cases],
                metadata={
                    "source": "office_memory",
                    "project_id": project_id,
                    "memory_evidence_count": len(project_evidence),
                    "eval_case_count": len(project_cases),
                },
            )
        )

    return MemoryEvalDataset(
        name=name or Path(eval_cases_path).stem,
        samples=samples,
        metadata={
            "source": "office_memory",
            "evidence_path": str(evidence_path),
            "eval_cases_path": str(eval_cases_path),
        },
    )
