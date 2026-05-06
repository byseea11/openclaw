# anti_interference

## 本质

这类 family 测的是：当多个任务共享角色、词汇和上下文时，系统能不能只回答目标任务的当前上下文。

## 为什么默认记忆系统容易失败

因为默认记忆系统很容易把“同一个人”“相似任务名”“相近 blocker”拼接成一个模糊 summary，最后把其他任务的信息错带进目标任务答案。

## 失败原理

失败通常不是因为没记住，而是因为记住了太多相似片段，却没有足够强的 task boundary。

## 对后续阶段的帮助

### capability-brief

- 强调必须有 target task、distractor tasks 和 shared actors

### case-world

- 强调场景里必须天然存在多任务并行和共享角色

### story-plan

- 强调 `task_actor_layout` 和 `planned_probe_queries` 是重点

## 有效 probe

- 询问目标任务当前负责人、状态或 blocker
- 明确要求不要混入相似任务信息

## 无效 probe

- 只问一个显式字段、完全不制造相似任务干扰
- 不要求区分目标任务和 distractor task

## Observed Validation / Eval 重点

- shared actor 是否真的出现在多个任务中
- distractor 信息是否真的进入了 observed messages
- probe 是否真的需要系统做 task boundary 判断
