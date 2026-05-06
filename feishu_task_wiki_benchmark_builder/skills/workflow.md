# Feishu Task Wiki Benchmark Builder Workflow

这个文件是当前 builder 的 machine workflow 入口。它只负责：

- 给出 canonical workflow
- 给出 stage routing
- 用简短摘要说明每个阶段做什么
- 告诉 runtime 当前阶段应引用哪些 code-side skills

## Referenced Skills

- `family-selection.md`
- `capability-brief.md`
- `case-world.md`
- `story-plan.md`
- `anti-interference-context.md`
- `contradiction-update-context.md`
- `evidence-dependency-context.md`
- `evaluation.md`

## Canonical Workflow

### Phase 1

```text
case-context
-> story-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
```

### Phase 2

```text
annotation-gold
-> query-benchmark
-> replay-eval
```

### Phase 3

```text
baseline-eval
-> value-eval
-> benchmark-report
```

## Stage Routing

- 如果当前任务是确定 family、能力约束、case id 和企业场景，进入 `case-context`，并引用：
  - `family-selection.md`
  - `capability-brief.md`
  - `case-world.md`
  - 当前 family 对应的 context skill
- 如果当前任务是生成任务结构、状态变化、消息节奏和 probes，进入 `story-plan`，并引用：
  - `story-plan.md`
  - 当前 family 对应的 context skill
- 如果当前任务是把 message beats 转成可执行动作，进入 `command-plan`
- 如果当前任务是执行动作，进入 `execute`
- 如果当前任务是收集 observed messages，进入 `collect`
- 如果当前任务是判断 trap 是否落地，进入 `pre-annotation-validate`
- 如果当前任务已经进入 observed data 回标和评测，进入 Phase 2 / Phase 3，并引用：
  - `evaluation.md`

## Stage Summary

### `case-context`

- 做什么：统一收口 family 选择、capability brief 和企业场景。
- 读取：显式 family、seed、difficulty、comparison_target。
- 输出：`input/case_context.json`。

### `story-plan`

- 做什么：生成任务结构、参与者、状态变化、消息节奏和 planned probes。
- 读取：`input/case_context.json`。
- 输出：`input/story_plan.json`。

### `command-plan`

- 做什么：把 `message_beats` 编译成可执行命令。
- 读取：`input/story_plan.json`。
- 输出：`input/command_plan.jsonl`。

### `execute`

- 做什么：执行 command plan，生成 runtime execution rows。
- 读取：`input/command_plan.jsonl`。
- 输出：`runtime/executed_commands.jsonl`。

### `collect`

- 做什么：把 execution rows 收口成 observed messages。
- 读取：`runtime/executed_commands.jsonl`。
- 输出：`data/collected_messages.jsonl`、`data/openclaw_message_ingress.jsonl`。

### `pre-annotation-validate`

- 做什么：检查关键 beats、状态信号和 probes 是否真的落地。
- 读取：`input/story_plan.json` 和 observed data。
- 输出：`checks/pre_annotation_validation_report.json`。

### Phase 2 / Phase 3

- 做什么：回标 gold、构造 query benchmark、运行 replay/baseline/value eval、汇总最终 benchmark report。
- 详细规则：统一引用 `evaluation.md`。

## Minimal Global Invariants

- `case-context` 和 `story-plan` 必须由大模型生成，不允许走规则 fallback。
- 真实模型配置只读取 repo 根 `.env`，不混用 shell env。
- 进入 `case-context` / `story-plan` 前必须先通过认证预检。
- `效能指标验证` 是跨 family 的最终比较维度，不是 formal family。
- runtime prompt 只读 `skills/`，不读 `docs/`。
