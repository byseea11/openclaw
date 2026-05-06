# 2026-05-06 Layer 2 批量抽取与 Freshness Barrier 设计说明

本文只解释 Layer 2 的批量抽取与 freshness barrier 机制。  
本文描述的是当前已经落到 `extensions/feishu-task-wiki/openclaw-lark` 的正式运行语义。  
`memory-core` 不承接 Task Wiki 的 drain 逻辑；Task Wiki 自己负责在读 state/event/wiki 前补齐 dirty span。

当前主要代码面：

- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-wiki/recall.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-wiki/projector.js`

---

## 1. 为什么从逐条抽取改成批量抽取

旧理解更接近：

```text
message ingress
-> immediate LLM extraction
-> verification
```

当前正式实现改成：

```text
message ingress
-> write-only ingest
-> pending/evidence
-> batch drain
-> candidate_events
-> verification
-> session_events
-> projector
```

这样改的原因不是“想把流程变复杂”，而是为了让 Layer 2 更接近真实协作记忆场景。

- 多条消息拼起来才成立的状态变化，不适合逐条 message 独立抽取。
- `stale state / supersession / dependency propagation / objection / revision` 都更像 span 级语义，不像单句独立语义。
- 抽取成本要从 `O(turns)` 转到 `O(batches)`，避免每来一条消息都调一次 LLM。
- 这条主线更贴近第一阶段 `graph_index` 的 transcript-driven batch extraction 设计。

可以把这次改造理解成：

```text
旧：
message -> extract -> verify

