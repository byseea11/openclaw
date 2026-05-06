#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
用法：
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh <command> [options]

正式 family：
  - anti_interference            抗干扰测试
  - contradiction_update        矛盾更新测试
  - evidence_dependency_reasoning 证据验证 + 依赖传播

说明：
  - “效能指标验证”不是独立 family。
  - 它属于 phase3 之后的 benchmark report 维度，用来展示命中率、时间、字符数或操作步数的收益。

命令：
  dataset-plan
      生成 batch 用的 dataset_generation_plan.json

  phase1
      执行：
      family-selection
      -> memory-capability-brief
      -> case-spec
      -> case-world
      -> story-plan
      -> command-plan
      -> execute
      -> collect
      -> pre-annotation-validate

  phase2
      执行：
      annotation-gold
      -> query-benchmark
      -> replay-eval

  phase3
      执行：
      baseline-eval
      -> value-eval
      -> benchmark-report

  build-all
      顺序执行 phase1 -> phase2 -> phase3

常用参数：
  --family-id <id>
      single case 时显式指定 family。
      未指定时，会按 seed 做 deterministic 选择。

示例：
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase1 --seed 11
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh build-all --seed 12 --family-id contradiction_update
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh build-all --seed 13 --family-id anti_interference
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh build-all --seed 14 --family-id evidence_dependency_reasoning
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase2 --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/case_0012_contradiction_update
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

COMMAND="$1"
shift

case "${COMMAND}" in
  dataset-plan|phase1|phase2|phase3|build-all)
    python3 -m feishu_task_wiki_benchmark_builder.cli "${COMMAND}" "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "未知命令：${COMMAND}" >&2
    usage >&2
    exit 1
    ;;
esac
