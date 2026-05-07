"""Shared I/O and metric helpers for eval scorers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ARTICLES_RE = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s\u4e00-\u9fff]", re.UNICODE)


def ensure_parent_dir(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def dump_json(data: Any, path: str | Path) -> None:
    target = ensure_parent_dir(path)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_jsonl(rows: list[dict[str, Any]], path: str | Path) -> None:
    target = ensure_parent_dir(path)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if text:
        text += "\n"
    target.write_text(text, encoding="utf-8")


def normalize_answer(text: str | None) -> str:
    value = (text or "").strip().lower()
    value = _ARTICLES_RE.sub(" ", value)
    value = _PUNCT_RE.sub(" ", value)
    return " ".join(value.split())


def _answer_tokens(text: str | None) -> list[str]:
    return _TOKEN_RE.findall(normalize_answer(text))


def exact_match(prediction: str | None, gold: str | None) -> float:
    return float(normalize_answer(prediction) == normalize_answer(gold))


def answer_f1(prediction: str | None, gold: str | None) -> float:
    pred_tokens = _answer_tokens(prediction)
    gold_tokens = _answer_tokens(gold)
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
    for token, count in pred_counts.items():
        overlap += min(count, gold_counts.get(token, 0))
    if overlap <= 0:
        return 0.0

    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return (2 * precision * recall) / (precision + recall)
