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
  - anti_interference              抗干扰测试
  - contradiction_update          矛盾更新测试
  - evidence_dependency_reasoning 证据验证 + 依赖传播

说明：
  - “效能指标验证”不是独立 family。
  - 它属于 phase3 之后的 benchmark report 维度，用来展示命中率、时间、字符数或操作步数的收益。
  - 真实模型认证默认只读取 repo 根 `.env`。
  - `case-context` 和 `story-plan` 会在运行前先做真实模型预检。

命令：
  auth-check
      读取 repo 根 `.env`，对当前 OpenAI 配置做一次真实 API 探活。

  current-case
      读取 dataset root 下的 active_case.json，查看当前正在操作的 case。

  dataset-plan
      生成 batch 用的 dataset_generation_plan.json

  phase1
      执行：
      case-context
      -> story-plan
      -> command-plan
      -> execute
      -> collect
      -> pre-annotation-validate

  phase1-step
      单步执行 Phase 1。
      需要通过 `--stage <stage>` 指定具体阶段。
      `case-context` 成功后会刷新当前 active case。
      除 `case-context` 外的后续 stage，若未显式传 `--case-dir`，默认读取当前 active case。

      可选 stage：
      - case-context
      - story-plan
      - command-plan
      - execute
      - collect
      - pre-annotation-validate

  phase2
      执行：
      annotation-gold
      -> query-benchmark
      -> replay-eval
      若未显式传 `--case-dir`，默认读取当前 active case。

  phase3
      执行：
      baseline-eval
      -> value-eval
      -> benchmark-report
      若未显式传 `--case-dir`，默认读取当前 active case。

  build-all
      顺序执行 phase1 -> phase2 -> phase3

常用参数：
  --family-id <id>
      single case 时显式指定 family。
      未指定时，会按 seed 做 deterministic 选择。

  --case-dir <path>
      显式指定要继续操作的 case；若省略则默认读取当前 active case。

示例：
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh auth-check
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh current-case
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase1
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase1-step --stage case-context --family-id anti_interference
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase1-step --stage story-plan
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase1-step --stage command-plan
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh build-all --seed 12 --family-id contradiction_update
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh build-all --seed 13 --family-id anti_interference
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh build-all --seed 14 --family-id evidence_dependency_reasoning
  amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh phase2
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

COMMAND="$1"
shift

case "${COMMAND}" in
  auth-check|current-case|dataset-plan|phase1-step|phase1|phase2|phase3|build-all)
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
