from __future__ import annotations

from typing import Any

from ..schemas import validate_case_spec
from .common import build_case_id, build_task_id, normalize_seed


def build_case_spec(
    *,
    family_id: str,
    difficulty: str,
    seed: int | None,
    comparison_target: str,
) -> dict[str, Any]:
    normalized_seed = normalize_seed(seed)
    payload = {
        "case_id": build_case_id(normalized_seed, family_id),
        "task_id": build_task_id(normalized_seed),
        "seed": normalized_seed,
        "difficulty": difficulty,
        "comparison_target": comparison_target,
        "family_id": family_id,
    }
    return validate_case_spec(payload)
