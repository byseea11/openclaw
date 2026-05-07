#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

usage() {
  cat <<'EOF'
用法：
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh [options]

正式 family：
  - anti_interference              抗干扰测试
  - contradiction_update          矛盾更新测试
  - evidence_dependency_reasoning 证据验证 + 依赖传播
  - private_info_in_official_file 个人私有信息混入正式文件

说明：
  - 这个脚本是 Phase 1 的专用执行入口。
  - Phase 1 负责生成并真实执行数据集。
  - 真实模型认证默认只读取 repo 根 `.env`。
  - `conversation-plan` 会在运行前先做真实模型预检。
  - 成功后会刷新 dataset root 下的 active_case.json。

命令：
  phase1
      执行：
      spec-generation
      -> family-selection
      -> capability-brief
      -> task-actor-layout
      -> case-world
      -> characters
      -> state-trajectory
      -> coverage-spec
      -> story-beats
      -> conversation-plan
      -> command-plan
      -> execute
      -> collect
      -> pre-annotation-validate

      这一阶段会生成 case control、角色、状态、完整企业对话、lark-cli action plan，
      并通过 execute / collect 回收真实 observed messages。

      注意：`效能指标验证` 不是独立 family，它属于 Phase 3 的最终对比维度。

常用参数：
  --family-id <id>
      single case 时显式指定 family。
      未指定时，会按 seed 做 deterministic 选择。

  --difficulty <easy|medium|hard>
      指定数据集复杂度。

  --seed <number>
      指定可复现 seed。

  --dataset-root <path>
      dataset root。
      默认：amem_docs/ds/feishu_im_dataset_v3

批量生成参数：
  --batch-size <N>
      生成 N 个 case。批量 case 会写入：
      <dataset-root>/batches/<batch_id>/cases/

  --batch-id <id>
      指定 batch 目录名。未指定时自动生成 batch_<时间戳>。

  --families all|id1,id2
      批量 family 策略。默认 all，按四类 family round-robin。
      如果同时传 --family-id，则 N 条都生成同一个 family。

  --continue-on-error
      默认 fail-fast；开启后单个 case 失败会写入 batch_manifest 并继续生成后续 case。

输出：
  <case_dir>/input/*
  <case_dir>/runtime/executed_commands.jsonl
  <case_dir>/data/collected_messages.jsonl
  <case_dir>/data/openclaw_message_ingress.jsonl
  <case_dir>/checks/pre_annotation_validation_report.json

批量输出：
  <dataset-root>/active_batch.json
  <dataset-root>/batches/<batch_id>/batch_manifest.json
  <dataset-root>/batches/<batch_id>/batch_run_summary.json
  <dataset-root>/batches/<batch_id>/dataset_generation_plan.json
  <dataset-root>/batches/<batch_id>/cases/<case_id>/*

示例：
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh --family-id anti_interference --difficulty hard
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh --seed 12 --family-id contradiction_update
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh --seed 15 --family-id private_info_in_official_file
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh --batch-size 12 --difficulty hard --families all
  amem_docs/scripts/01-feishu-task-wiki-phase1-build.sh --batch-size 4 --family-id contradiction_update --seed 20260507
EOF
}

case "${1:-}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

python3 -m feishu_task_wiki_benchmark_builder.cli phase1 "$@"
