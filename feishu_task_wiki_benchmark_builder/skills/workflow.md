# Feishu Task Wiki Benchmark Builder Workflow

这个文件是当前 builder 的 machine workflow 入口。它只负责：

- 给出 canonical workflow
- 给出 stage routing
- 用简短摘要说明每个阶段做什么
- 告诉 runtime 当前阶段应引用哪些 code-side skills

## Referenced Skills

- `v3-phase1-dataset-generation.md`
- `spec-generation.md`
- `family-selection.md`
- `capability-brief.md`
- `task-actor-layout.md`
- `case-world.md`
- `characters.md`
- `state-trajectory.md`
- `coverage-spec.md`
- `story-beats.md`
- `conversation-plan.md`
- `command-plan.md`
- `execute.md`
- `collect.md`
- `pre-annotation-validate.md`
- `anti-interference-context.md`
- `contradiction-update-context.md`
- `evidence-dependency-context.md`
- `story-plan.md`
- `evaluation.md`

## Canonical Workflow

### Phase 1

```text
spec-generation
-> family-selection
-> capability-brief
-> family context skill
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
```

`family context skill` 按 `family_id` 路由：

- `anti_interference` 使用 `anti-interference-context.md`
- `contradiction_update` 使用 `contradiction-update-context.md`
- `evidence_dependency_reasoning` 使用 `evidence-dependency-context.md`

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

- 如果当前任务是解释 Phase 1 每个 artifact 如何生成、互相如何衔接，先引用：
  - `v3-phase1-dataset-generation.md`
- 如果当前任务是生成最小 case control，进入 `spec-generation`，并引用：
  - `spec-generation.md`
  - `family-selection.md`
- 如果当前任务是确定能力约束、失败原因、生成规则和 probe 策略，进入 `capability-brief`，并引用：
  - `capability-brief.md`
  - 当前 family 对应的 context skill
- 如果当前任务是定义 actor roster、shared actors、overlap 和 context identity，进入 `task-actor-layout`，并引用：
  - `task-actor-layout.md`
  - 当前 family 对应的 context skill
- 如果当前任务是定义企业世界、source session 和信息分布原因，进入 `case-world`，并引用：
  - `case-world.md`
  - 当前 family 对应的 context skill
- 如果当前任务是把 actor slots 实例化成人和 actor registry，进入 `characters`，并引用：
  - `characters.md`
- 如果当前任务是定义 current、historical、supersession、dependency impact 或干扰边界，进入 `state-trajectory`，并引用：
  - `state-trajectory.md`
  - 当前 family 对应的 context skill
- 如果当前任务是定义 evidence、state、beat 和 probe 的落地检查要求，进入 `coverage-spec`，并引用：
  - `coverage-spec.md`
  - `capability-brief.md`
  - 当前 family 对应的 context skill
- 如果当前任务是定义 benchmark roles、beat skeleton 和 session 落点，进入 `story-beats`，并引用：
  - `story-beats.md`
  - 当前 family 对应的 context skill
- 如果当前任务是定义 speaker、session、turn 和 message 的具体落位，进入 `conversation-plan`，并引用：
  - `conversation-plan.md`
  - 当前 family 对应的 context skill
- 如果当前任务是把 conversation turn 转成真实 `lark-cli` action plan，进入 `command-plan`，并引用：
  - `command-plan.md`
- 如果当前任务是执行 action plan，进入 `execute`，并引用：
  - `execute.md`
- 如果当前任务是回收真实 observed messages，进入 `collect`，并引用：
  - `collect.md`
- 如果当前任务是判断 trap、状态变化、证据链和 probe 是否落地，进入 `pre-annotation-validate`，并引用：
  - `pre-annotation-validate.md`
- 如果当前任务已经进入 observed data 回标和评测，进入 Phase 2 / Phase 3，并引用：
  - `evaluation.md`

## Stage Summary

### `spec-generation`

- 做什么：确定 `case_id`、`task_id`、`family_id`、`difficulty`、`seed` 和 `comparison_target`。
- 读取：显式 family、seed、difficulty、comparison target。
- 输出：最小 case control。

### `family-selection`

- 做什么：在三类正式 family 中选择当前 case 的数据集方向。
- 读取：`family-selection.md`、seed、显式 family。
- 输出：`family_id`。

