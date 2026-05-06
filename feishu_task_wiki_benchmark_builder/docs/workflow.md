# Feishu Task Wiki Benchmark Builder Workflow

## Phase 1

```text
case-context
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
- 前置要求：
  - 先通过真实模型预检
- 输出：
  - `input/story_plan.json`
- 作用：
  - 生成单 `task`、actors、task_actor_layout、state_changes、message_beats、planned_probe_queries
  - 由大模型直接生成，不走规则 fallback

### `command-plan`

- 输入：
  - `input/story_plan.json`
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

## 不再作为正式上游 artifact 的文件

- `input/family_selection.json`
- `input/memory_capability_brief.json`
- `case_spec.json`
- `input/case_world.json`

这些信息现在全部并入 `input/case_context.json`。
