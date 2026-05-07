# contradiction_update

## 本质

这类 family 测的是：当同一字段被多次更新后，系统能不能正确分辨 current、historical 和 stale。

## 为什么默认记忆系统容易失败

因为系统常常会记住最早出现、最明确的值，却忽略后续修正，或者无法稳定理解“之前口径作废”。

## 失败原理

失败不是单纯 missing memory，而是时序和 supersedes 关系没有被建模。

## 为什么这个 hard case 会难倒弱记忆系统

- 早期口径通常写得最明确，弱记忆系统容易把最早出现的 owner 或日期直接保留下来。
- 中间修正是真实存在且一度有效的，所以不能简单当噪声丢掉，这会逼系统正确区分 historical 和 current。
- 最终消息虽然给了强 supersession clue，但如果系统没有建模“作废关系”，仍会把旧值和当前值并列保留。

## 最容易误判的消息

- 第一轮最明确的 owner / window 宣布。
- 中间那轮看起来很“正式”的修正消息。
- 最终带“之前口径作废”的 current-state 确认消息。

## 对后续阶段的帮助

### capability-brief

- 强调必须有多轮更新和 current/historical 区分
- 当前 difficulty 会额外注入 actors、departments 和 session 数量目标，不能把修正链压缩成最小示例

### case-world

- 强调场景要自然支持重复修正，例如 owner、窗口、排期等

### story-beats / conversation-plan

- 强调 `state_changes` 和 planned probes 是重点
- 强调 `revision_context_blocks` 和 `supersession_clues` 必须明确指出哪一轮口径已经作废
- 强调最终规模必须服从 runtime 注入的数字目标，而 stale/current/supersession 和 revision field 语义由 family skills 自己定义

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
- `revision_context_blocks` 是否能把 stale / historical / current 的语义边界表达清楚
