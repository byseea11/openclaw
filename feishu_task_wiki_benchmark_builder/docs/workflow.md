# Feishu Task Wiki Benchmark Builder Workflow

## Phase 1

```text
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
```

### `spec-generation`

- 输入：`--seed`、`--family-id`、`--difficulty`、`--comparison-target`。
- 输出：`case_spec.json`、`input/case_context.json`。
- 作用：确定 case control，不生成角色、消息或故事。

### `family-selection`

- 输入：case control。
- 输出：`input/family_selection.json`。
- 作用：固定四类 formal family 之一：`anti_interference`、`contradiction_update`、`evidence_dependency_reasoning`、`private_info_in_official_file`。

### `capability-brief`

- 输入：`family_id`。
- 输出：`input/memory_capability_brief.json`。
- 作用：把 family 翻译成能力约束、失败原因、probe 策略和 coverage 要求。

### `task-actor-layout`

- 输入：`input/case_context.json`。
- 输出：`input/task_actor_layout.json`。
- 作用：固定 actor roster、shared actors、overlap 和 context identity。

### `case-world`

- 输入：`input/case_context.json`、`input/task_actor_layout.json`。
- 输出：`input/case_world.json`。
- 作用：固定 source sessions、session purpose 和企业协作世界。

### `characters`

- 输入：`input/task_actor_layout.json`、`input/case_world.json`。
- 输出：`input/characters.json`、`input/actor_registry.json`。
- 作用：把 actor slots 实例化为人物，并生成 stable simulated OpenID 映射。

### `state-trajectory`

- 输入：case control、layout、world、characters。
- 输出：`input/state_trajectory.json`。
- 作用：固定 current、historical、supersession、dependency impact 或私有信息边界。

### `coverage-spec`

- 输入：capability brief、state trajectory、family context。
- 输出：`input/coverage_spec.json`。
- 作用：定义 evidence、state、beat 和 probe 的落地检查要求。

### `story-beats`

- 输入：case world、state trajectory、coverage spec。
- 输出：`input/story_beats.json`、`input/official_file_plan.json`。
- 作用：固定 benchmark roles、beat skeleton、official file 回流要求。

### `conversation-plan`

- 输入：layout、world、characters、state trajectory、story beats。
- 输出：`input/conversation_plan.json`。
- 作用：由 LLM 生成完整企业 transcript；每个 turn 都是后续真实发送和 OpenClaw replay 的候选消息。

### `command-plan`

- 输入：`input/conversation_plan.json`、`input/characters.json`、`input/actor_registry.json`。
- 输出：`input/command_plan.jsonl`。
- 作用：把 turn 编译成真实 `lark-cli` action rows，包括 dependency、output ref 和 command preview。

### `execute`

- 输入：`input/command_plan.jsonl`。
- 输出：`runtime/executed_commands.jsonl`、`runtime/execution_result.json`。
- 作用：按 dependency graph 调用真实 `lark-cli`，记录 stdout、stderr、returncode 和 resource ids。

### `collect`

- 输入：execution result 和 fetch actions。
- 输出：`data/collected_messages.jsonl`、`data/openclaw_message_ingress.jsonl`。
- 作用：从真实 fetch 结果回收 observed data，并把全部真实协作消息转成 OpenClaw replay ingress。

### `pre-annotation-validate`

- 输入：coverage spec、conversation plan、command plan、observed data。
- 输出：`checks/pre_annotation_validation_report.json`。
- 作用：检查 family trap、状态变化、证据链、official/private 信息边界和 probe 是否真实落地。

### model 调用日志

- 运行时写入：`logs/model_call_log.jsonl`。
- 当前主要记录：`spec-generation`、`conversation-plan`、`semantic-gold`。
- 默认认证来源：只读 repo 根 `.env`。

## Phase 2

```text
annotation-gold
-> semantic-gold
-> query-benchmark
-> build-checks
-> gold-validate
-> replay-runtime
-> replay-eval
```

- `gold/annotation_gold.jsonl` 是 deterministic evidence gold，只基于 observed messages。
- `gold/task_wiki_semantic_gold.json` 是 optional semantic gold，只能引用 observed `message_id`。
- `query_benchmark.json` 与 replay eval 使用 gold 和 observed data，不读取 planned-only 文本作为证据。

## Phase 3

```text
task-wiki-runtime-eval
-> openclaw-real-baseline-eval
-> comparative-score
```

- 正式输出：
  - `runtime/task_wiki_replay/layer_metrics.json`
  - `reports/openclaw_baseline_eval.json`
  - `reports/phase3_score.json`
