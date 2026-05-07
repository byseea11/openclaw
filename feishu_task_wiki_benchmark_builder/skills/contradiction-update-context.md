# contradiction-update-context

## 职责

这个 skill 定义 `contradiction_update` family 的修正上下文规则。它强调同一目标任务内部的 stale / historical / current 关系，而不是其他任务干扰。

## 硬规则

- 修正上下文只能作为 `revision_context_blocks` 和 `supersession_clues` 出现。
- `revision_context_blocks` 必须说明字段、修正轮次、旧值为什么会被误保留。
- `supersession_clues` 必须提供能判断旧口径作废的强语义线索。
- hard case 必须同时覆盖至少 3 段状态、至少 2 个字段连续修正、跨 session 确认和最终 current-state。
- `story-beats` 必须覆盖初始口径、中间修正、最终确认和旧口径作废。
- `conversation-plan` 必须让这些修正发生在真实消息中，而不是只写在结构化字段里。
- query 必须同时考 current state、历史值和 supersession 关系。

## 禁止

- 不要把其他任务当成这类 family 的主干扰手段。
- 不要只给最终值，不给 supersede 过程。
- 不要把 stale / historical / current 混成同一层状态。
- 不要让 query 退化成普通字段抽取题。

## JSON 示例：`task_actor_layout`

```json
{
  "target_task_id": "FEISHU-202",
  "shared_actors": ["alice", "xavier"],
  "revision_context_blocks": [
    {
      "context_ref": "ctx_owner_handoff",
      "field": "owner",
      "revision_role": "historical_update",
      "relationship_to_target": "Bob -> Alice -> Xavier 的交接链会诱发系统把历史 owner 留成 current owner。"
    },
    {
      "context_ref": "ctx_window_shift",
      "field": "release_window",
      "revision_role": "superseded_schedule",
      "relationship_to_target": "5 月 5 日 -> 5 月 7 日 -> 5 月 9 日 的窗口变化很容易让早期明确日期残留。"
    }
  ],
  "supersession_clues": ["之前口径作废", "最终确认以本轮为准", "旧 owner 只算历史信息"],
  "actor_task_roles": [
    {"actor_id": "bob", "task_id": "FEISHU-202", "role": "initial_owner"},
    {"actor_id": "alice", "task_id": "FEISHU-202", "role": "historical_owner"},
    {"actor_id": "xavier", "task_id": "FEISHU-202", "role": "current_owner"}
  ]
}
```

## 对接位置

- `task-actor-layout`：先定义 initial/historical/current role。
- `state-trajectory`：生成 stale、historical、current 和 supersession 链。
- `story-beats`：把每一轮修正落成 required beat。
- `conversation-plan`：用自然企业消息表达修正、确认、反悔和最终口径。
