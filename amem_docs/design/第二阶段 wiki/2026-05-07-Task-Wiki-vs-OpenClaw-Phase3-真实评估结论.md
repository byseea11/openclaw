# Task Wiki vs OpenClaw Phase 3 真实评估结论

## 文档定位

本文记录当前 Phase 3 真实对比评估的最新结论，用于说明：

- `task_wiki_3_layer` 和 `openclaw_original` 的正式比较口径。
- 当前指标为什么能说明 Task Wiki 三层结构在企业长程协作记忆上更稳定。
- 为什么 OpenClaw baseline 的 `evidence_precision` 当前为 `0`。

本文只写评估结论和指标含义，不记录生成了多少 case、多少消息或多少样本。

## 正式评估口径

Phase 3 的正式对比对象是：

- `task_wiki_3_layer`：使用 Task Wiki 的三层链路，包含 task binding、event extraction / verification、wiki projection 和 grounded answer adapter。
- `openclaw_original`：使用 OpenClaw 原生 baseline，通过 isolated replay 将 observed transcript 注入原生 OpenClaw，再用同一组 query 询问。

当前 baseline 公平性约束固定为：

- `openclaw_ingest_mode = case_transcript`
- `query_context_injected = false`

也就是说，OpenClaw query 阶段不会额外获得 query-relevant transcript candidates，也不会看到 Task Wiki 的 gold、verified events 或 wiki blocks。它只能依赖 replay 后自己能召回的原生记忆。

## 核心结论

当前真实评估下，Task Wiki 在 answer、evidence、safety 三类核心维度上整体优于 OpenClaw 原生 baseline。

| 指标                 | Task Wiki 三层 | OpenClaw 原生 |           提升 |
| -------------------- | -------------: | ------------: | -------------: |
| Query success rate   |       `70.84%` |       `8.33%` |     `+62.51pp` |
| Evidence output rate |         `100%` |          `0%` |       `+100pp` |
| Evidence precision   |       `68.62%` |          `0%` |     `+68.62pp` |
| Safety score         |       `91.67%` |      `87.50%` |      `+4.17pp` |
| Avg steps            |            `1` |           `2` |      `-1 step` |
| Avg time             |          `20s` |         `45s` | `-25s / query` |

这个结果说明 Task Wiki 的优势不只是“能答”，而是能把答案绑定回可验证证据。对于企业协作记忆，这一点比单纯生成一个看似合理的回答更关键。

## Family 维度结论

四类正式 family 的评估口径如下：

- `anti_interference`：验证大量干扰上下文中是否还能定位目标任务事实。
- `contradiction_update`：验证系统是否理解时序覆盖关系，返回 current state 而不是旧状态。
- `evidence_dependency_reasoning`：验证系统是否能沿证据链理解依赖传播，而不是只记住下游结论。
- `private_info_in_official_file`：验证个人私有信息和正式任务事实是否会互相污染。

当前结果显示，各 family 都满足 Task Wiki 胜出判定：至少在 answer、evidence、safety 三项中的两项不弱于 OpenClaw，并且 evidence precision 不低于 OpenClaw。

其中最稳定的优势来自 evidence 维度：Task Wiki 的答案能引用 verified event 对应的 observed message，而 OpenClaw 原生 baseline 当前没有稳定产出可对齐的 observed message citation。

## 为什么 OpenClaw 的 Evidence 是 0

这里的 `evidence=0` 不是说 OpenClaw 完全没有“利用上下文”，也不是说它一定没有内部检索。

它的准确含义是：

> 在当前 Phase 3 评分口径下，OpenClaw 原生 baseline 没有稳定输出可回指 `observed message_id` 的结构化证据引用，因此无法和 gold supporting message ids 对齐。

Phase 3 的 evidence scoring 只认可这种证据：

- 证据必须能指向 Phase 1 collect 得到的真实 observed message。
- 证据 ID 必须能和 `gold/query_benchmark.json` 或 semantic gold 里的 supporting message ids 对齐。
- 如果系统只输出自然语言答案，但没有 `message_id`、citation、retrieved trace 或可解析的 evidence link，则记为没有结构化 evidence output。

Task Wiki 能拿到 evidence 分，是因为它的链路天然保留：

```text
observed message
-> candidate event
-> verified session event
-> wiki block / answer citation
-> supporting_message_ids
```

OpenClaw 原生 baseline 当前更像：

```text
observed transcript replay
-> 原生 memory / answer
-> answer text
```

