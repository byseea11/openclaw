from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DATASET_ROOT = "amem_docs/ds/feishu_im_dataset_v3"


@dataclass(frozen=True)
class BuilderConfig:
    dataset_root: Path
    operator_identity: str = "user"
    delivery_mode: str = "prefixed_single_operator"
    lark_cli_bin: str = "lark-cli"

    @property
    def cases_dir(self) -> Path:
        return self.dataset_root / "cases"


def default_config(dataset_root: str | Path = DATASET_ROOT) -> BuilderConfig:
    return BuilderConfig(dataset_root=Path(dataset_root))
