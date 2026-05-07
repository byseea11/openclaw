from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..config import ACTIVE_CASE_FILENAME, CASES_DIRNAME

_LAST_GENERATED_DEFAULT_SEED: int | None = None


def generate_default_seed() -> int:
    global _LAST_GENERATED_DEFAULT_SEED
    candidate = int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
    if _LAST_GENERATED_DEFAULT_SEED is not None and candidate <= _LAST_GENERATED_DEFAULT_SEED:
        candidate = _LAST_GENERATED_DEFAULT_SEED + 1
    _LAST_GENERATED_DEFAULT_SEED = candidate
    return candidate


def normalize_seed(seed: int | None) -> int:
    return int(seed if seed is not None else generate_default_seed())


def build_case_id(seed: int, family_id: str) -> str:
    return f"case_{seed:04d}_{family_id}"


def build_task_id(seed: int) -> str:
    return f"FEISHU-{200 + (seed % 700)}"


def case_dir_for(dataset_root: Path, case_id: str) -> Path:
    return dataset_root / CASES_DIRNAME / case_id


def dataset_root_for_case(case_dir: Path) -> Path:
    return case_dir.parent.parent


def active_case_path_for(dataset_root: Path) -> Path:
    return dataset_root / ACTIVE_CASE_FILENAME


def ensure_case_layout(case_dir: Path) -> None:
    for name in ("input", "data", "checks", "gold", "reports", "runtime", "logs"):
        (case_dir / name).mkdir(parents=True, exist_ok=True)
