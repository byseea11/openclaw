# Feishu Task Wiki Benchmark Builder Workflow

## Phase 1

```text
case-context
-> task-actor-layout
-> case-world
-> story-beats
-> conversation-plan
-> story-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
```

### `case-context`

- 输入：
  - `--seed`
  - `--family-id` 可选
  - `--difficulty`
  - `--comparison-target`
- 前置要求：
  - 先通过真实模型预检
  - 真实模型配置只读取 repo 根 `.env`
- 输出：
  - `input/case_context.json`
- 作用：
  - 一次性收口 family 选择、能力约束、case 控制字段、企业场景
  - 由大模型直接生成，不走规则 fallback
  - `case_id`、`task_id`、`seed`、`difficulty`、`comparison_target` 由代码层注入，不由模型自由命名

### `story-plan`

- 输入：
  - `input/case_context.json`
  - `input/task_actor_layout.json`
  - `input/case_world.json`
  - `input/story_beats.json`
  - `input/conversation_plan.json`
- 前置要求：
  - 先通过真实模型预检
- 输出：
  - `input/story_plan.json`
  - `input/task_actor_layout.json`
  - `input/case_world.json`
  - `input/story_beats.json`
  - `input/conversation_plan.json`
- 作用：
  - 生成单 `task`、actors、task_actor_layout、state_changes、message_beats、planned_probe_queries
  - 同时把内部 ownership 结构物化为中间 artifact，供后续阶段只读引用
  - 由大模型直接生成，不走规则 fallback

### `task-actor-layout`

- 输入：
  - `input/case_context.json`
- 输出：
  - `input/task_actor_layout.json`
- 作用：
  - 固定 actor roster、shared actors、overlap 和 context identity
  - 后续阶段不得新增未声明 actor 或 context

### `case-world`

- 输入：
  - `input/case_context.json`
  - `input/task_actor_layout.json`
- 输出：
  - `input/case_world.json`
- 作用：
  - 固定 source sessions、session purpose 和企业协作世界
  - 后续阶段不得新增未声明 session

### `story-beats`

- 输入：
  - `input/case_context.json`
  - `input/case_world.json`
- 输出：
  - `input/story_beats.json`
- 作用：
  - 固定 benchmark roles 和 beat skeleton

### `conversation-plan`

- 输入：
  - `input/task_actor_layout.json`
  - `input/case_world.json`
  - `input/story_beats.json`
- 输出：
  - `input/conversation_plan.json`
- 作用：
  - 固定 `speaker_actor_id`、session placement 和 turn ordering
  - `command-plan` 只编译这里的结构化 turn，不再猜 speaker 名字

### `command-plan`

- 输入：
  - `input/conversation_plan.json`
- 输出：
  - `input/command_plan.jsonl`

### `execute`

- 输入：
  - `input/case_context.json`
  - `input/command_plan.jsonl`
- 输出：
  - `runtime/executed_commands.jsonl`

### `collect`

- 输入：
  - `input/case_context.json`
  - `runtime/executed_commands.jsonl`
- 输出：
  - `data/collected_messages.jsonl`
  - `data/openclaw_message_ingress.jsonl`

### `pre-annotation-validate`

- 输入：
  - `input/case_context.json`
  - `input/story_plan.json`
  - `data/collected_messages.jsonl`
- 输出：
  - `checks/pre_annotation_validation_report.json`

### model 调用日志

- 运行时会额外写：
  - `logs/model_call_log.jsonl`
- 当前只记录：
  - `case-context`
  - `story-plan`
- 默认认证来源：
  - 只读 repo 根 `.env`
- 当前日志只保留元数据：
  - `timestamp`
  - `stage`
  - `backend`
  - `model`
  - `base_url`
  - `success`
  - `duration_ms`
  - `case_id`
  - `artifact_path`
- 失败时额外记录：
  - `error_type`
  - `error_code`
  - `http_status`
  - `message`

### auth-check

- `auth-check` 会读取 repo 根 `.env`
- 它会用当前 `OPENAI_API_KEY`、`OPENAI_API_BASE_URL`、`FEISHU_BUILDER_MODEL` 做一次真实 API 探活
- 如果失败，CLI 会直接返回可修复的错误提示，而不是打印 Python traceback

## Phase 2

```text
annotation-gold
-> query-benchmark
-> replay-eval
```

- 正式输出：
  - `gold/annotation_gold.jsonl`
  - `gold/query_benchmark.json`
  - `reports/replay_eval.json`

## Phase 3

```text
baseline-eval
-> value-eval
-> benchmark-report
```

- 正式输出：
  - `reports/baseline_eval.json`
  - `reports/value_eval.json`
  - `reports/final_benchmark_report.md`

## 仍然不是独立外部 stage 的文件

- `input/family_selection.json`
- `input/memory_capability_brief.json`
- `case_spec.json`

这些信息现在仍通过 `input/case_context.json` 或 phase1 内部 ownership artifact 表达，不再作为单独的外部 CLI stage。
