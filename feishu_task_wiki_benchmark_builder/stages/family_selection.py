from __future__ import annotations

from typing import Any

from ..config import FORMAL_FAMILY_IDS
from ..schemas import validate_family_selection
from .common import normalize_seed


def select_family(*, seed: int | None, requested_family_id: str | None = None) -> dict[str, Any]:
    normalized_seed = normalize_seed(seed)
    if requested_family_id is not None:
        payload = {
            "family_id": requested_family_id,
            "selection_mode": "explicit",
            "selection_reason": "用户显式指定 family，跳过随机选择。",
            "seed": normalized_seed,
        }
        return validate_family_selection(payload)
    index = normalized_seed % len(FORMAL_FAMILY_IDS)
    family_id = FORMAL_FAMILY_IDS[index]
    payload = {
        "family_id": family_id,
        "selection_mode": "seeded_deterministic",
        "selection_reason": "未指定 family，按 seed 做 deterministic 选择。",
        "seed": normalized_seed,
    }
    return validate_family_selection(payload)
