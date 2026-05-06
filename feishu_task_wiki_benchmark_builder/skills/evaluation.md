# evaluation

## 什么时候使用

当当前任务涉及 observed validation、annotation gold、query benchmark、baseline eval 或 value eval 时使用。

## 这一步要解决什么

- 判断 case 是否真的落地
- 基于 observed messages 回标 gold
- 从 planned probes 收口成正式评测 query
- 比较 Task Wiki 与 baseline 的能力差异

## pre-annotation-validate 应检查什么

- 关键 message beats 是否真的落地
- `story_plan.json` 中的核心目标是否都被 observed data 覆盖
- 这条 case 是否仍然是一个有效 benchmark case

## annotation-gold 为什么只能基于 observed messages

- 因为 gold 必须描述真实落地的消息
- 不能把未发生的计划内容直接标成 gold
- 不能绕过 collect 去写理想化答案

## query-benchmark 做什么

- 把 `planned_probe_queries` 收口成正式 query benchmark
- 保留 probe 的能力目标
- 让后续 replay / baseline 有统一评测输入
- 如果是 `evidence_dependency_reasoning`，query 必须同时保留证据归因和 dependency impact 两个维度

## baseline-eval 和 value-eval 看什么

- `baseline-eval`
  关注不同 baseline mode 的结果分开输出
- `value-eval`
  关注 Task Wiki 相对 baseline 的提升是否真实存在
- `效能指标验证`
  作为跨 family 的 report 维度输出，不单独变成 family
