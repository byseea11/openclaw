# capability-brief

## 职责

这个 skill 负责为 `case-context` 阶段提供能力约束、失败原因、生成规则和 probe 策略。它不单独落文件，而是约束最终 `case_context.json` 的 capability brief 部分。

## 硬规则

- 必须明确：
  - `capability_under_test`
  - `why_memory_systems_may_fail`
  - `generation_rules`
  - `required_case_structure`
  - `probe_strategy`
  - `expected_good_system_behavior`
- 每个字段都必须能帮助后续 `story-plan` 做决定。
- `probe_strategy` 必须描述要测什么能力，不是最终问句。
- `required_case_structure` 必须约束后续任务结构、状态变化或证据关系。
- `required_case_structure` 不只是“有这些概念”，还必须满足当前 difficulty 和 family 的最低数量、分布与 cross-source 复杂度。
- `required_case_structure` 必须显式覆盖 runtime 注入的数字目标，以及当前 family skill 里定义的语义槽位，不能只保留抽象概念名词。
- 必须吸收旧 builder 里的 family-specific failure mechanism：
  - `anti_interference` 强调 shared actor、相似措辞和 cross-task noise 如何污染目标任务答案。
  - `contradiction_update` 强调 stale state、supersede relation 和 final current state 的区分。
  - `evidence_dependency_reasoning` 强调 verified / ambiguous / hearsay 的证据梯度，以及 upstream impact 如何传播到目标任务。
- 正式 contract 里只有 1 个目标任务；distractor 或 upstream/downstream 只能作为上下文来源，不是并列正式 task。
- 必须吸收旧 builder 的规模规则：
  - `department_count`
  - `character_count_min/max`
  - `recommended_session_count`
  - family-specific minima，如 `min_shared_actors`、`min_state_tracks`、`min_dependency_hops`
- session 类型定义、noise 类型、role slots、context slots、revision fields、dependency slots 都由对应 skills 定义，不由 yml 注入。
- 如果当前 family skill 定义了特定 role/context/dependency/revision 槽位，`generation_rules` 和 `required_case_structure` 必须能覆盖这些语义槽位。

## 禁止

- 不要开始写企业场景。
- 不要开始写 message beats。
- 不要开始写最终 probe wording。
- 不要重新定义 family。
- 不要把多个正式 task 写进 `required_case_structure`。

## JSON 示例

下面是最终 `case_context.json` 中 capability brief 的片段示例：

```json
{
  "capability_under_test": "在多个状态更新发生后，识别哪个值已经被覆盖，哪个值仍是当前值，并明确旧口径已经作废。",
  "why_memory_systems_may_fail": "系统容易记住较早的显式值，却忽略后续修正和 supersede 关系，最终把 stale value 当成 current value。",
  "generation_rules": [
    "必须有至少 3 段状态：initial、historical、current。",
    "更新必须通过真实消息落地，不能只在结构化字段里声明。",
    "当前 difficulty 必须保证足够多的部门、角色和 session，不能把复杂协作压成单线程对话。"
  ],
  "required_case_structure": [
    "target_task",
    "distractor_context",
    "multi_step_update_sequence",
    "supersedes_relation"
  ],
  "probe_strategy": [
    "查询当前状态，同时追问历史状态是否仍然有效。"
  ],
  "expected_good_system_behavior": [
    "返回 current value，并标注历史值已经失效。"
  ]
}
```

## V3 Phase 1 对接位置

在 Phase 1 细分链路里，`capability-brief` 接在 `family-selection` 之后，负责把 family 转成可执行生成约束。

它主要约束：

- `task-actor-layout` 需要哪些角色、context block、shared actor 或 dependency role。
- `state-trajectory` 需要哪些 current / historical / dependency state。
- `coverage-spec` 需要检查哪些 evidence、state、beat 和 probe。
- `story-beats` 需要覆盖哪些 benchmark role。

它承接旧版第一阶段里 failure mechanism、landing requirements 和 probe strategy 的作用，但当前版本不新增独立 blueprint 文件。