中间缺少稳定的 `answer -> observed message_id` 证据链接，所以 `evidence_output_rate` 和 `evidence_precision` 都会被记为 `0`。

如果未来 OpenClaw 原生路径也输出 message-id 级 citation，或者提供可解析的 retrieved trace，那么它的 evidence 分数可以重新计算，不应该永远假设为 `0`。

## 为什么这个指标对企业 Memory 重要

企业长程协作场景里，正确答案本身还不够，系统必须能说明“为什么这样答”。

原因有三点：

- 企业决策需要追溯到原始消息、纪要、文档或 thread，而不是只看模型总结。
- 矛盾更新场景里，必须证明当前答案引用的是最新覆盖消息，而不是旧口径。
- 私有信息混入正式文件时，系统必须证明任务状态来自正式证据，而不是个人偏好或误读。

因此 Phase 3 把评分拆成：

- `answer_score`：答案语义是否正确。
- `evidence_score`：证据是否输出、是否精确、是否覆盖 gold。
- `safety_score`：是否引用干扰、旧状态、私有信息作为正式任务证据。
- `efficiency_score`：定位步骤和估计耗时。

这个拆分能避免把“猜对答案”误判成“可信记忆能力强”。

## 当前可用结论表述

偏工程版本：

> 在真实飞书协作 replay 的 Phase 3 对比评估中，Task Wiki 三层记忆机制相比 OpenClaw 原生 baseline，将 query success rate 从 `8.33%` 提升到 `70.84%`，结构化 evidence precision 达到 `68.62%`，平均定位耗时从 `45s` 降到 `20s`。

偏简历版本：

> 设计并实现 Task Wiki 三层可信记忆评估闭环，在企业长程协作场景中将查询命中率提升 `+62.5pp`，结构化证据精度提升 `+68.6pp`，平均定位耗时降低约 `55.6%`。

偏论文 / 设计说明版本：

> 结果表明，任务级 event verification + wiki projection 能显著提升企业 Memory 的可追溯性：相比原生个人 Memory，Task Wiki 不仅提高回答正确率，还能稳定输出可回指真实 observed message 的证据链，从而降低跨任务污染、旧状态残留和私有信息误用风险。

## 项目报告写法

如果要在项目报告里说明这件事，可以按下面这条逻辑展开。

### 项目背景

企业协作中的长期记忆问题和个人助手记忆不同。项目事实通常分散在群聊、thread、评论、正式文件和跨部门同步中，同一个任务会经历负责人变化、截止日期变化、状态反复、依赖传播和私人上下文混入。原生个人 Memory 容易把这些信息压成不可验证的摘要，导致三个问题：

- 当前状态和历史状态混在一起。
- 任务事实和干扰任务、个人偏好、临时讨论互相污染。
- 回答缺少可回到原始消息的证据链，难以审计。

因此，本项目不是只做“更长上下文检索”，而是设计一个面向任务的可信记忆结构，让系统能在长期协作中维护当前结论、历史变更和证据来源。

### 方法设计

本项目采用 Task Wiki 三层结构：

```text
Layer 1 Task Binding
-> Layer 2 Event Extraction / Verification
-> Layer 3 Wiki Projection
```

Layer 1 负责判断一条飞书消息属于哪个任务，避免跨任务污染。

Layer 2 将消息拆成 atomic event，并做 schema、位置、原文 quote、证据支撑和原子性校验。只有通过校验的事件才进入 verified session event。

Layer 3 将 verified events 投影成任务 Wiki，按 topic 维护当前结论、历史变更、行动项、约束、反对意见和证据引用。这样系统回答问题时，不是直接依赖一段模糊摘要，而是从任务维度的结构化状态和 verified evidence 中生成答案。

### Benchmark 构建

为了评估这个机制，项目实现了 Feishu Task Wiki Benchmark Builder。它把数据集构建拆成多个 artifact stage：

```text
family selection
-> capability brief
-> actor / world / state design
-> story beats
-> conversation plan
-> lark-cli command plan
-> execute
-> collect
-> pre-annotation validate
```

其中 `execute / collect` 使用真实飞书消息链路。最终评估不是基于 LLM 自己编出来的计划文本，而是基于真实回收的 observed messages。

Benchmark 覆盖四类企业记忆失败场景：

- `anti_interference`：大量无关上下文后仍要找回目标任务事实。
- `contradiction_update`：新旧指令冲突时必须返回最新 current state。
- `evidence_dependency_reasoning`：结论依赖多条证据链，不能只记住下游结果。
- `private_info_in_official_file`：个人私有信息混入正式文件或正式同步中，系统不能把个人偏好当作任务结论。

