# story-plan

## 什么时候使用

当 family、brief 和 case world 已经确定，当前要生成唯一核心中间 artifact 时使用。

## 这一步要解决什么

统一生成 `story_plan.json`，并确保它足以驱动 command-plan、execute、collect、validation 和 eval。

## 必须包含的 section

- `tasks`
- `actors`
- `task_actor_layout`
- `state_changes`
- `message_beats`
- `planned_probe_queries`

## family 不同，重点不同

- `anti_interference`
  重点在 `task_actor_layout + planned_probe_queries`
- `contradiction_update`
  重点在 `state_changes + planned_probe_queries`
- `evidence_dependency_reasoning`
  重点在 `task_actor_layout + state_changes + message_beats + planned_probe_queries`

## probe 规则

- planned probe query 不能只是问显式字段
- 必须真正测试当前 family 的 memory capability
- 必须让好系统和差系统拉开差异
- 对第三类 family，probe 必须同时要求证据归因和影响链解释

## 不要做什么

- 不要重新拆出 `state_trajectory.json`
- 不要重新拆出 `probe_targets.json`
- 不要重新拆出 `memory_case_contract.json`
