from __future__ import annotations

from pathlib import Path

from ..config import CASES_DIRNAME


def normalize_seed(seed: int | None) -> int:
    return int(seed if seed is not None else 1)


def build_case_id(seed: int, family_id: str) -> str:
    return f"case_{seed:04d}_{family_id}"


def build_task_id(seed: int) -> str:
    return f"FEISHU-{200 + (seed % 700)}"


def case_dir_for(dataset_root: Path, case_id: str) -> Path:
    return dataset_root / CASES_DIRNAME / case_id


def ensure_case_layout(case_dir: Path) -> None:
    for name in ("input", "data", "checks", "gold", "reports", "runtime"):
        (case_dir / name).mkdir(parents=True, exist_ok=True)
