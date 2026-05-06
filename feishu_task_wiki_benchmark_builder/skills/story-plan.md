# story-plan

## 职责

这个 skill 负责约束 `story-plan` 阶段生成唯一核心中间 artifact：`story_plan.json`。

## 统一 contract

- `story_plan.json` 必须包含：
  - `task`
  - `actors`
  - `task_actor_layout`
  - `state_changes`
  - `message_beats`
  - `planned_probe_queries`
- `task` 必须是 object，并且它是唯一正式 task。
- `actors` 必须是 list。
- `task_actor_layout` 必须是 object。
- `state_changes` 必须是 list。
- `message_beats` 必须是 list。
- `planned_probe_queries` 必须是 list。
- distractor、upstream、downstream 这类内容只能作为 family-specific context blocks 出现，不能再作为并列正式 task 出现。
- `message_beats` 必须能被 `command-plan` 直接映射成可执行动作。
- `planned_probe_queries` 是 query contract，不单独拆 probe artifact。
- query 不能只是问显式字段，必须真正测试当前 family 的 memory capability，让好系统和差系统拉开差异。
- `actors` 数量必须落在当前 difficulty profile 的 `character_count_min/max` 范围内。
- `message_beats` 的 session 分布必须满足当前 difficulty 的 `session_blueprint`，不能退化成单 session 单线程。
- 共享角色、状态段数、依赖 hop 数等最低复杂度必须服从当前 family 的 settings summary，而不是自行简化。

## family-specific hard-case 要求

- `anti_interference`
  - 至少满足当前 family 设置的 `min_interference_context_blocks` 和 `min_shared_actors`
  - 至少包含 `shared_actor_noise`、`similar_wording_noise`、`parallel_discussion_noise`
  - 至少有一条消息显式提醒“这不是目标任务 owner 变更”
- `contradiction_update`
  - 至少满足当前 family 设置的 `min_state_tracks` 和 `min_stale_states`
  - 至少同时修正 `owner` 和 `release_window`
  - 至少有一条强 supersession clue，例如“之前口径作废”
- `evidence_dependency_reasoning`
  - 至少满足当前 family 设置的 `min_dependency_hops` 和 `min_cross_source_updates`
  - 至少同时包含 `verified_anchor`、`hearsay_channel`、`ambiguous_channel`、`downstream_impact`
  - 最终 summary 必须依赖 verified anchor 才能答对

## 禁止

- 不要重新拆出 `state_trajectory.json`。
- 不要重新拆出 `probe_targets.json`。
- 不要重新拆出 `memory_case_contract.json`。
- 不要让 `expected_good_behavior` 只是重复 query。
- 不要把 distractor 写成正式 `task`。
- 不要把某个 section 写成 string 或 object 来替代应为 list 的字段。
- 不要把规模要求偷降到 3-4 个角色、1-2 个 session 这种过弱版本，除非当前 difficulty settings 明确允许。

## JSON 示例：`anti_interference`

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
        "relationship_to_target": "Alice 在文档收口里是 reviewer，不应被误当成 FEISHU-201 的 owner 再次变更。"
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

## JSON 示例：`contradiction_update`

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

## JSON 示例：`evidence_dependency_reasoning`

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
    {"actor_id": "xzy", "display_name": "xzy", "role": "target_owner"}
  ],
  "task_actor_layout": {
    "target_task_id": "FEISHU-203",
    "shared_actors": ["carol", "xzy"],
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
      {"actor_id": "xzy", "task_id": "FEISHU-203", "role": "target_owner"},
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
      "speaker": "xzy",
      "session_id": "thread_release",
      "message_intent": "结论先按 Carol 的正式确认走：当前真正 blocker 是迁移窗口未锁定，这会同时卡住 FEISHU-203 和后面的回滚预案验收。"
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
