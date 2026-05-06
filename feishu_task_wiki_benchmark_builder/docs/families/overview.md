# Memory Capability Families Overview

## 为什么现在收成三类

当前正式比赛 family 只有三类：

- `anti_interference`
  - 对应项目需求里的抗干扰测试
- `contradiction_update`
  - 对应项目需求里的矛盾更新测试
- `evidence_dependency_reasoning`
  - 对应证据验证结果 + 企业任务网络 / 依赖传播验证

这样收口的原因是：

- 前两类直接对应项目需求里明确点名的强制测试
- 第三类把“证据可追溯”和“依赖传播”合成一个更贴近真实企业协作的问题：系统必须先知道该信谁，才能正确判断影响链
- 正式 family 更少，case 归因更干净，builder 也更容易围绕比赛口径组织数据

## 关于效能指标验证

项目需求里的 `效能指标验证` 不是第四类 family。

它是一个跨 family 的评测维度，用来证明：

- 命中率有没有提升
- 操作步数有没有下降
- 输入字符数有没有减少
- 时间成本有没有下降

所以：

- family 负责定义“测哪种记忆能力”
- 效能指标负责定义“这种能力有没有带来真实收益”

## 它们为什么不能互相替代

- `anti_interference` 关注“不要把别的任务混进来”，不等于会处理冲突更新
- `contradiction_update` 关注“旧口径是否已被覆盖”，不等于会判断证据强弱或依赖传播
- `evidence_dependency_reasoning` 关注“谁的话可信、这条证据怎样影响任务网络”，不等于会严格隔离 shared actor 噪音

## 单 case 为什么默认只挂一个 family

- 避免归因变脏
- 避免后续 eval 不知道失败到底来自哪种能力缺失
- 避免 story-plan 同时服务多个主目标导致 case 不纯

## 这份总览为后续阶段提供什么帮助

- 帮 `family-selection` 选对 case 的主测试目标
- 帮 `capability-brief` 避免把不同 family 的约束混在一起
- 帮评审者判断一条 case 是否真的在测它声称的 family
