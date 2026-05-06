# v3-phase1-dataset-generation

## 职责

这个 skill 是当前三类 family 的 Phase 1 数据集生成总入口。它定义正式生成链路、stage ownership、artifact 职责和真实执行边界。

当前正式 family 只有三类：

- `anti_interference`
- `contradiction_update`
- `evidence_dependency_reasoning`

## Phase 1 主链路

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

- `anti_interference` 读取 `anti-interference-context.md`
- `contradiction_update` 读取 `contradiction-update-context.md`
- `evidence_dependency_reasoning` 读取 `evidence-dependency-context.md`

## Stage 职责表

- `spec-generation`：生成最小 case control，决定 case id、task id、family、difficulty、seed 和 comparison target。
- `family-selection`：在三类 family 中确定本 case 的正式数据集方向。
- `capability-brief`：把 family 翻译成能力约束、失败原因、生成规则、probe 策略和 coverage 要求。
- `family context skill`：提供 family-specific 的上下文结构、证据类型、状态变化或干扰机制。
- `task-actor-layout`：生成 actor roster、context blocks、shared actors 和 overlap。
- `case-world`：把 family 和 layout 翻译成自然企业协作背景与 source sessions。
- `characters`：把 actor slots 实例化为人物，并生成执行可引用的 actor registry。
- `state-trajectory`：定义 current state、historical state、supersession、dependency impact 或干扰边界。
- `coverage-spec`：把 required structure 转成落地检查条件。
- `story-beats`：把 required roles、context blocks、state requirements 映射成 beat skeleton。
- `conversation-plan`：把 beat、actor、session、state hint 落成消息级 turn。
- `command-plan`：把 conversation turns 生成真实 `lark-cli` action plan。
- `execute`：按依赖顺序真实执行 `lark-cli` action。
- `collect`：从飞书回收真实 observed messages。
- `pre-annotation-validate`：基于 observed data 检查 family trap、状态变化、证据链和 probe 是否落地。

## 生成边界

- family/context skills 是当前版本的 failure-oriented 语义来源。
- `spec-generation` 到 `conversation-plan` 负责计划与生成。
- `command-plan` 负责把计划转成真实可执行 action。
- `execute` 和 `collect` 负责真实飞书 side effect 与 observed data 回收。
- 不新增 `memory-failure-blueprint.md`，不引入旧四类 failure mode。

## 下游约束

- 下游阶段只能引用上游已声明的 actor、session、context、beat 和 state field。
- `command-plan` 可以生成 `lark_cli_command` preview，但不直接执行。
- `execute` 才允许产生真实飞书 side effect。
- `collect` 必须从真实 fetch 结果生成 observed data，不能用 planned message 伪造。
