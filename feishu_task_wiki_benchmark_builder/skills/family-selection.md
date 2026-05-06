# family-selection

## 什么时候使用

当当前任务是在 single case 或 batch generation 中决定“本次到底测哪一类 memory capability family”时使用。

## 这一步要解决什么

- 单 case 时选择唯一 family
- batch 时确保三类正式 family 都能覆盖
- 保证选择过程 deterministic
- 保证所选 family 能对齐项目要求里的 benchmark 测试类型

## 输入

- `seed`
- 用户是否显式指定 `family_id`
- batch quota policy

## 输出

- `input/family_selection.json`

## 当前正式三类 family

### 1. `anti_interference`

- 中文名：抗干扰
- 对应项目需求：
  - 抗干扰测试
- 主要要测什么：
  - 在大量无关任务、共享角色、相似字段混入后，系统还能不能只捞目标任务的关键信息
- 什么时候优先选它：
  - 你要验证“信息很多、噪音很多，但系统还能精准回忆”

### 2. `contradiction_update`

- 中文名：矛盾更新
- 对应项目需求：
  - 矛盾更新测试
- 主要要测什么：
  - 当先后输入冲突口径后，系统能不能理解时间顺序，并让新版本覆盖旧版本
- 什么时候优先选它：
  - 你要验证“旧记忆是否会被正确覆写”

### 3. `evidence_dependency_reasoning`

- 中文名：证据验证 + 依赖传播
- 对应 benchmark 口径：
  - 证据验证结果
  - 企业任务网络 / 依赖传播验证
- 主要要测什么：
  - 系统给出 blocker 或风险结论时，能不能说明依据来自哪条消息、谁明确说过、哪些只是转述或猜测
  - 系统能不能继续解释该证据对应的上游状态如何影响目标任务和下游任务
- 什么时候优先选它：
  - 你要验证“系统不是只会总结，而是真的能给证据并解释依赖链”

## 关于“效能指标验证”

`效能指标验证` 不是单独的 case family。

它是一个 **跨 family 的最终评测维度**，应该在 `evaluation` 和最终 benchmark report 里体现，例如：

- 使用前后操作步数对比
- 输入字符数对比
- 命中率 / 节省时间对比

也就是说：

- family-selection 负责选择“测哪种记忆能力”
- `效能指标` 负责证明“这种能力带来了多少实际收益”

## 规则

- 如果用户显式指定 family，优先服从显式指定
- 如果是 single case 且未指定 family，按 deterministic seed 规则选择
- 如果是 batch，必须覆盖三类正式 family
- batch 至少要覆盖项目需求里强制最核心的两类：
  - `anti_interference`
  - `contradiction_update`
- batch 还必须补齐第三类：
  - `evidence_dependency_reasoning`
- 这一步只做选择，不开始写故事
- 这一步不要提前写 capability brief

## 推荐选择策略

### single case

- 默认只选 1 个 family
- 如果用户没有显式要求，优先按 seed deterministic 选择
- 但如果当前目标非常明确，也可以按目标直选：
  - 验证抗干扰：选 `anti_interference`
  - 验证矛盾更新：选 `contradiction_update`
  - 验证证据归因和依赖传播：选 `evidence_dependency_reasoning`

### batch

- 最低要求：
  - 必须覆盖 `anti_interference`
  - 必须覆盖 `contradiction_update`
  - 必须覆盖 `evidence_dependency_reasoning`
- 最终 report 还必须单独给出效能指标结果，而不是把效能指标误当成第五类 family

## 不要做什么

- 不要设计企业场景
- 不要设计角色
- 不要写 message beats
- 不要写最终 probe wording
- 不要把“效能指标验证”误当成 case family
