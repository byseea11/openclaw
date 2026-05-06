# anti-interference-context

## 职责

这个 skill 负责定义 `anti_interference` family 的干扰上下文规则。它约束的不是额外正式 task，而是目标任务周围会污染记忆的上下文 block，并要求这些 block 真正落进消息里。

## 硬规则

- 干扰上下文只能作为 `interference_context_blocks` 出现，不能写成并列正式 task。
- 每个 block 必须说明：
  - `context_ref`
  - `context_label`
  - `noise_source_type`
  - `relationship_to_target`
- 允许的干扰来源包括：
  - `shared_actor_noise`
  - `similar_wording_noise`
  - `parallel_discussion_noise`
- hard case 必须同时满足：
  - 同一个人既是目标任务 owner，又在其他上下文里扮演 reviewer / ops owner / approver。
  - 至少两个干扰上下文使用与目标任务相似的 `owner`、`blocker`、`ready`、`收口` 词汇。
  - 至少有一条消息显式说“这不是目标任务 owner 变更”，否则干扰太弱。
- `message_beats` 必须让这些干扰 block 真正进入对话，而不是只停留在结构字段里。
- query 必须逼系统显式排除这些上下文噪声，只回答目标任务。
- 默认 `hard` 下必须按企业版密度生成：至少满足更高的 shared actor、context block 和并行讨论覆盖，不得只用 3 个左右角色完成示例。

## 禁止

- 不要把干扰上下文重新写成 `distractor task`。
- 不要把其他任务的名字直接当成正式 task id 列进 `story_plan.task`。
- 不要只写“有干扰”，但没有具体 block 类型和污染机制。
- 不要只问单个显式字段而不要求系统说明“哪些上下文不该混入”。

## JSON 示例：完整 `task_actor_layout`

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
    },
    {
      "context_ref": "ctx_release_sync",
      "context_label": "并行发布节奏同步",
      "noise_source_type": "parallel_discussion_noise",
      "relationship_to_target": "另一个并行同步会反复提到 owner、窗口和 ready，很适合制造 scope pollution。"
    }
  ],
  "actor_task_roles": [
    {
      "actor_id": "alice",
      "task_id": "FEISHU-201",
      "role": "target_owner"
    },
    {
      "actor_id": "alice",
      "context_ref": "ctx_doc_review",
      "role": "reviewer"
    },
    {
      "actor_id": "bob",
      "context_ref": "ctx_ops_rehearsal",
      "role": "ops_owner"
    },
    {
      "actor_id": "carol",
      "context_ref": "ctx_release_sync",
      "role": "release_coordinator"
    }
  ]
}
```

## JSON 示例：最小完整 `story_plan`

```json
{
  "story_id": "story_case_0201_anti_interference",
  "case_id": "case_0201_anti_interference",
  "family_id": "anti_interference",
  "task": {
    "task_id": "FEISHU-201",
    "task_name": "支付灰度放量准备",
    "role": "target_task"
  },
  "actors": [
    {"actor_id": "alice", "display_name": "Alice", "role": "project_manager"},
    {"actor_id": "bob", "display_name": "Bob", "role": "ops_manager"},
    {"actor_id": "carol", "display_name": "Carol", "role": "release_manager"}
  ],
  "task_actor_layout": {
    "target_task_id": "FEISHU-201",
    "shared_actors": ["alice", "bob"],
    "interference_context_blocks": [
      {
        "context_ref": "ctx_doc_review",
        "context_label": "并行文档收口讨论",
        "noise_source_type": "shared_actor_noise",
        "relationship_to_target": "Alice 在文档收口里是 reviewer，不应被误当成新的 owner 变更。"
      },
      {
        "context_ref": "ctx_ops_rehearsal",
        "context_label": "运维演练 blocker 讨论",
        "noise_source_type": "similar_wording_noise",
        "relationship_to_target": "Bob 在这里说的 blocker 和 ready 不是 FEISHU-201 的当前 blocker。"
      },
      {
        "context_ref": "ctx_release_sync",
        "context_label": "并行发布节奏同步",
        "noise_source_type": "parallel_discussion_noise",
        "relationship_to_target": "并行同步里的 window/ready 讨论会和 FEISHU-201 混淆。"
      }
    ],
    "actor_task_roles": [
      {"actor_id": "alice", "task_id": "FEISHU-201", "role": "target_owner"},
      {"actor_id": "alice", "context_ref": "ctx_doc_review", "role": "reviewer"},
      {"actor_id": "bob", "context_ref": "ctx_ops_rehearsal", "role": "ops_owner"},
      {"actor_id": "carol", "context_ref": "ctx_release_sync", "role": "release_coordinator"}
    ]
  },
  "state_changes": [
    {
      "task_id": "FEISHU-201",
      "field": "owner",
      "sequence": [{"value": "Alice", "status": "current"}]
    },
    {
      "task_id": "FEISHU-201",
      "field": "blocker",
      "sequence": [{"value": "支付风控回归未完成", "status": "current"}]
    }
  ],
  "message_beats": [
    {
      "beat_id": "beat_001",
      "speaker": "Alice",
      "session_id": "main_chat",
      "message_intent": "FEISHU-201 当前由 Alice 负责收口，真正 blocker 还是支付风控回归没有完成。"
    },
    {
      "beat_id": "beat_002",
      "speaker": "Bob",
      "session_id": "main_chat",
      "message_intent": "运维演练那边也卡在 blocker，但这是另外一条并行讨论，不是 FEISHU-201 的 owner 变更。"
    },
    {
      "beat_id": "beat_003",
      "speaker": "Carol",
      "session_id": "thread_docs",
      "message_intent": "Alice 晚上还要审文档收口，不过那只是 reviewer 身份，不代表 FEISHU-201 再次换 owner。"
    }
  ],
  "planned_probe_queries": [
    {
      "query": "FEISHU-201 当前 owner 和 blocker 是什么？哪些上下文不应该混入当前答案？为什么文档收口和运维演练里的说法不属于 FEISHU-201？",
      "expected_good_behavior": "只回答 Alice 是当前 owner、支付风控回归未完成是当前 blocker，并明确排除文档收口 reviewer 身份和运维演练 blocker 讨论。"
    }
  ]
}
```

## V3 Phase 1 对接位置

`anti_interference` 被选中时，本 skill 必须参与这些 stage：

- `task-actor-layout`：定义 shared actors、parallel context、相似措辞干扰和 actor/context role。
- `state-trajectory`：定义目标任务 current state，以及哪些上下文不能污染目标答案。
- `coverage-spec`：要求干扰上下文、排除线索和目标 current state 都必须在真实消息中落地。
- `story-beats`：安排 target fact、shared actor noise、similar wording noise、explicit exclusion 等 beat。
- `conversation-plan`：把干扰与排除线索写成自然消息，但不能让干扰上下文变成目标任务事实。

本 family 的关键不是“多写几个噪声消息”，而是让系统必须从 shared actor 和相似措辞中排除不属于目标任务的上下文。
