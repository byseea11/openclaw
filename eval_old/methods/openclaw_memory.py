"""OpenClaw memory_search baseline for the shared memory eval harness."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval_old.memory_harness import AnswerResult, MemoryEvalQuery, MemoryEvalSample, RetrievalResult
from eval_old.openclaw.cli import OpenClawCli
from eval_old.openclaw.workspace import OpenClawEvalWorkspace

_ID_RE = re.compile(
    r"(?:turn_id|memory_id|evidence_id)\s*[:=]\s*[`'\"]?([A-Za-z0-9_.:-]+)",
    re.IGNORECASE,
)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _result_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "matches", "hits", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _candidate_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("turn_id", "memory_id", "evidence_id", "id", "source", "path", "title"):
        value = item.get(key)
        if value is not None:
            parts.append(str(value))
    for key in ("snippet", "text", "content", "summary", "body"):
        value = item.get(key)
        if value is not None:
            parts.append(str(value))
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key in ("turn_id", "memory_id", "evidence_id"):
            value = metadata.get(key)
            if value is not None:
                parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _extract_evidence_id(item: dict[str, Any]) -> str | None:
    for key in ("turn_id", "memory_id", "evidence_id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key in ("turn_id", "memory_id", "evidence_id"):
            value = metadata.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    match = _ID_RE.search(_candidate_text(item))
    if match:
        return match.group(1)
    return None


@dataclass(slots=True)
class OpenClawMemorySearchBaseline:
    """Evaluate OpenClaw's stock Markdown memory search against harness cases."""

    openclaw: OpenClawCli
    workspace_root: Path
    state_root: Path
    agent: str = "main"
    max_results: int = 5
    min_score: float | None = None
    index_before_search: bool = True
    answer_with_agent: bool = False
    agent_args: list[str] = field(default_factory=list)
    name: str = "openclaw_memory_search"
    _indexed_samples: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def from_paths(
        cls,
        *,
        openclaw_root: str | Path = "openclaw-main",
        workspace_root: str | Path = "outputs/openclaw_eval/workspaces",
        state_root: str | Path = "outputs/openclaw_eval/state",
        agent: str = "main",
        max_results: int = 5,
        min_score: float | None = None,
        index_before_search: bool = True,
        answer_with_agent: bool = False,
        timeout_seconds: float = 180.0,
    ) -> OpenClawMemorySearchBaseline:
        return cls(
            openclaw=OpenClawCli.from_path(openclaw_root, timeout_seconds=timeout_seconds),
            workspace_root=Path(workspace_root),
            state_root=Path(state_root),
            agent=agent,
            max_results=max_results,
            min_score=min_score,
            index_before_search=index_before_search,
            answer_with_agent=answer_with_agent,
        )

    async def retrieve(
        self,
        *,
        sample: MemoryEvalSample,
        query: MemoryEvalQuery,
    ) -> RetrievalResult:
        started_at = time.perf_counter()
        workspace = self._workspace_for(sample)
        workspace.prepare(sample)
        if self.index_before_search and sample.id not in self._indexed_samples:
            self.openclaw.run(
                ["memory", "index", "--agent", self.agent, "--force"],
                env=workspace.env(),
            )
            self._indexed_samples.add(sample.id)

        args = [
            "memory",
            "search",
            "--agent",
            self.agent,
            "--query",
            query.prompt,
            "--max-results",
            str(self.max_results),
            "--json",
        ]
        if self.min_score is not None:
            args.extend(["--min-score", str(self.min_score)])
        result = self.openclaw.run(args, env=workspace.env())
        payload = result.json()
        items = _result_items(payload)
        evidence = self._normalize_evidence(items)
        predicted = [item["turn_id"] for item in evidence if item.get("turn_id")]
        return RetrievalResult(
            predicted_turn_ids=predicted,
            prompt_turn_ids=predicted,
            evidence=evidence,
            latency_ms=(time.perf_counter() - started_at) * 1000,
            prompt_tokens=sum(_estimate_tokens(str(item.get("text") or "")) for item in evidence),
            metadata={
                "mode": self.name,
                "workspace": str(workspace.workspace_dir),
                "state_dir": str(workspace.state_dir),
                "raw_result_count": len(items),
                "command": result.args,
            },
        )

    async def answer(
        self,
        *,
        sample: MemoryEvalSample,
        query: MemoryEvalQuery,
        retrieval: RetrievalResult,
    ) -> AnswerResult:
        if not self.answer_with_agent:
            return AnswerResult(
                answer="",
                latency_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                cost=0.0,
                metadata={
                    "mode": "retrieval_only",
                    "reason": "Run with answer_with_agent=True to invoke `openclaw agent`.",
                },
            )

        workspace = self._workspace_for(sample)
        evidence_text = "\n".join(
            f"- [{item.get('turn_id', '')}] {item.get('text', '')}"
            for item in retrieval.evidence
        )
        prompt = (
            "# Retrieved Memory\n"
            f"{evidence_text or '(no retrieved memory)'}\n\n"
            "# User Question\n"
            f"{query.prompt}\n\n"
            "Answer briefly and cite only supported evidence."
        )
        started_at = time.perf_counter()
        result = self.openclaw.run(
            ["agent", "--message", prompt, *self.agent_args],
            env=workspace.env(),
        )
        answer = (result.stdout or "").strip()
        return AnswerResult(
            answer=answer,
            latency_ms=(time.perf_counter() - started_at) * 1000,
            prompt_tokens=_estimate_tokens(prompt),
            completion_tokens=_estimate_tokens(answer),
            cost=0.0,
            metadata={
                "mode": "openclaw_agent",
                "command": result.args,
                "stderr": result.stderr,
            },
        )

    def _workspace_for(self, sample: MemoryEvalSample) -> OpenClawEvalWorkspace:
        return OpenClawEvalWorkspace.for_sample(
            workspace_root=self.workspace_root,
            state_root=self.state_root,
            sample=sample,
            agent=self.agent,
        )

    @staticmethod
    def _normalize_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            evidence_id = _extract_evidence_id(item)
            if not evidence_id or evidence_id in seen:
                continue
            seen.add(evidence_id)
            text = _candidate_text(item).strip()
            evidence.append(
                {
                    "turn_id": evidence_id,
                    "text": text,
                    "score": float(item.get("score") or item.get("relevance") or 0.0),
                    "rank": index + 1,
                    "raw": json.loads(json.dumps(item, ensure_ascii=False, default=str)),
                }
            )
        return evidence