新：
message -> ingest ledger -> dirty span -> batch extract -> verify -> project
```

---

## 2. 正式主流程

Layer 2 当前正式主线是：

```text
message ingress
-> maybeIngestTaskSourceSession(...)          [write-only ingest + signal detection]
-> pending_ingests.jsonl / evidence_spans.jsonl
-> drainPendingGraphUpdates(...)              [batch extractor]
-> candidate_events.jsonl
-> runVerificationJobs(...)                   [verifier]
-> session_events.jsonl
-> updateTaskWikiFromVerifiedEvents(...)      [projector]
-> session_wiki / task_index / task_wiki
```

每一步的职责如下：

- `maybeIngestTaskSourceSession(...)`
  只负责把消息写入 source session、打 signal、落 `pending_ingests / evidence_spans`，不直接跑 extractor。
- `pending_ingests.jsonl`
  记录哪些 ingest 仍然是 dirty，还没进入稳定 extraction / verification 结果。
- `evidence_spans.jsonl`
  记录 batch extraction 使用的 evidence envelope。
- `drainPendingGraphUpdates(...)`
  把多个 dirty ingest 合并成一个或多个 drain batch，再一次性抽取 candidate events。
- `candidate_events.jsonl`
  候选层，表示“模型抽到了什么”。
- `runVerificationJobs(...)`
  决定 candidate 哪些变成 `verified / rejected / needs_review`。
- `session_events.jsonl`
  verified ledger，才是 Layer 3 的正式事实输入。
- `updateTaskWikiFromVerifiedEvents(...)`
  只消费 verified events，更新 `session_wiki / task_index / task_wiki`。

---

## 3. Batch Extractor 设计

当前 extractor 的正式入口已经不是 `maybeIngestTaskSourceSession(...)`，而是：

- `drainPendingGraphUpdates(...)`
- 内部实际执行抽取的是 `extractCandidateEventsWithLLM(...)`

它的输入单元也不再是“单条消息”，而是一个 `drain batch / dirty span`。  
一次 batch extract 可以产出多个 `candidate_events`，因为它面对的是一个 span 里的多条潜在变化，而不是单句事件碎片。

### 3.1 旧 extractor vs 新 extractor

| 维度 | 旧理解 | 当前正式实现 |
| --- | --- | --- |
| 触发时机 | message ingress 后立即抽取 | `drainPendingGraphUpdates(...)` 时批量抽取 |
| 抽取单位 | 单条 message / 单次 ingest | dirty span / drain batch |
| 输入结构 | 单条消息 + 少量前文 | `core(trigger) + context + support + task/session metadata` |
| 证据范围 | 局部消息上下文 | 多个 ingest 合并后的 span 证据包 |
| 一次调用产出 | 单个或极少量候选 | 多个 `candidate_events` |
| 更擅长的问题 | 单句显式结论 | stale state、修正、反对、依赖传播、多 source 交叉确认 |
| 成本模型 | `O(turns)` | `O(batches)` |

结论很明确：

- 旧：更接近 `message -> extract`
- 新：`dirty span -> batch extract`
- 新 extractor 抽的是“span 上成立的候选事实”，不是“单条消息的局部事件碎片”

### 3.2 为什么 Layer 2 必须改成 Batch Extractor

这次改造不是为了“攒消息省调用”，而是为了把事实抽取单元从 message 改成 change-bearing span。

- `stale state` 需要看前后状态有没有被更新或覆盖。
- `supersession` 需要看旧口径和新口径是不是在同一个 span 内被替换。
- `dependency propagation` 需要看一个 blocker 或风险如何影响别的 target。
- `objection / revision` 需要看一条消息是不是在反驳或修正前文。
- 多 source 交叉确认需要把 thread root、reply、comment、chat 前文放到同一个证据视图里。

所以 batch extractor 的本质不是“减少调用次数”，而是：

- 不再从“单条消息有没有 event”出发
- 而是从“这一批 dirty span 里成立了哪些候选事实”出发

### 3.3 当前 batch 是怎么划分的

当前实现里的 batch 切分规则还比较朴素，不是按语义主题智能切分，而是按同一个 `source_session` 内的 dirty ingest 顺序和大小阈值做受控装箱。

先看进入 batch 的对象。当前不是所有消息都会进入 batch，只有满足下面条件的 ingest 才会进入 `drainPendingGraphUpdates(...)`：

- `status` 是 `pending_extraction` 或 `queued_for_drain`
- `needs_llm_extraction=true`

这意味着 Layer 2 先经过一层轻量 signal detection，再决定哪些增量消息值得进入 LLM 抽取阶段。

当前 batch 还有一个更外层边界：

- batch 不跨 `source_session`
- `drainPendingGraphUpdates(...)` 是按单个 `sessionDir` 运行的

因此一次 batch 抽取一定只发生在同一个 source session 内，不会把不同 session 的 dirty ingest 混在一起。

在单个 session 内，当前切分规则只有两个硬阈值：

- `DEFAULT_DRAIN_INGEST_LIMIT = 4`
- `DEFAULT_DRAIN_CHAR_LIMIT = 1600`

实际切分方式是：

- 先按 `ingest_version` 升序排列 pending ingest
- 按顺序连续装箱
- 如果当前 batch 已经有 4 个 ingest，或者再放入下一条 ingest 后累计字符数会超过 1600，就切到下一个 batch

所以当前更接近：

```text
pending ingests
-> sort by ingest_version
-> pack in order
-> split when count > 4 or chars > 1600
```

这套规则的含义是：

- 当前是 bounded batch
- 重点先保证一次抽取的输入窗口不会无限长
- 还没有进入按 topic、state phase、dependency chain 做语义切分的阶段

需要明确的是，当前实现还没有这些更高级的切分规则：

- 不按 topic 漂移切 batch
- 不按状态修正点切 batch
- 不按 dependency cluster 单独切 batch
- 不按 objection / supersession 的语义阶段切 batch

因此当前正式口径应该写成：

- 现在是“按 source session 内顺序 + 数量/字符阈值”切 batch
- 不是“按语义结构智能切 batch”

### 3.4 batch 切分之后，`context` 怎么进入 span

batch 切分只是先决定“一次抽取看哪些 ingest”，真正送给 extractor 的 span 证据还要再做一层合并。

当前流程分成两步：

- 单个 ingest 阶段先由 `buildCoreAndContext(...)` 生成自己的 `trigger / support / context`
- batch drain 阶段再由 `buildBatchEnvelope(...)` 把多个 ingest 的 `core / support / context` 合并、去重和裁剪

因此当前 batch 语义不是：

- 直接把原始消息整段塞给 extractor

而是：

- 先把 ingest 装箱成 bounded batch
- 再把这些 ingest 各自的 evidence span 合成一个 batch-level evidence envelope

这一点也解释了为什么 batch extractor 可以：

- 输入是一个 span
- 输出仍然是一条一条的 atomic candidate event

也就是：

- batch 化的是输入证据窗口
- 不是输出 event 的粒度

---

## 4. Validate / Verify 分层变化

batch 化之后，Layer 2 不再是“抽取一步到位”，而是明确变成三段式链路：

```text
候选生成
-> 程序化准入
-> 语义验证
```

当前代码面的对应关系是：

- `extractCandidateEventsWithLLM(...)`
  负责提出候选，不负责最终确认。
- `validateCandidateEvent(...)`
  负责 programmatic validation。
- `runVerificationJobs(...)`
  负责把 candidate 推进到 verification。
- `verifyCandidateEvent(...)`
  负责语义验证并决定是否进入 verified ledger。

### 4.1 `validateCandidateEvent(...)`

它的职责是程序化准入，而不是最终事件成立判定。

- schema / typed fields 检查
- evidence location / quote 对齐检查
- atomicity 检查
- 基础可验证性检查

它输出的是：

- `programmatic_validation.verdict`
- `ready_for_verification`
- `needs_review`
- `rejected`

因此它真正回答的问题是：

- 这个 candidate 的结构是否像一个合法候选
- 它的主证据挂接是否正确
- 它是否值得进入下一步 verification

### 4.2 `verifyCandidateEvent(...)`

它负责基于 resolved batch evidence 做语义确认。

- 判断 candidate 是否真的被证据支撑
- 判断它是成立、存疑，还是应被拒绝
- 产出更接近最终 ledger 的结论

它输出的语义是：

- `verified`
- `needs_review`
- `rejected`

一句话区分：

- `validate` 是准入闸门
- `verify` 才是进入 `session_events` 前的确认层

### 4.3 `candidate_events` 和 `session_events` 为什么必须分层

这也是 batch 模式后最容易被忽略的变化。

```text
dirty ingest(s)
-> evidence span assembly
-> drain batch
-> extractCandidateEventsWithLLM(...)
-> validateCandidateEvent(...)
-> candidate_events.jsonl
-> runVerificationJobs(...)
-> verifyCandidateEvent(...)
-> session_events.jsonl
-> projector
```

- `candidate_events.jsonl`
  表示“抽到了什么，以及通过了哪一级程序化检查”。
- `session_events.jsonl`
  表示“哪些候选经过 verification 后成为 verified ledger”。

如果没有这层分离，batch extractor 产出的多候选结果会直接和 verified ledger 混在一起，Layer 2 就无法清楚表达：

- 候选有没有被抽到
- 候选有没有通过程序化准入
- 候选最后有没有被语义确认

---

## 5. `evidence_spans / context / support / core` 关系说明

这层关系如果不单独讲清楚，最容易把 `evidence_spans` 误解成“上下文文件”。

### 5.1 `evidence_spans`

`evidence_spans.jsonl` 是 Layer 2 的正式证据封装层 / evidence envelope。

它不是单独一种“上下文”，而是用来持久化记录某个 ingest 或 drain batch 对应的证据包。

它当前至少包含：

- `span_kind`
- `ingest_id / drain_batch_id`
- `trigger_entries`
- `support_entries`
- `core_entries`
- `context_entries`

所以更准确地说：

- `evidence_spans` 是外层容器
- `context_entries` 只是这个容器里的一个字段

### 5.2 `context_entries`

`context_entries` 是解释性上下文，不直接承载主事实。

它主要用来：

- 消解代词和指代关系
- 解释修正、反驳和状态切换
- 确定时间口径和当前状态归属
- 帮 extractor / verifier 理解“这句话是在接哪句话”

### 5.3 `support_entries`

`support_entries` 是更稳定的辅助证据。

典型例子包括：

- thread root
- comment root
- 其他更像上位背景、但不是本次主变化承载者的证据

它的作用更偏向：

- 给 extractor 一个稳定背景
- 给 verifier 提供额外证据

### 5.4 `trigger_entries / core_entries`

`trigger_entries / core_entries` 是当前 dirty span 中最像“新事实承载者”的主证据集合。

- `trigger_entries`
  更贴近本次 ingest 直接触发的消息
- `core_entries`
  是 extractor 真正最关注的主证据输入核心

到了 batch drain 之后，它们会成为 `extractCandidateEventsWithLLM(...)` 的主要输入核心。

---

## 6. `context` 是怎么确定的

`context` 不是 LLM 现想的，当前先由 `buildCoreAndContext(...)` 程序化确定，然后 batch drain 再把多个 ingest 的 context 合并、去重和裁剪。

### 6.1 单个 ingest 阶段

当前规则按 source type 分三类。

- `thread`
  - 当前消息进 `trigger`
  - thread root 进 `support`
  - 之前消息进 `context`
- `comment`
  - 当前消息进 `trigger`
  - comment root 进 `support`
  - 之前消息进 `context`
  - `replyChainContext` 额外进入 `context`
- `chat`
  - 当前消息进 `trigger`
  - 最近少量 prior entries 进 `context`

所以在 ingest 阶段，`context` 的本质是：

- 当前消息附近、但不是主事实本身的解释性前文

### 6.2 batch drain 阶段

到了 `buildBatchEnvelope(...)`：

- 多个 ingest span 的 `core / support / context` 会被合并
- 然后统一去重
- 如果某条 entry 已经属于 `core` 或 `support`，就不会再保留在 `context`

因此 batch 后的 `context` 已经不是“某一条消息前面的几句”，而是：

- 这一批 dirty span 的解释性上下文窗口

也正因为这样，batch extractor 才能处理：

- 修正前文
- 覆盖旧状态
- 多条消息共同成立的结论

---

## 7. 批量抽取的三个核心概念

### 7.1 `pending_ingests`

`pending_ingests.jsonl` 不再是临时文件，而是正式 dirty ledger。

它表达的是：

- 哪些增量消息已经进入 source session
- 哪些 ingest 还没被 drain 进稳定 extraction 结果
- 哪些 ingest 已经进入 verification 或已经完成结论

当前关键状态包括：

- `pending_extraction`
- `queued_for_drain`
- `pending_verification`
- `processed_no_event`
- `verified`
- `needs_review`
- `rejected`

其中：

- `pending_extraction`
  表示这次 ingest 仍然是 dirty，需要后续 batch drain。
- `queued_for_drain`
  表示它已经被纳入某个待处理 drain batch。
- `pending_verification`
  表示 candidate 已经产出，但 verifier 还没给最终判定。
- `processed_no_event`
  表示 signal detection 已做完，当前 span 不需要 LLM extraction，或者 drain 后确认无 event。

### 7.2 `evidence_spans`

`evidence_spans.jsonl` 也不是调试副产物，而是正式 evidence envelope。

当前主要承接两类 span：

- ingest span
  表示某次单独 ingest 进入系统时的局部证据视图。
- drain batch span
  表示多个 dirty ingest 合并后真正送给 batch extractor 的 span 视图。

这层的作用是把“消息流”变成“可抽取证据块”，并稳定承接：

- `trigger_entries`
- `core_entries`
- `context_entries`
- `support_entries`

### 7.3 `core / context / support`

这里的语义已经从“单条消息视角”改成“dirty span 视角”。

- `core`
  本次 dirty span 里真正承载新事实的主证据集合。
- `context`
  用来解释代词、时间、修正、否定和当前状态归属的上下文窗口。
- `support`
  用来辅助 verification、dependency linkage 和 current-state disambiguation 的辅助证据。

也就是说，现在真正送给 extractor 的不是“单条消息 + 少量上下文”，而是：

```text
dirty span
= core entries
+ context window
+ support evidence
```

---

## 8. Hard Trigger / Soft Trigger 语义

Layer 2 当前已经把 drain 触发语义收成两层。

### 8.1 Hard trigger

下面这些场景属于 correctness 语义，必须先 drain：

- `verification` 前必须 drain
- `replay_runtime` 前必须 drain
- `projector` 前必须 drain
- `recall` 前必须 drain
- `pre_compaction` 前必须 drain
- 显式调用 `ensureTaskWikiFresh(...)` 时，必须消费当前 dirty span，而不是静默跳过

这里的原则是：

- 只要后续逻辑要读 `candidate_events / session_events / task_wiki_state`
- 就不能让它看到 still-dirty session

### 8.2 Soft trigger

下面这些场景属于 freshness / cost tradeoff 语义，建议提前 drain，但不是 correctness 兜底：

- `threshold_dirty_count`
- `threshold_span_size`
- `strong_signal`
- `idle`

这里的原则是：

- Soft trigger 负责尽早刷新结果
- Hard trigger 负责最终一致性

---

## 9. Freshness Barrier 设计

### 9.1 `ensureTaskWikiFresh(...)`

`ensureTaskWikiFresh(...)` 是 Task Wiki 侧统一 freshness API。

当前输入固定为：

- `taskRootDir?`
- `sessionDir?`
- `reason`
- `projectAfterDrain?`

当前输出固定解释为：

- `checked_session_count`
- `drained_session_count`
- `drain_batch_ids`
- `verified_event_count`
- `projected_session_count`

它的正式行为是：

- 扫一个 session，或一个 task 下的所有 sessions
- 找出仍有 dirty ingest 的 session
- 对这些 session 执行：
  - drain
  - verify
  - optional project

这样 `recall / replay / projector / pre_compaction` 都可以统一依赖它，而不是各自散落调用 `drainPendingGraphUpdates(...)`。

### 9.2 `recallTaskWiki(...)`

`recallTaskWiki(...)` 不是 `memory-core` 的搜索器，而是 Task Wiki 自己的 query seam。

它的职责是：

- 在真正读取 `task_wiki_state / task_index_state / session_wiki_state / session_events` 之前
- 先强制执行：

```text
ensureTaskWikiFresh({ reason: "recall", projectAfterDrain: true })
```

这里的硬规则是：

- 任何“基于 Task Wiki state 给答案”的入口，都应该先过它
- 不能直接裸读 state 文件

### 9.3 `prepareSessionForCompaction(...)`

`prepareSessionForCompaction(...)` 不是当前已经存在的 compaction 流程，而是 compaction 前置 barrier seam。

它的语义是：

- 某个 source session 在做压缩、裁剪、归档、session markdown 重写前
- 必须先 freshness catch-up

当前实现是“接口和语义先到位”：

- barrier seam 已有
- 具体 compaction 流程可以后续再接

### 9.4 `scheduleIdleDrain(...)`

`scheduleIdleDrain(...)` 是 plugin-local soft trigger。

它当前的正式语义是：

- 只给 `needs_llm_extraction=true` 的 session 挂 idle drain
- 到期后触发：

```text
ensureTaskWikiFresh({ sessionDir, reason: "idle", projectAfterDrain: true })
```

但它不承担 correctness 兜底：

- `idle` 负责 freshness
- correctness 仍由 `recall / verification / projector / pre_compaction` 等 hard trigger 负责

---

## 10. 与 `memory-core` 的边界

这层边界必须明确。

这里也要顺带重申：

- `memory-core` 不参与 Layer 2 的 batch extractor
- `memory-core` 也不参与 `validateCandidateEvent(...) / verifyCandidateEvent(...)`
- 这些机制都属于 `extensions/feishu-task-wiki/openclaw-lark` 内部的 Layer 2 运行语义

`memory-core` 当前不应该知道：

- `pending_ingests.jsonl`
- `evidence_spans.jsonl`
- `candidate_events.jsonl`
- `session_events.jsonl`

Task Wiki 自己负责 state freshness。

如果未来确实需要让 `memory-core` 在 recall 前确保 Task Wiki 新鲜，也应该只加通用 hook seam，例如：

- `beforeRecall`
- `freshnessBarrier.ensureFresh(...)`

而不应把：

- Task Wiki 的目录结构
- drain 逻辑
- verification / projection 编排

直接塞进 `memory-core`。

一句话说清就是：

- 现在是 Task Wiki 自己做 barrier
- 不是 `memory-core` 来管理 Task Wiki 的 dirty span

---

## 11. 当前状态判断

### 7.1 已实现

当前已经落地的部分包括：

- write-only ingest
- batch drain extractor
- `candidate_events / session_events` 双层
- `ensureTaskWikiFresh(...)`
- `recallTaskWiki(...)`
- `prepareSessionForCompaction(...)`
- `idle` 本地调度接口
- replay/runtime 前的强制 drain

### 7.2 尚未完全接线

当前仍需要继续收口的部分包括：

- 真正在线 recall 主入口还没有大规模业务接线
- `pre_compaction` 目前是 barrier seam，具体 compaction 流程待后续接入
- `idle` 已实现为本地调度，但仍是 soft trigger，不替代 hard trigger correctness

---

## 12. 实现验证依据

当前已经验证到的方向包括：

### 8.1 Layer 2

- `session-ingest` 可写入 `pending_ingests / evidence_spans`
- `drainPendingGraphUpdates(...)` 可产出 `candidate_events`
- `runVerificationJobs(...)` 可产出 `session_events`

### 8.2 Freshness barrier

- `ensureTaskWikiFresh(...)` 可在 `recall / pre_compaction` 路径上强制 drain
- `scheduleIdleDrain(...)` 只针对 `needs_llm_extraction=true` 的 session 生效

### 8.3 Layer 3

- verified events 可继续进入 projector
- 后半段 `session_wiki / task_index / task_wiki` contract 不需要因为这次改造而回退

---

## 13. 一句话总结

这次 Layer 2 的正式转向不是“把抽取步骤改名”，而是把主链从：

```text
per-message immediate extraction
```

改成：

```text
write-only ingest
-> dirty ledger
-> batch drain
-> verification
-> freshness barrier protected reads
```

而 `memory-core` 在当前设计里不负责这条链的 freshness；Task Wiki 自己负责在读 state/event/wiki 前补齐 dirty span。