### `capability-brief`

- 做什么：把 family 翻译成能力约束、失败原因、生成规则、probe 策略和 coverage 要求。
- 读取：`family_id` 和当前 family context skill。
- 输出：capability brief。

### `task-actor-layout`

- 做什么：定义 actor roster、shared actors、context identity 和 overlap 结构。
- 读取：case control、capability brief、当前 family context skill。
- 输出：`input/task_actor_layout.json`。

### `case-world`

- 做什么：定义企业世界、source session、session purpose 和信息分布原因。
- 读取：case control、`input/task_actor_layout.json`。
- 输出：`input/case_world.json`。

### `characters`

- 做什么：把 actor slots 实例化为人物，并生成稳定 actor registry。
- 读取：`input/task_actor_layout.json`、`input/case_world.json`。
- 输出：`input/characters.json`、`input/actor_registry.json`。

### `state-trajectory`

- 做什么：定义状态演进、supersession、dependency impact 或干扰边界。
- 读取：case control、layout、world、characters、当前 family context skill。
- 输出：`input/state_trajectory.json`。

### `coverage-spec`

- 做什么：定义哪些 evidence、state、beat 和 probe 必须真实落地。
- 读取：capability brief、state trajectory、当前 family context skill。
- 输出：`input/coverage_spec.json`。

### `story-beats`

- 做什么：定义 benchmark roles、beat skeleton 和每个 beat 的目标 session。
- 读取：case control、case world、state trajectory、coverage spec。
- 输出：`input/story_beats.json`。

### `conversation-plan`

- 做什么：定义谁在什么 session 说什么，固定 turn 序和结构化 speaker 引用。
- 读取：layout、world、characters、state trajectory、story beats。
- 输出：`input/conversation_plan.json`。

### `command-plan`

- 做什么：把 conversation turns 转成真实 `lark-cli` action rows。
- 读取：`input/conversation_plan.json`、`input/characters.json`、`input/actor_registry.json`。
- 输出：`input/command_plan.jsonl`。

### `execute`

- 做什么：按 dependency graph 真实执行 command plan。
- 读取：`input/command_plan.jsonl`。
- 输出：`runtime/executed_commands.jsonl`。

### `collect`

- 做什么：从真实飞书会话回收 observed messages。
- 读取：execution result 和 fetch actions。
- 输出：`data/collected_messages.jsonl`、`data/openclaw_message_ingress.jsonl`。

### `pre-annotation-validate`

- 做什么：检查 family trap、状态变化、证据链和 probes 是否真的落地。
- 读取：coverage spec、conversation plan、command plan、observed data。
- 输出：`checks/pre_annotation_validation_report.json`。

## Current Implementation Compatibility

当前 Python CLI 仍保留 `case-context` 和 `story-plan` 两个聚合入口：

- `case-context` 当前聚合 spec generation、family selection、capability brief 和 case world 的一部分，输出 `input/case_context.json`。
- `story-plan` 当前聚合 task actor layout、case world、story beats、conversation plan 的可读视图，输出 `input/story_plan.json`。

这两个入口是当前实现兼容层，不是本 skill 的 canonical Phase 1 主线。后续拆分代码时，应以本文件的细分 stage 为准。

## Minimal Global Invariants

- 当前三类 family 是唯一正式数据集方向。
- 不新增 `memory-failure-blueprint.md`，不引入旧四类 failure mode。
- 真实模型配置只读取 repo 根 `.env`，不混用 shell env。
- 进入需要 LLM 的生成阶段前必须先通过认证预检。
- `task-actor-layout`、`case-world`、`characters`、`state-trajectory`、`coverage-spec`、`story-beats`、`conversation-plan` 是 phase1 内部 ownership 阶段，后续阶段只能引用，不得重造同类 identity。
- `command-plan` 只生成真实 `lark-cli` action plan，不执行。
- `execute` 才允许真实调用 `lark-cli`。
- `collect` 必须基于真实 fetch 结果生成 observed data，不允许用 planned message 伪造。
- `效能指标验证` 是跨 family 的最终比较维度，不是 formal family。
- runtime prompt 只读 `skills/`，不读 `docs/`。
- `case-context` 和 `story-plan` 当前仍必须由大模型生成，不允许走规则 fallback。
