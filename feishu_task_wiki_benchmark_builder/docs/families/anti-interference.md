# anti_interference

## 本质

这类 family 测的是：当单个目标任务周围存在来自其他任务的共享角色、相似措辞和并行协作上下文时，系统能不能只回答目标任务的当前上下文。

## 为什么默认记忆系统容易失败

因为默认记忆系统很容易把“同一个人”“相似任务名”“相近 blocker”拼接成一个模糊 summary，最后把其他任务的信息错带进目标任务答案。

## 失败原理

失败通常不是因为没记住，而是因为记住了太多相似片段，却没有足够强的 task boundary。

## 为什么这个 hard case 会难倒弱记忆系统

- 同一个人同时在目标任务和并行上下文里出现，弱记忆系统会把 reviewer / ops owner 身份拼进目标任务答案。
- 多条消息都使用 `owner`、`blocker`、`ready`、`收口` 这类相似词，静态 summary 很容易把别处的 blocker 当成当前 blocker。
- 即使消息里明说“这不是目标任务 owner 变更”，只做关键词拼接的系统仍然可能把它当成新的 owner 证据。

## 最容易误判的消息

- “这不是目标任务 owner 变更”这类带否定和排除语义的消息。
- shared actor 在其他上下文里的角色说明。
- 相似措辞但不同 scope 的 blocker / ready 描述。

## 对后续阶段的帮助

### capability-brief

- 强调必须有单一 target task、shared actors 和来自其他任务的干扰上下文
- 当前 difficulty 会额外注入 actors、departments 和 session 数量目标，不能只保留最小三人示例

### case-world

- 强调场景里必须天然存在其他任务带来的并行上下文和共享角色

### story-plan

- 强调 `task_actor_layout` 和 `planned_probe_queries` 是重点
- 强调 `interference_context_blocks` 必须把 shared actor noise、相似措辞噪声或并行讨论噪声结构化出来
- 强调最终规模必须服从 runtime 注入的数字目标，而 `shared_actor_noise`、role slots、context slots 语义由 family skills 自己定义

## 有效 probe

- 询问目标任务当前负责人、状态或 blocker
- 明确要求不要混入相似任务信息

## 无效 probe

- 只问一个显式字段、完全不制造相似任务干扰
- 不要求区分目标任务和其他任务上下文

## Observed Validation / Eval 重点

- shared actor 是否真的同时出现在目标任务和其他任务上下文中
- distractor 信息是否真的进入了 observed messages
- probe 是否真的需要系统做 task boundary 判断
- `interference_context_blocks` 是否都在消息里找得到对应噪声来源
