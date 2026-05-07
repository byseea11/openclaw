# Evaluation Design

## Observed Validation

`pre-annotation-validate` 的角色是判断 case 有没有真的落地。

它不是：

- gold
- replay eval
- baseline eval

它要回答的是：这条 case 还能不能作为有效 benchmark case 继续往后走。

## Annotation Gold

`annotation-gold` 必须严格基于 observed messages 回标。

原因：

- planned story 只是生成目标，不代表真实发生
- 只有 collect 之后的 observed data 才能成为 gold 的证据来源
- 这样才能避免“计划写得很好，但消息根本没落地”时 gold 仍然看起来正确

## Query Benchmark

`query-benchmark` 负责把 `planned_probe_queries` 收口成正式评测问题。

目标：

- 保留 family-specific probe intent
- 统一 Task Wiki 和 baseline 的评测输入
- 如果 family 是 `evidence_dependency_reasoning`，query 必须同时考察证据归因和依赖传播

## Phase 3 Cross-system Eval

当前正式对比对象固定为：

- `task_wiki_3_layer`
- `openclaw_original`

Phase 3 不能使用 synthetic family penalty。它必须读取同一批 observed messages、同一份 query benchmark 和同一份 semantic gold，分别比较两个系统的答案和证据。

核心维度：

- 答案是否正确。
- 是否输出证据。
- 证据是否命中 gold supporting message ids。
- 证据是否来自目标 task / 正确 session / 正确 source。
- 证据是否避开干扰、旧状态、传闻和个人私有信息。

## 效能指标验证

`效能指标验证` 是最终 benchmark report 的必要维度，但它不是独立 family。

它应该跨不同 family 汇总，例如：

- 命中率提升
- 证据输出率提升
- 证据准确率提升
- 平均检索步骤减少
- 平均输入字符数减少
- 平均完成时间减少

评估原则：

- family 结果告诉我们“系统记没记住”
- 效能指标告诉我们“记住之后有没有实际价值”
- 正式 family 不把效能指标扩成独立 family
