from __future__ import annotations

from pathlib import Path

BUILDER_VERSION = "v1-lite"
DEFAULT_DATASET_ROOT = Path("amem_docs/ds/feishu_im_dataset_v3")
CASES_DIRNAME = "cases"
SKILLS_ROOT = Path("feishu_task_wiki_benchmark_builder/skills/root.md")
ARCHITECTURE_DOC = Path("feishu_task_wiki_benchmark_builder/docs/architecture.md")
WORKFLOW_DOC = Path("feishu_task_wiki_benchmark_builder/docs/workflow.md")
EVALUATION_DOC = Path("feishu_task_wiki_benchmark_builder/docs/evaluation.md")
FAMILY_OVERVIEW_DOC = Path("feishu_task_wiki_benchmark_builder/docs/families/overview.md")
FORMAL_FAMILY_IDS = (
    "anti_interference",
    "contradiction_update",
    "evidence_dependency_reasoning",
)
BASELINE_MODES = (
    "openclaw_memory_md",
    "raw_message_rag",
    "task_wiki",
)