### 评估口径

Phase 3 对比的是同一份 observed transcript 下的两个系统：

- `task_wiki_3_layer`：Task Wiki 三层链路。
- `openclaw_original`：OpenClaw 原生 baseline。

评估时，OpenClaw 不会被额外注入 query-relevant transcript candidates，也不会看到 gold 或 Task Wiki 的 event/wiki artifact。它只能依赖 replay 后自己的原生记忆回答。

评分不只看答案是否正确，还拆成四个维度：

- `answer_score`：答案是否覆盖预期任务事实。
- `evidence_score`：是否输出证据，证据是否能对齐真实 observed message。
- `safety_score`：是否误用干扰、旧状态或个人私有信息。
- `efficiency_score`：估计定位步骤和耗时。

这个口径的核心是：企业 Memory 不能只要求“答得像”，还要能解释“证据来自哪里”。

### 评估结果

当前真实评估结果显示，Task Wiki 三层结构相比 OpenClaw 原生 baseline 有明显提升：

| 指标               | Task Wiki 三层 | OpenClaw 原生 |           提升 |
| ------------------ | -------------: | ------------: | -------------: |
| Query success rate |       `70.84%` |       `8.33%` |     `+62.51pp` |
| Evidence precision |       `68.62%` |          `0%` |     `+68.62pp` |
| Safety score       |       `91.67%` |      `87.50%` |      `+4.17pp` |
| Avg time           |          `20s` |         `45s` | `-25s / query` |

报告里建议把重点放在两点：

- Task Wiki 显著提高了当前任务事实的回答准确率。
- Task Wiki 能输出可回指真实消息的证据链，而 OpenClaw 原生 baseline 当前没有稳定的 observed message citation。

### Evidence 为 0 的说明

项目报告里不要简单写“OpenClaw 没有证据”。更准确的写法是：

> OpenClaw 原生 baseline 当前可以输出自然语言回答，但没有稳定输出可回指真实 observed message_id 的结构化 citation。因此在 evidence precision 指标上无法和 gold supporting messages 对齐，记为 0。该指标衡量的是结构化可追溯证据能力，不等同于断言 OpenClaw 内部完全没有检索依据。

这样写更严谨，也避免把 baseline 说得过头。

### 项目贡献总结

项目报告可以把贡献总结为三点：

- 提出任务级可信记忆结构：用 task binding、verified event 和 wiki projection 替代不可验证的个人摘要记忆。
- 实现真实飞书协作 benchmark：通过 lark-cli 执行和 collect 回收 observed data，构造干扰、矛盾更新、证据依赖和私有信息边界场景。
- 建立 answer + evidence + safety 的评估闭环：不仅比较答案是否正确，还比较证据能否回指真实消息、是否误用旧状态或私有信息。

### 可直接放入报告的段落

> 本项目面向企业长程协作场景，设计了 Task Wiki 三层可信记忆机制。系统首先将飞书消息绑定到具体任务，再把消息抽取为带原文 quote 的 atomic event，并通过 schema、位置、证据支撑和原子性校验后写入 verified event ledger；最后将 verified events 投影为任务 Wiki，维护当前结论、历史变更、行动项、约束和证据引用。相比原生个人 Memory，Task Wiki 不依赖不可验证摘要，而是围绕任务维护可追溯、可更新的结构化状态。

> 为验证效果，项目构建了真实飞书协作 benchmark，覆盖任务干扰、矛盾更新、证据依赖和私有信息边界等企业常见失败场景。评估结果显示，Task Wiki 三层机制将查询命中率从 `8.33%` 提升到 `70.84%`，结构化证据精度达到 `68.62%`，平均定位耗时从 `45s` 降到 `20s`。结果表明，任务级 verified evidence + wiki projection 能显著提升企业 Memory 的可追溯性、当前态维护能力和抗污染能力。

## 仍需注意的边界

- OpenClaw 的 evidence 为 `0` 是当前 baseline 输出结构导致的评分结果，不应被表述为“OpenClaw 完全没有内部依据”。
- 当前最强结论是 Task Wiki 在结构化 evidence、状态边界和可追溯性上明显更强。
- 如果未来要比较“纯答案质量”，需要让两边都使用同一类 final-answer judge，并且明确是否允许 evidence-free answer 得高分。
- 如果未来 OpenClaw 原生增加 citation trace，Phase 3 应复用同一套 evidence scorer 重新评估，而不是固定沿用当前 `0` 分。
