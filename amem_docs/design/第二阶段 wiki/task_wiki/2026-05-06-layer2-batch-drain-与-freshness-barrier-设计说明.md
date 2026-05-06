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

## 3. 批量抽取的三个核心概念

### 3.1 `pending_ingests`

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

### 3.2 `evidence_spans`

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

### 3.3 `core / context / support`

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

## 4. Hard Trigger / Soft Trigger 语义

Layer 2 当前已经把 drain 触发语义收成两层。

### 4.1 Hard trigger

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

### 4.2 Soft trigger

下面这些场景属于 freshness / cost tradeoff 语义，建议提前 drain，但不是 correctness 兜底：

- `threshold_dirty_count`
- `threshold_span_size`
- `strong_signal`
- `idle`

这里的原则是：

- Soft trigger 负责尽早刷新结果
- Hard trigger 负责最终一致性

---

## 5. Freshness Barrier 设计

### 5.1 `ensureTaskWikiFresh(...)`

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

### 5.2 `recallTaskWiki(...)`

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

### 5.3 `prepareSessionForCompaction(...)`

`prepareSessionForCompaction(...)` 不是当前已经存在的 compaction 流程，而是 compaction 前置 barrier seam。

它的语义是：

- 某个 source session 在做压缩、裁剪、归档、session markdown 重写前
- 必须先 freshness catch-up

当前实现是“接口和语义先到位”：

- barrier seam 已有
- 具体 compaction 流程可以后续再接

### 5.4 `scheduleIdleDrain(...)`

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

## 6. 与 `memory-core` 的边界

这层边界必须明确。

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

## 7. 当前状态判断

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

## 8. 实现验证依据

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

## 9. 一句话总结

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
