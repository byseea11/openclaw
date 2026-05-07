from __future__ import annotations

from typing import Any

from ..config import FORMAL_FAMILY_IDS
from .common import normalize_seed


def build_dataset_generation_plan(*, dataset_size: int, seed: int | None, difficulty: str) -> dict[str, Any]:
    normalized_seed = normalize_seed(seed)
    quotas = {family_id: max(1, dataset_size // len(FORMAL_FAMILY_IDS)) for family_id in FORMAL_FAMILY_IDS}
    return {
        "generation_mode": "batch",
        "dataset_size": dataset_size,
        "seed": normalized_seed,
        "difficulty_policy": difficulty,
        "family_quotas": quotas,
        "family_selection_policy": "round_robin_by_seed",
    }
