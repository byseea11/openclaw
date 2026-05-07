#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
用法：
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh [options]

说明：
  - 这个脚本是 Phase 3 的专用执行入口。
  - Phase 3 目标是比较 `task_wiki_3_layer` 和 `openclaw_original`。
  - 主产物是评分 JSON，不是 Markdown report。
  - 它不是只看答案是否答对，也会比较 evidence output、evidence precision、safety 和 efficiency。
  - `openclaw_original` 必须走已启动的真实 OpenClaw Gateway；不可用时会失败，不再隐式使用 adapter。
  - 若未显式传 `--case-dir` 或 `--batch-dir`，默认读取 active_case.json。
  - 只有显式传 `--batch-dir` 时才批量消费 batch。

命令：
  phase3
      执行：
      task-wiki-runtime-eval
      -> openclaw-real-baseline-eval
      -> comparative-score

      Task Wiki runtime health 检查三层是否跑通。
      OpenClaw real baseline 使用已启动 Gateway，按 sender_open_id + source session 保留多人物记忆边界，再检查 query answers 和 evidence traces。
      Comparative score 比较两套系统在 answer / evidence / safety / efficiency 上的表现。

  phase3 --task-wiki-only
  phase3 --stage task-wiki-runtime-eval
      只执行 Task Wiki 三层 runtime eval，不启动或调用 OpenClaw baseline。
      适合先验证 `task_wiki_3_layer` 本身效果，输出 runtime/task_wiki_replay/* 和 reports/task_wiki_runtime_eval.md。

评估口径：
  - answer correctness 和 evidence correctness 分开评分。
  - 答案对但没有证据，只能算弱通过。
  - 证据来自干扰、旧状态、传闻或个人私有信息，会被单独暴露。
  - `效能指标验证` 不是独立 family，而是 Phase 3 的最终价值维度。

常用参数：
  --case-dir <path>
      显式指定要评估的 case 目录。
      若省略且没有 --batch-dir，则读取 active_case.json。

  --dataset-root <path>
      dataset root。
      默认：amem_docs/ds/feishu_im_dataset_v3

  --batch-dir <path>
      显式指定要批量评分的 batch 目录。

  --continue-on-error
      默认 fail-fast；开启后单个 case 失败会记录到 batch summary 并继续处理后续 case。

  --task-wiki-only
      只跑三层方法，不跑 OpenClaw baseline 和 comparative-score。

  --stage task-wiki-runtime-eval
      等价于 --task-wiki-only。

输出：
  <case_dir>/runtime/task_wiki_replay/*
      Task Wiki 三层 runtime health 与 predictions。

  <case_dir>/runtime/openclaw_baseline/*
      真实 OpenClaw baseline answers、evidence traces 与 replay metadata。

  <case_dir>/reports/openclaw_baseline_eval.json
      OpenClaw baseline 指标。

  <case_dir>/reports/phase3_score.json
      Phase 3 唯一正式评分 JSON：包含 per-query、aggregate、delta、failure reason 和 evidence metrics。

批量输出：
  <batch_dir>/batch_manifest.json
  <batch_dir>/batch_run_summary.json
  <batch_dir>/reports/batch_phase3_score.json
      汇总每个 case 的 phase3_score，按 family 统计 answer / evidence / safety / efficiency 平均分。

退出码：
  0
      Phase 3 完整生成。

  非 0
      输入、runtime、baseline 或 comparative eval 失败。

前置条件：
  Phase 3 不负责启动 OpenClaw Gateway。请先确认：
    openclaw gateway status
  或：
    openclaw gateway call health

示例：
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh --task-wiki-only
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh --stage task-wiki-runtime-eval --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/<case_id>
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/<case_id>
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh --batch-dir amem_docs/ds/feishu_im_dataset_v3/batches/<batch_id>
  amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh --dataset-root amem_docs/ds/feishu_im_dataset_v3
EOF
}

case "${1:-}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

mode="full"
forward_args=()
task_wiki_unsupported_args=()
while (($# > 0)); do
  case "$1" in
    --task-wiki-only|--task-wiki-runtime-eval)
      mode="task_wiki_only"
      shift
      ;;
    --stage)
      if [[ "${2:-}" != "task-wiki-runtime-eval" ]]; then
        echo "--stage 当前只支持 task-wiki-runtime-eval；完整 Phase3 请不传 --stage。" >&2
        exit 2
      fi
      mode="task_wiki_only"
      shift 2
      ;;
    --batch-dir|--continue-on-error|--force)
      task_wiki_unsupported_args+=("$1")
      forward_args+=("$1")
      if [[ "$1" == "--batch-dir" ]]; then
        forward_args+=("${2:-}")
        shift 2
      else
        shift
      fi
      ;;
    *)
      forward_args+=("$1")
      shift
      ;;
  esac
done

if [[ "${mode}" == "task_wiki_only" ]]; then
  if ((${#task_wiki_unsupported_args[@]} > 0)); then
    echo "只跑 task-wiki-runtime-eval 时不支持：${task_wiki_unsupported_args[*]}；请改用完整 Phase3 或逐个传 --case-dir。" >&2
    exit 2
  fi
  node feishu_task_wiki_benchmark_builder/runtime/task_wiki_runtime_eval.mjs "${forward_args[@]}"
else
  python3 -m feishu_task_wiki_benchmark_builder.cli phase3 "${forward_args[@]}"
fi
