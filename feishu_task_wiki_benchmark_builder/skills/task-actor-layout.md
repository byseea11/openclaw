# task-actor-layout

## 职责

这个 skill 负责定义 phase1 的 actor/context identity owner。它先把 actor roster、shared actors、overlap 和 family-specific context identity 定死，后续阶段只能引用，不能重造。

## 硬规则

- 必须产出：
  - `case_id`
  - `family_id`
  - `task_id`
  - `actors`
  - `task_actor_layout`
- `actors` 是 canonical actor roster。
- `task_actor_layout` 是 canonical overlap / context identity 结构。
- 后续阶段不得新增未在本阶段声明的：
  - actor
  - actor_id
  - shared_actor
  - context_ref
- actor roster 必须先定死，再展开 world / beats / conversation。
- family-specific context skill 里定义的 role/context block 必须在本阶段先落 identity。
- 应吸收旧版 `task_actor_layout_generator.py` 的思路：
  - target scope 先定
  - overlap 先定
  - shared actor 先定
  - 干扰/依赖上下文先定

## 禁止

- 不要在后续 `story-plan` 才临时发明新 actor。
- 不要把 distractor / dependency context 继续写成并列正式 task。
- 不要只写 prose，不给结构化 actor/context identity。

## JSON 示例

```json
{
  "case_id": "case_0203_evidence_dependency_reasoning",
  "family_id": "evidence_dependency_reasoning",
  "task_id": "FEISHU-203",
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
      }
    ],
    "actor_task_roles": [
      {"actor_id": "carol", "context_ref": "ctx_upstream_window", "role": "verified_source"},
      {"actor_id": "xavier", "task_id": "FEISHU-203", "role": "target_owner"}
    ]
  }
}
```

## V3 Phase 1 对接位置

在细分 Phase 1 链路里，`task-actor-layout` 读取 `family-selection`、`capability-brief` 和当前 family context skill，生成后续阶段唯一可引用的 actor/context identity。

不同 family 的重点：

- `anti_interference`：必须落 shared actors、interference context blocks、相似措辞或并行上下文关系。
- `contradiction_update`：必须落 initial/historical/current 相关 actor role，以及 revision context blocks。
- `evidence_dependency_reasoning`：必须落 verified anchor、hearsay、ambiguous、downstream impact 等 dependency context blocks。

本阶段不引入旧版 distractor task 作为并列正式 task。干扰、修正和依赖都应优先表达为 context block、actor role 和 source 分布。
