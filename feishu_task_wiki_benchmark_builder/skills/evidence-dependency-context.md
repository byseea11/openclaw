# evidence-dependency-context

## 职责

这个 skill 负责定义 `evidence_dependency_reasoning` family 的证据与依赖上下文规则。它约束的是证据梯度和影响链，而不是并列正式 task。

## 硬规则

- 依赖与证据上下文只能作为 `dependency_context_blocks` 出现。
- 每个 block 必须说明：
  - `context_ref`
  - `context_label`
  - `dependency_role`
  - `evidence_strength`
  - `impact_on_target`
- `dependency_role` 只允许：
  - `verified_anchor`
  - `hearsay_channel`
  - `ambiguous_channel`
  - `downstream_impact`
- hard case 必须同时满足：
  - 至少有一条正式确认消息。
  - 至少有一条“我听别人说”的缓解传闻。
  - 至少有一条目标负责人自己的模糊判断。
  - 至少有一条依赖传播到下游的影响说明。
  - 最终 summary 必须依赖 verified anchor 才能答对。
- `message_beats` 必须同时落地：
  - verified anchor
  - ambiguous claim
  - hearsay
  - impact chain
  - target summary
- query 必须同时要求：
  - 当前真实 blocker 是什么
  - 依据来自谁、哪条消息
  - 哪些说法不能当正式确认
  - 这个 blocker 如何影响目标任务和下游影响
- 默认 `hard` 下必须按企业版密度生成：依赖 hop、cross-source update、证据梯度和下游影响都应明显高于最小示例，不得退化成单条上游确认加一句总结。

## 禁止

- 不要把 upstream / downstream 写成并列正式 task。
- 不要只给 blocker 结论，不给证据强度差异。
- 不要把 hearsay 或 ambiguous 直接升级成 verified fact。
- 不要把 query 写成“谁说过什么”的简单检索题。

## JSON 示例：完整 `task_actor_layout`

```json
{
  "target_task_id": "FEISHU-203",
  "shared_actors": ["carol", "xavier"],
  "dependency_context_blocks": [
    {
      "context_ref": "ctx_upstream_window",
      "context_label": "迁移窗口正式确认",
      "dependency_role": "verified_anchor",
      "evidence_strength": "verified",
      "impact_on_target": "窗口今天还没锁定，因此 FEISHU-203 不能对外承诺上线时间。"
    },
    {
      "context_ref": "ctx_window_hearsay",
      "context_label": "窗口缓解传闻",
      "dependency_role": "hearsay_channel",
      "evidence_strength": "hearsay",
      "impact_on_target": "如果误信传闻，系统会过早判断 blocker 已消失。"
    },
    {
      "context_ref": "ctx_target_assessment",
      "context_label": "目标负责人模糊判断",
      "dependency_role": "ambiguous_channel",
      "evidence_strength": "ambiguous",
      "impact_on_target": "模糊判断不能替代正式确认，但很容易被 summary 压成结论。"
    },
    {
      "context_ref": "ctx_downstream_rollback",
      "context_label": "回滚预案验收影响",
      "dependency_role": "downstream_impact",
      "evidence_strength": "derived_from_verified",
      "impact_on_target": "目标任务不锁窗口时，下游回滚预案验收会一起顺延。"
    }
  ],
  "actor_task_roles": [
    {
      "actor_id": "carol",
      "context_ref": "ctx_upstream_window",
      "role": "verified_source"
    },
    {
      "actor_id": "bob",
      "context_ref": "ctx_window_hearsay",
      "role": "hearsay_source"
    },
    {
      "actor_id": "alice",
      "task_id": "FEISHU-203",
      "role": "ambiguous_source"
    },
    {
      "actor_id": "xavier",
      "task_id": "FEISHU-203",
      "role": "target_owner"
    },
    {
      "actor_id": "alice",
      "context_ref": "ctx_downstream_rollback",
      "role": "rollback_owner"
    }
  ]
}
```

## JSON 示例：最小完整 `story_plan`

