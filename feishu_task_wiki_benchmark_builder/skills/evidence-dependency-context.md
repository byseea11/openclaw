# evidence-dependency-context

## 职责

这个 skill 定义 `evidence_dependency_reasoning` family 的证据与依赖上下文规则。它约束的是证据梯度和影响链，而不是并列正式 task。

## 硬规则

- 依赖与证据上下文只能作为 `dependency_context_blocks` 出现。
- 每个 block 必须说明 `context_ref`、`context_label`、`dependency_role`、`evidence_strength`、`impact_on_target`。
- `dependency_role` 只允许 `verified_anchor`、`hearsay_channel`、`ambiguous_channel`、`downstream_impact`。
- hard case 必须同时覆盖正式确认、传闻、模糊判断、下游影响和目标总结。
- `story-beats` 必须把 verified anchor、ambiguous claim、hearsay、impact chain 和 target summary 全部落地。
- `conversation-plan` 必须让不同证据强度来自不同 source/session，不能把所有信息压成单句总结。
- query 必须同时要求当前 blocker、依据来源、哪些说法不能当正式确认、依赖如何影响目标任务。

## 禁止

- 不要把 upstream / downstream 写成并列正式 task。
- 不要只给 blocker 结论，不给证据强度差异。
- 不要把 hearsay 或 ambiguous 直接升级成 verified fact。
- 不要把 query 写成“谁说过什么”的简单检索题。

## JSON 示例：`task_actor_layout`

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
    {"actor_id": "xavier", "task_id": "FEISHU-203", "role": "target_owner"}
  ]
}
```

## 对接位置

- `task-actor-layout`：定义 verified、hearsay、ambiguous 和 downstream actor/context identity。
- `state-trajectory`：把依赖状态和目标任务 current-state 影响链分开。
- `story-beats`：确保每类证据强度都有可观测消息。
- `conversation-plan`：生成跨 source 证据对话，让 OpenClaw 原生 summary 容易把低可信信息误升级。
