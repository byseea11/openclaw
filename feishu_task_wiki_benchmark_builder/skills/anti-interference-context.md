# anti-interference-context

## 职责

这个 skill 定义 `anti_interference` family 的干扰上下文规则。它约束的不是额外正式 task，而是目标任务周围会污染记忆的 context blocks，并要求这些 block 真实落进 observed messages。

## 硬规则

- 干扰上下文只能作为 `interference_context_blocks` 出现，不能写成并列正式 task。
- 每个 block 必须说明 `context_ref`、`context_label`、`noise_source_type`、`relationship_to_target`。
- 允许的干扰来源包括 `shared_actor_noise`、`similar_wording_noise`、`parallel_discussion_noise`。
- hard case 必须同时满足 shared actor、相似措辞、并行 source session 和显式排除句。
- `story-beats` 必须把干扰 block 编成 required beats。
- `conversation-plan` 必须把干扰落成真实企业消息，而不是模板补句。
- query 必须逼系统显式排除这些上下文噪声，只回答目标任务。

## 禁止

- 不要把干扰上下文重新写成 `distractor task`。
- 不要只写“有干扰”，但没有具体 block 类型和污染机制。
- 不要只问单个显式字段而不要求系统说明哪些上下文不该混入。

## JSON 示例：`task_actor_layout`

```json
{
  "target_task_id": "FEISHU-201",
  "shared_actors": ["alice", "bob"],
  "interference_context_blocks": [
    {
      "context_ref": "ctx_doc_review",
      "context_label": "并行文档收口讨论",
      "noise_source_type": "shared_actor_noise",
      "relationship_to_target": "Alice 在这条并行讨论里负责审文档，很容易被误当成 FEISHU-201 的 owner 再次变更。"
    },
    {
      "context_ref": "ctx_ops_rehearsal",
      "context_label": "运维演练 blocker 讨论",
      "noise_source_type": "similar_wording_noise",
      "relationship_to_target": "这里也在说 blocker、ready 和收口，容易把别的讨论污染到 FEISHU-201。"
    }
  ],
  "actor_task_roles": [
    {"actor_id": "alice", "task_id": "FEISHU-201", "role": "target_owner"},
    {"actor_id": "alice", "context_ref": "ctx_doc_review", "role": "reviewer"},
    {"actor_id": "bob", "context_ref": "ctx_ops_rehearsal", "role": "ops_owner"}
  ]
}
```

## 对接位置

- `task-actor-layout`：先定义 shared actors 和 interference context identity。
- `state-trajectory`：明确目标 current state 与干扰 state 的边界。
- `story-beats`：把干扰、排除句和目标事实编成 required beats。
- `conversation-plan`：生成完整 transcript，让 OpenClaw 原生 summary 容易混入干扰，但让 Task Wiki 能按 task scope 排除。
