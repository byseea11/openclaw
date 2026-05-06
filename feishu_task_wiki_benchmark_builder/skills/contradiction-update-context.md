# contradiction-update-context

## 职责

这个 skill 负责定义 `contradiction_update` family 的修正上下文规则。它强调的是同一目标任务内部的 stale / historical / current 关系，而不是其他任务干扰。

## 硬规则

- 修正上下文只能作为 `revision_context_blocks` 和 `supersession_clues` 出现。
- `revision_context_blocks` 必须说明：
  - 哪个字段被修正
  - 修正发生在哪一轮
  - 为什么旧值会被误保留
- `supersession_clues` 必须提供能让系统判断“旧口径已作废”的强语义线索。
- hard case 必须同时满足：
  - 至少 3 段状态。
  - 至少 2 个字段发生连续修正，例如 `owner` 和 `release_window`。
  - 中间状态是真实存在的、合理的，不是噪声。
  - 最终消息必须显式说“之前口径作废”或同等强度 supersession cue。
- `message_beats` 必须覆盖：
  - 初始口径
  - 中间修正
  - 最终 current-state 确认
- query 必须同时考 current state、历史值和 supersession 关系。

## 禁止

- 不要把“其他任务”当成这类 family 的主干扰手段。
- 不要只给最终值，不给 supersede 过程。
- 不要把 stale / historical / current 混成同一层状态。
- 不要让 query 退化成普通字段抽取题。

## JSON 示例：完整 `task_actor_layout`

```json
{
  "target_task_id": "FEISHU-202",
  "shared_actors": ["alice", "xzy"],
  "revision_context_blocks": [
    {
      "context_ref": "ctx_owner_handoff",
      "field": "owner",
      "revision_role": "historical_update",
      "relationship_to_target": "Bob -> Alice -> xzy 的交接链会诱发系统把历史 owner 留成 current owner。"
    },
    {
      "context_ref": "ctx_window_shift",
      "field": "release_window",
      "revision_role": "superseded_schedule",
      "relationship_to_target": "5 月 5 日 -> 5 月 7 日 -> 5 月 9 日 的窗口变化很容易让早期明确日期残留。"
    }
  ],
  "supersession_clues": [
    "之前口径作废",
    "最终确认以本轮为准",
    "旧 owner 只算历史信息"
  ],
  "actor_task_roles": [
    {
      "actor_id": "bob",
      "task_id": "FEISHU-202",
      "role": "initial_owner"
    },
    {
      "actor_id": "alice",
      "task_id": "FEISHU-202",
      "role": "historical_owner"
    },
    {
      "actor_id": "xzy",
      "task_id": "FEISHU-202",
      "role": "current_owner"
    }
  ]
}
```

## JSON 示例：最小完整 `story_plan`

```json
{
  "story_id": "story_case_0202_contradiction_update",
  "case_id": "case_0202_contradiction_update",
  "family_id": "contradiction_update",
  "task": {
    "task_id": "FEISHU-202",
    "task_name": "灰度开关切换计划",
    "role": "target_task"
  },
  "actors": [
    {"actor_id": "bob", "display_name": "Bob", "role": "initial_owner"},
    {"actor_id": "alice", "display_name": "Alice", "role": "historical_owner"},
    {"actor_id": "xzy", "display_name": "xzy", "role": "current_owner"}
  ],
  "task_actor_layout": {
    "target_task_id": "FEISHU-202",
    "shared_actors": ["alice", "xzy"],
    "revision_context_blocks": [
      {
        "context_ref": "ctx_owner_handoff",
        "field": "owner",
        "revision_role": "historical_update",
        "relationship_to_target": "Bob 交接到 Alice，再交接到 xzy，历史 owner 都是真实说法。"
      },
      {
        "context_ref": "ctx_window_shift",
        "field": "release_window",
        "revision_role": "superseded_schedule",
        "relationship_to_target": "发布时间被多轮修正，最早的明确日期最容易被弱记忆系统误当成 current。"
      }
    ],
    "supersession_clues": ["之前口径作废", "最终确认以本轮为准", "旧 owner 只算历史信息"]
  },
  "state_changes": [
    {
      "task_id": "FEISHU-202",
      "field": "owner",
      "sequence": [
        {"value": "Bob", "status": "initial"},
        {"value": "Alice", "status": "historical"},
        {"value": "xzy", "status": "current"}
      ]
    },
    {
      "task_id": "FEISHU-202",
      "field": "release_window",
      "sequence": [
        {"value": "5 月 5 日", "status": "initial"},
        {"value": "5 月 7 日", "status": "historical"},
        {"value": "5 月 9 日", "status": "current"}
      ]
    }
  ],
  "message_beats": [
    {
      "beat_id": "beat_001",
      "speaker": "Alice",
      "session_id": "main_chat",
      "message_intent": "FEISHU-202 最早先由 Bob 跟进，初版窗口先按 5 月 5 日看。"
    },
    {
      "beat_id": "beat_002",
      "speaker": "Alice",
      "session_id": "main_chat",
      "message_intent": "Bob 下周要转去处理别的发布，FEISHU-202 先改成 Alice 接手，窗口顺延到 5 月 7 日。"
    },
    {
      "beat_id": "beat_003",
      "speaker": "xzy",
      "session_id": "thread_release",
      "message_intent": "最终确认：FEISHU-202 由 xzy 收口，正式窗口以 5 月 9 日为准，之前口径作废，旧 owner 只算历史信息。"
    }
  ],
  "planned_probe_queries": [
    {
      "query": "FEISHU-202 当前负责人是谁？Bob 和 Alice 现在还负责吗？上线窗口最终以哪一天为准？从哪一轮开始旧口径已经失效？",
      "expected_good_behavior": "回答 xzy 是当前负责人、5 月 9 日是当前窗口，并明确 Bob/Alice 与 5 月 5 日/5 月 7 日都只属于历史状态，最终确认后旧口径已失效。"
    }
  ]
}
```
