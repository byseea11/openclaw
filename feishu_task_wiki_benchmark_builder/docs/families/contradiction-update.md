# contradiction_update

## 本质

这类 family 测的是：当同一字段被多次更新后，系统能不能正确分辨 current、historical 和 stale。

## 为什么默认记忆系统容易失败

因为系统常常会记住最早出现、最明确的值，却忽略后续修正，或者无法稳定理解“之前口径作废”。

## 失败原理

失败不是单纯 missing memory，而是时序和 supersedes 关系没有被建模。

## 对后续阶段的帮助

### capability-brief

- 强调必须有多轮更新和 current/historical 区分

### case-world

- 强调场景要自然支持重复修正，例如 owner、窗口、排期等

### story-plan

- 强调 `state_changes` 和 planned probes 是重点

## 有效 probe

- 同时追问当前值和历史值
- 要求系统明确指出哪个口径已失效

## 无效 probe

- 只问“最开始是谁负责”
- 只问单一当前字段但不考 stale distinction

## Observed Validation / Eval 重点

- 更新是否真的在消息里逐步发生
- 当前值和历史值是否都能在 observed data 找到证据
- probe 是否真的测试 supersession 而不是普通字段抽取
