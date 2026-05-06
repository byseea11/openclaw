# case-world

## 什么时候使用

当 capability brief 已经确定，当前要把 brief 业务化成真实企业协作场景时使用。

## 这一步要解决什么

- 让 family 在场景里自然发生
- 让 brief 的 required structure 在场景里天然成立
- 为 story-plan 提供合理业务语境

## 输入

- `case_spec`
- `memory_capability_brief`

## 输出

- `input/case_world.json`

## 关键规则

- case world 不是自由写世界
- 它必须服务 brief
- 它必须解释为什么该 family 会在这个场景里自然发生
- 它必须让后续 tasks、actors、state_changes 能合理落地
- `evidence_dependency_reasoning` 场景必须天然同时支持证据强弱差异和 upstream -> downstream 依赖传播

## 不要做什么

- 不要提前写 message beats
- 不要提前写最终 probe wording
- 不要把 story-plan 内容揉到 case-world 里