```json
{
  "story_id": "story_case_0203_evidence_dependency_reasoning",
  "case_id": "case_0203_evidence_dependency_reasoning",
  "family_id": "evidence_dependency_reasoning",
  "task": {
    "task_id": "FEISHU-203",
    "task_name": "支付网关灰度发布",
    "role": "target_task"
  },
  "actors": [
    {"actor_id": "alice", "display_name": "Alice", "role": "release_pm"},
    {"actor_id": "bob", "display_name": "Bob", "role": "ops_partner"},
    {"actor_id": "carol", "display_name": "Carol", "role": "migration_owner"},
    {"actor_id": "xavier", "display_name": "Xavier", "role": "target_owner"}
  ],
  "task_actor_layout": {
    "target_task_id": "FEISHU-203",
    "shared_actors": ["carol", "xavier"],
    "dependency_context_blocks": [
      {
        "context_ref": "ctx_upstream_window",
        "context_label": "迁移窗口正式确认",
        "dependency_role": "verified_anchor",
        "evidence_strength": "verified",
        "impact_on_target": "窗口今天还没锁定，因此 FEISHU-203 不能对外承诺上线时间。"
      },
      {
        "context_ref": "ctx_window_hearsay",
        "context_label": "窗口缓解传闻",
        "dependency_role": "hearsay_channel",
        "evidence_strength": "hearsay",
        "impact_on_target": "误信传闻会导致系统错误地下结论说 blocker 已消失。"
      },
      {
        "context_ref": "ctx_target_assessment",
        "context_label": "目标负责人模糊判断",
        "dependency_role": "ambiguous_channel",
        "evidence_strength": "ambiguous",
        "impact_on_target": "模糊判断不能替代正式确认，但很容易被压成一句看似可靠的 summary。"
      },
      {
        "context_ref": "ctx_downstream_rollback",
        "context_label": "回滚预案验收影响",
        "dependency_role": "downstream_impact",
        "evidence_strength": "derived_from_verified",
        "impact_on_target": "目标任务不锁窗口时，下游回滚预案验收会一起顺延。"
      }
    ],
    "actor_task_roles": [
      {"actor_id": "carol", "context_ref": "ctx_upstream_window", "role": "verified_source"},
      {"actor_id": "bob", "context_ref": "ctx_window_hearsay", "role": "hearsay_source"},
      {"actor_id": "alice", "task_id": "FEISHU-203", "role": "ambiguous_source"},
      {"actor_id": "xavier", "task_id": "FEISHU-203", "role": "target_owner"},
      {"actor_id": "alice", "context_ref": "ctx_downstream_rollback", "role": "rollback_owner"}
    ]
  },
  "state_changes": [
    {
      "task_id": "FEISHU-203",
      "field": "upstream_dependency_status",
      "sequence": [
        {"value": "未确认", "status": "initial"},
        {"value": "Carol 明确表示窗口还没锁定", "status": "current"}
      ]
    },
    {
      "task_id": "FEISHU-203",
      "field": "release_commitment",
      "sequence": [
        {"value": "计划 5 月 8 日上线", "status": "initial"},
        {"value": "等待正式窗口确认后再承诺", "status": "current"}
      ]
    },
    {
      "task_id": "FEISHU-203",
      "field": "downstream_dependency_impact",
      "sequence": [
        {"value": "待验收", "status": "initial"},
        {"value": "等待主任务窗口明确后再验收", "status": "current"}
      ]
    }
  ],
  "message_beats": [
    {
      "beat_id": "beat_001",
      "speaker": "Carol",
      "session_id": "main_chat",
      "message_intent": "我刚和迁移负责人确认过，窗口今天还没锁定，所以 FEISHU-203 先不要对外承诺 5 月 8 日上线。"
    },
    {
      "beat_id": "beat_002",
      "speaker": "Bob",
      "session_id": "main_chat",
      "message_intent": "我听别人说窗口其实差不多定了，感觉可以先照常往外报，但我没看到正式确认。"
    },
    {
      "beat_id": "beat_003",
      "speaker": "Alice",
      "session_id": "thread_release",
      "message_intent": "直觉上风险可能没那么大，不过如果没有正式窗口邮件，FEISHU-203 这边还是不敢锁最终时间。"
    },
    {
      "beat_id": "beat_004",
      "speaker": "Alice",
      "session_id": "thread_release",
      "message_intent": "如果 FEISHU-203 不能锁上线窗口，那回滚预案验收也只能一起顺延。"
    },
    {
      "beat_id": "beat_005",
      "speaker_actor_id": "xavier",
      "speaker": "Xavier",
      "session_id": "thread_release",
      "message_intent": "结论先按 Carol 的确认走：当前真正 blocker 是迁移窗口未锁定，这会同时卡住 FEISHU-203 和后面的回滚预案验收。"
    }
  ],
  "planned_probe_queries": [
    {
      "query": "FEISHU-203 当前真实 blocker 是什么？依据来自谁、哪条消息？Bob 和 Alice 的说法为什么不能当正式确认？这个 blocker 如何影响后续回滚预案验收？",
      "expected_good_behavior": "应以 Carol 的正式确认作为主要依据，指出真正 blocker 是迁移窗口未锁定；说明 Bob 是 hearsay、Alice 是模糊判断，二者都不能替代正式确认；并解释为什么这会顺延后续回滚预案验收。"
    }
  ]
}
```

## V3 Phase 1 对接位置

`evidence_dependency_reasoning` 被选中时，本 skill 必须参与这些 stage：

- `task-actor-layout`：定义 verified anchor、hearsay channel、ambiguous channel、downstream impact 等 context block。
- `state-trajectory`：定义 upstream evidence 如何影响目标任务 current state，以及如何传播到 downstream impact。
- `coverage-spec`：要求 verified、ambiguous、hearsay、impact chain 和 target summary 都必须在真实消息中落地。
- `story-beats`：安排 evidence anchor、ambiguous claim、hearsay、dependency impact、target conclusion 等 beat。
- `conversation-plan`：把证据梯度写成真实消息，并保持哪些说法可以验证、哪些不能验证的边界。

本 family 的关键是让系统区分证据强度，并解释依赖变化如何影响目标任务，而不是只抽取一句 blocker 结论。
