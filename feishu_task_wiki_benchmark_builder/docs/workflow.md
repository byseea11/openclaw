# Feishu Task Wiki Benchmark Builder Workflow

## 定位

这套 workflow 采用 family-first 设计：

- 先决定要测哪一种 memory capability family
- 正式 family 固定为 `anti_interference`、`contradiction_update`、`evidence_dependency_reasoning`
- 再把 capability brief 业务化成企业场景
- 再在统一的 `story_plan.json` 中承载任务、角色、状态变化、消息节奏和 planned probe queries
- collect 之后才做 observed validation、annotation gold 和 benchmark evaluation

## 正式 artifact

- `dataset_generation_plan.json`
- `input/family_selection.json`
- `input/memory_capability_brief.json`
- `case_spec.json`
- `input/case_world.json`
- `input/story_plan.json`
- `input/command_plan.jsonl`
- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`
- `checks/pre_annotation_validation_report.json`
- `gold/annotation_gold.jsonl`
- `gold/query_benchmark.json`
- `reports/replay_eval.json`
- `reports/baseline_eval.json`
- `reports/value_eval.json`
- `reports/final_benchmark_report.md`

## 不再存在的正式 artifact

- `input/memory_failure_blueprint.json`
- `input/task_actor_layout.json`
- `input/state_trajectory.json`
- `input/probe_targets.json`
- `input/memory_case_contract.json`
- `case_manifest.json`

## Phase 1

```text
dataset-plan
-> family-selection
-> memory-capability-brief
-> case-spec
-> case-world
-> story-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
```

### dataset-plan

- 输入：`dataset_size`、`seed`、`difficulty`
- 输出：`dataset_generation_plan.json`
- 说明：只在 batch 模式下需要，用来定义 family quota、difficulty policy 和 seed policy

### family-selection

- 输入：`seed` 或用户显式指定的 `family_id`
- 输出：`input/family_selection.json`
- 说明：single case 未指定 family 时，按 seed deterministic 选择

### memory-capability-brief

- 输入：`input/family_selection.json`
- 输出：`input/memory_capability_brief.json`
- 说明：定义本 case 测试的 memory capability、生成规则、required structure、probe strategy，以及项目需求映射字段

### case-spec

- 输入：`family_selection + difficulty + comparison_target + seed`
- 输出：`case_spec.json`
- 说明：只保留控制字段，不承载解释性 family 语义

### case-world

- 输入：`case_spec + memory_capability_brief`
- 输出：`input/case_world.json`
- 说明：不是自由写故事，而是把 brief 业务化成自然企业场景

### story-plan

- 输入：`case_spec + case_world + memory_capability_brief`
- 输出：`input/story_plan.json`
- 说明：这是 V1-Lite 唯一核心中间 artifact，统一承载：
  - `tasks`
  - `actors`
  - `task_actor_layout`
  - `state_changes`
  - `message_beats`
  - `planned_probe_queries`

### command-plan

- 输入：`input/story_plan.json`
- 输出：`input/command_plan.jsonl`
- 说明：把 message beats 转成可执行动作

### execute

- 输入：`input/command_plan.jsonl`
- 输出：`runtime/executed_commands.jsonl`
- 说明：执行动作计划，形成 runtime trace

### collect

- 输入：`runtime/executed_commands.jsonl`
- 输出：
  - `data/collected_messages.jsonl`
  - `data/openclaw_message_ingress.jsonl`
- 说明：把执行结果转成 observed-side message artifacts

### pre-annotation-validate

- 输入：`story_plan + collected_messages`
- 输出：`checks/pre_annotation_validation_report.json`
- 说明：这是 observed-side validation，不是 gold，也不是 replay eval

## Phase 2

```text
annotation-gold
-> query-benchmark
-> replay-eval
```

### annotation-gold

- 输入：`story_plan + collected_messages`
- 输出：`gold/annotation_gold.jsonl`
- 说明：只能基于 observed messages 回标

### query-benchmark

- 输入：`annotation_gold + story_plan`
- 输出：`gold/query_benchmark.json`
- 说明：把 planned probe queries 收口成正式评测 query

### replay-eval

- 输入：`gold/query_benchmark.json`
- 输出：`reports/replay_eval.json`
- 说明：这是 Task Wiki replay 结果，不是 baseline comparison

## Phase 3

```text
baseline-eval
-> value-eval
-> benchmark-report
```

### baseline-eval

- 输入：`reports/replay_eval.json`
- 输出：`reports/baseline_eval.json`
- 说明：输出 `openclaw_memory_md`、`raw_message_rag`、`task_wiki` 三个 baseline mode

### value-eval

- 输入：`reports/replay_eval.json + reports/baseline_eval.json`
- 输出：`reports/value_eval.json`
- 说明：衡量 Task Wiki 相对 baseline 的能力提升

### benchmark-report

- 输入：`case_spec + capability_brief + replay_eval + baseline_eval + value_eval`
- 输出：`reports/final_benchmark_report.md`
- 说明：输出人类可读总结
