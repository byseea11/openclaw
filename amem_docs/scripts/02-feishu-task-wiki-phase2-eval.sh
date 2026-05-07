#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
用法：
  amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh [options]

说明：
  - 这个脚本是 Phase 2 的专用执行入口。
  - Phase 2 负责把 Phase 1 observed data 转成 gold、query benchmark 和 replay eval。
  - 若未显式传 `--case-dir` 或 `--batch-dir`，默认读取 active_case.json。
  - 只有显式传 `--batch-dir` 时才批量消费 batch。
  - semantic gold 默认使用 auto 模式；有模型配置时优先 LLM，否则可回退 rule。

命令：
  phase2
      执行：
      annotation-gold
      -> semantic-gold
      -> query-benchmark
      -> build-checks
      -> gold-validate
      -> replay-runtime
      -> replay-eval

      这一阶段不重新生成企业对话，只基于真实 observed messages 生成评测材料。

评估口径：
  - annotation gold 只基于真实 observed messages。
  - semantic gold 只能引用 observed message_id。
  - query benchmark 统一 Task Wiki 与 baseline 的评测输入。

常用参数：
  --case-dir <path>
      显式指定要评估的 case 目录。
      若省略且没有 --batch-dir，则读取 active_case.json。

  --dataset-root <path>
      dataset root。
      默认：amem_docs/ds/feishu_im_dataset_v3

  --batch-dir <path>
      显式指定要批量评估的 batch 目录。

  --continue-on-error
      默认 fail-fast；开启后单个 case 失败会记录到 batch summary 并继续处理后续 case。

  --semantic-gold <auto|llm|rule|off>
      semantic gold 生成模式。

  --require-llm
      semantic gold 需要 LLM 时，如果没有模型配置则直接失败。

输出：
  <case_dir>/gold/annotation_gold.jsonl
  <case_dir>/gold/task_wiki_semantic_gold.json
  <case_dir>/gold/query_benchmark.json
  <case_dir>/checks/*
  <case_dir>/predictions/*
  <case_dir>/reports/replay_eval.json

批量输出：
  <batch_dir>/batch_manifest.json
  <batch_dir>/batch_run_summary.json
  <batch_dir>/reports/batch_phase2_summary.json

示例：
  amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh
  amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/<case_id>
  amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh --batch-dir amem_docs/ds/feishu_im_dataset_v3/batches/<batch_id>
  amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh --semantic-gold rule
  amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh --semantic-gold llm --require-llm
EOF
}

case "${1:-}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

python3 -m feishu_task_wiki_benchmark_builder.cli phase2 "$@"
