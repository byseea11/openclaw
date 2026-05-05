from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def builder_log(stage: str, message: str) -> None:
    if str(os.environ.get("FEISHU_BUILDER_QUIET") or "").strip() in {"1", "true", "TRUE"}:
        return
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sys.stderr.write(f"[feishu_builder][{timestamp}][{stage}] {message}\n")
    sys.stderr.flush()
