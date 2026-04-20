# OpenClaw Memory Graph Index V0 技术交付报告

生成日期：2026-04-17

## 1. 摘要

Memory Graph Index V0 已在当前仓库中完成 M0-M6 范围内的骨架接线与首版可用实现：从 flush 输出中的 graph JSON、规则抽取、canonicalize、sidecar SQLite 写入、event 到 state reduce、`search_graph()` 检索、`memory_search` graph 分支合并、`memory_get` 回读验证，到 graph hit 使用计量，已经形成一条可观测链路。

当前实现保持 `graphIndex.enabled=false` 的默认关闭策略。关闭时，现有 chunk memory 路径不应改变；开启时，graph hit 只作为 `memory_search` 返回结果末尾追加的结构化 hint，不替换 chunk branch，也不改变 `memory_search` / `memory_get` 的工具入参 schema。

本报告只描述当前仓库已经实现和验证过的内容。V1 M0-fix 已在 V0 基线之上补齐一组交付前 guardrail：canonical runtime 入口 fallback、flush persist 前 `source_ref` 强校验、`hitsUsedRaw` / `hitsUsedUniqueRefs` 语义收敛、真实 hook runner dispatcher smoke、CLI runtime smoke 测试。当前轮次又完成了 V1 M1 的首段实现：schema 已升级到 `v1`、新增 `status_before` / richer entity state 字段、sidecar 支持 v0->v1 migration、flush prompt 升级为多事件抽取版本，并补入 3 份 flush 场景 fixture 与对应自动化验证。M7 独立 LLM bootstrap 抽取、GraphRAG、关系图扩展、query-aware retrieval、全局 metrics 管线等能力仍未完成，详见“V0.1/M7 待做”和“已知限制与风险”。

## 2. 背景与问题定义

OpenClaw 现有 memory 能力以 Markdown memory 文件和 chunk index 为主，适合按文本片段召回原文。但在状态、任务、owner、decision 等结构化信息上，纯 chunk 检索存在两个问题：

- 对“某个任务当前状态是什么”这类查询，chunk hit 可能召回多个历史片段，模型需要自己判断最新状态。
- 对“哪些事件改变了状态”这类查询，系统缺少稳定的 event/state 层，难以计量、去重和追踪引用。

Graph Index V0 的定位不是替代 memory 文件或 compaction summary，而是在不破坏现有 memory/flush/chunk 主链路的前提下，为 `memory_search` 增加一条 graph branch：

```text
memory source
  -> extractor
  -> canonicalize
  -> CanonicalStore sidecar
  -> reducer
  -> search_graph
  -> memory_search append graph hit
  -> memory_get verify source lines
```

设计目标是“先可用、可观测、可回指”，而不是一次性实现高质量 GraphRAG。

## 3. 记忆定义

### 3.1 Source Of Truth

Memory 的 source of truth 仍然是 Markdown 文件：

- `MEMORY.md`
- `memory/YYYY-MM-DD.md`

Graph sidecar 中的数据是从这些文件或 flush piggyback JSON 派生出来的索引，不是新的事实源。任何 graph hit 都必须能通过 `source_ref` 回指到原始 memory 文件行段，并在需要精确措辞时由 `memory_get` 回读。

### 3.2 Graph Sidecar 定位

Graph sidecar 是与现有 chunk index 分离的 SQLite 文件。当前 schema 与 store 实现在 `extensions/memory-core/src/canonical/schema.ts` 和 `extensions/memory-core/src/canonical/store.ts`。

逻辑路径为：

```text
OPENCLAW_STATE_DIR/memory/{agentId}.graph.sqlite
```

在默认用户环境下等价于 state dir 下的 `memory/{agentId}.graph.sqlite`。它只承载 graph event/state、FTS、metrics、recent graph hit 候选，不改变现有 chunk index 数据结构。

### 3.3 Event 定义

当前 `RawEvent` / `EventRecord` 契约在 `extensions/memory-core/src/canonical/schema.ts` 中定义。M1 后核心字段包括：

- `action`：事件动作，必填。
- `source_ref`：原文回指，必填，形如 `memory/2026-04-15.md#L12-L18`。
- `actor` / `object` / `status_before` / `status_after` / `occurred_at` / `confidence`：可选结构化字段。
- `event_id`：由 `source_ref + actor + action + object + status_after + occurred_at` 的稳定顺序生成。
- `entity_id`：优先由 `object` 生成，其次使用 `actor:action` 或 `action:source_ref`，避免大量事件落到同一个空实体。
- `session_id` / `covered_until_entry_id`：schema v1 预留字段，当前实现保留为 `null`，尚未接入行为。

### 3.4 State 定义

`EntityState` 是从 event 派生出的当前实体状态。M1 后字段包括：

- `entity_id`
- `latest_status`
- `latest_owner`
- `last_event_id`
- `last_updated_at`
- `entity_type`
- `supporting_event_ids`
- `confidence`

当前 reducer 仍只做最小规则：按 `occurred_at` / `created_at` 选择每个 entity 最新事件并生成 state，但会额外写入：

- `entity_type`：保守默认 `other`；对明显像 `task_123` / `task-123` / 含 `task|issue|ticket` 的 object 标记为 `task`
- `supporting_event_ids`：当前先写 `[last_event_id]`
- `confidence`：当前直接沿用最新事件的 `confidence`

更复杂的状态归并、alias resolution、关系归并属于后续里程碑。

## 4. V0 目标与范围

### 4.1 V0 已完成：M0-M6

M0-M6 当前完成范围如下：

| 范围                                      | 状态       | 当前实现                                                                              |
| ----------------------------------------- | ---------- | ------------------------------------------------------------------------------------- |
| M0 规则抽取与 dry-run                     | 已完成     | `extensions/memory-core/src/canonical/extractor.ts`、`scripts/memory-graph-dryrun.ts` |
| M1 canonical contract                     | 已完成     | `extensions/memory-core/src/canonical/canonicalizer.ts`、`schema.ts`                  |
| M2 sidecar store 与 bootstrap             | 已完成     | `store.ts`、`bootstrap.ts`、graph CLI runtime                                         |
| M3 flush piggyback 可靠写入               | 已完成     | `flush-plan.ts`、`canonical/index.ts`、`agent-runner-memory.ts`                       |
| M4 graph retrieval + memory_search append | 已完成     | `retriever.ts`、`prompt.ts`、`tools.ts`                                               |
| M5 hits_returned / hits_used metrics      | 已完成首版 | `usage.ts`、`store.ts`、`extensions/memory-core/index.ts`                             |
| M6 自动化 proof 与 live E2E               | 已完成首版 | `canonical/integration.test.ts` + 本报告生成时的 live E2E                             |

### 4.2 V0 不做

当前实现明确不做：

- 不新增 `graph_MEMORY.md` 或新的 graph markdown 文件体系。
- 不替换 compaction summary。
- 不改变 `memory_search` / `memory_get` 入参 schema，只扩展返回字段。
- 不实现 entity-entity relation 表。
- 不实现复杂 graph expansion / graph rerank。
- 不抽取 session transcript。
- 不做 afterTurn 实时增量抽取。
- 不做独立 LLM bootstrap 抽取质量优化。

### 4.3 V1 M0-fix 已完成的基线加固

M0-fix 不进入 M1 schema v1 / alias / embedding，只关闭 V0 报告中的基线 gap：

| 范围                              | 状态             | 当前实现                                                                             |
| --------------------------------- | ---------------- | ------------------------------------------------------------------------------------ |
| canonical fallback guardrails     | 已完成           | `extensions/memory-core/src/canonical/index.ts`                                      |
| flush persist `source_ref` 强校验 | 已完成           | `canonical/index.ts`、`canonical/schema.ts`                                          |
| `hitsUsed` 语义收敛               | 已完成           | `canonical/usage.ts`、`canonical/store.ts`、`canonical/schema.ts`                    |
| 真实 hook runner dispatcher smoke | 已完成自动化测试 | `canonical/integration.test.ts`                                                      |
| CLI graph runtime smoke 测试      | 已完成自动化测试 | `extensions/memory-core/src/cli.test.ts`                                             |
| package CLI 人工 smoke            | 待补充           | `corepack pnpm openclaw ...` 在 dirty tree 自动 rebuild 路径中卡住，未作为通过项记录 |

### 4.4 V1 M1 已实现并验证的内容

当前轮次已实现并跑通以下 M1 范围：

| 范围                           | 状态           | 当前实现                                                                          |
| ------------------------------ | -------------- | --------------------------------------------------------------------------------- |
| Schema V1 migration            | 已完成并已验证 | `canonical/schema.ts`、`canonical/store.ts`、`canonical/migrations/v0-to-v1.ts` |
| `status_before` flush/parser   | 已完成并已验证 | `canonical/extractor.ts`、`canonical/canonicalizer.ts`、`canonical/integration.test.ts` |
| 多事件 flush prompt 优化       | 已完成并已验证 | `flush-plan.ts`、`flush-plan.test.ts`                                            |
| `entity_aliases` schema 落表   | 已完成，仅建表 | `canonical/schema.ts`、`canonical/migrations/v0-to-v1.ts`                        |
| M1 flush fixture / parser 验证 | 已完成并已验证 | `canonical/flush-scenarios.test.ts` + 3 份 fixture                               |

注意：M1 当前只把 `entity_aliases` 表纳入 schema v1；alias resolver、flush aliases、CLI alias 和 backfill 仍未实现。

## 5. 架构设计

### 5.1 主链路

```text
flush prompt JSON / memory file
  -> parseGraphJsonBlock() 或 extract()
  -> canonicalize(raw, EXTRACTOR_VERSION)
  -> CanonicalStore.upsertEvents()
  -> reduce(events, prevStates)
  -> CanonicalStore.refreshEntityStates()
  -> search_graph(store, query, k)
  -> graphHitToMemorySearchResult()
  -> memory_search results append corpus: "graph"
  -> memory_get(path, from, lines) 回读原文
```

关键实现点：

- Flush JSON 解析：`extensions/memory-core/src/canonical/extractor.ts`
- Canonicalize：`extensions/memory-core/src/canonical/canonicalizer.ts`
- Store：`extensions/memory-core/src/canonical/store.ts`
- Reducer：`extensions/memory-core/src/canonical/reducer.ts`
- Retriever：`extensions/memory-core/src/canonical/retriever.ts`
- Tool merge：`extensions/memory-core/src/tools.ts`

### 5.2 Flush Piggyback

`extensions/memory-core/src/flush-plan.ts` 在 graph enabled 且 `extractDuringFlush=true` 时，在 memory flush prompt 中追加 JSON block 约束。M1 后 prompt 已升级为多事件抽取版本，要求模型尽量从本轮 flush 中提取更多结构化事件，并在可知时同时输出 `status_before` 与 `status_after`：

```text
Try to extract as many valid events as possible; a typical flush can produce 3-10 events
Only include events from content newly appended to memory/YYYY-MM-DD.md during this flush
Each event must use source_ref like "memory/YYYY-MM-DD.md#L12-L18"
If both status_before and status_after are knowable, include both
If there are no extractable events, output {"events":[]}
```

Flush run 完成后，`src/auto-reply/reply/agent-runner-memory.ts` 会调用通用 memory capability 的 `flushResultHandler`，并用 `collectMemoryFlushOutputText(result)` 聚合 flush 输出文本。handler 异常只通过 `logVerbose` 记录，不阻断原 flush 成功路径。

### 5.3 Store 与状态归并

`CanonicalStore` 懒打开 sidecar SQLite，并维护以下核心表：

- `meta`
- `event_records`
- `entity_states`
- `entity_aliases`
- `event_fts`
- `graph_metrics`
- `recent_graph_hits`

M1 后，store 在打开 sidecar 时会检查 `meta.schema_version`：新库直接建 `v1` schema，旧 `v0` sidecar 则通过 `extensions/memory-core/src/canonical/migrations/v0-to-v1.ts` 做 additive migration，并回填 event FTS。`upsertEvents()` 写入 event 和 FTS；`refreshEntityStates()` 调用 reducer 刷新 entity state；`recordRecentGraphHits()` / `markRecentGraphHitsUsed*()` 记录 graph hit 返回与使用。

### 5.4 Retrieval 与 Tool Merge

`search_graph()` 在 V0 中使用 FTS 查询取 `k*4` 候选，再在 TypeScript 层做轻量 recentness boost，并限制每个 entity 最多返回 1 个 state + 1 个 event，最终裁剪到 `k`。

`memory_search` 的行为：

- 先走原 chunk search。
- 保持 chunk hit 原有排序和截断逻辑。
- graph enabled 时调用 `searchGraphForMemoryTool()`。
- graph hit append 在结果尾部。
- 返回 `debug.graph = { enabled, hits, renderedHits }`。

Graph hit 渲染由 `extensions/memory-core/src/canonical/prompt.ts` 统一处理：

- state snippet 以 `[Graph state]` 开头。
- event snippet 以 `[Graph event]` 开头。
- 必带 `source: memory/...#Lx-Ly`。

## 6. 核心模块与代码落点

### 6.1 Canonical Graph 模块

- `extensions/memory-core/src/canonical/schema.ts`
  - 定义 `RawEvent`、`EventRecord`、`EntityState`、`GraphHit`、`GraphIndexConfig`、metrics、recent hit 类型。
  - 定义 `EXTRACTOR_VERSION = "v0-2026.04"`、`CANONICAL_SCHEMA_VERSION = "v1"`。
  - 定义 SQLite schema 与 `resolveGraphIndexConfig()`、`describeGraphIndexConfig()`、`parseSourceRef()`。
  - M1 新增 `status_before`、`session_id`、`covered_until_entry_id`、`entity_type`、`supporting_event_ids`、`confidence`、`EntityAlias`。

- `extensions/memory-core/src/canonical/migrations/v0-to-v1.ts`
  - 实现 sidecar 的 v0->v1 additive migration。
  - 新增 event/state 列、`entity_aliases` 表，并回填 event FTS。
  - 日志：`[canonical] migration.start`、`[canonical] migration.done`、`[canonical] migration.fallback`。

- `extensions/memory-core/src/canonical/extractor.ts`
  - `parseGraphJsonBlock()` / `parseGraphJsonBlockWithStatus()` 解析 flush piggyback JSON。
  - `extract()` 实现规则抽取，覆盖 checklist、`status:`、`owner:`、`decided to ...`、`task_123 is blocked/done/in progress`、日期头/行内日期。
  - M1 parser 已接受 `status_before/status_after` 的 JSON roundtrip。
  - 日志：`canonical.extract.parse_ok`、`canonical.extract.parse_failed`、`canonical.extract.rules`。

- `extensions/memory-core/src/canonical/canonicalizer.ts`
  - 稳定生成 `event_id` / `entity_id`。
  - 规范 `occurred_at` 为 ISO8601。
  - `confidence` 越界回退，默认 `0.5`。
  - M1 起 canonicalize 会持久化 `status_before`，但不会把 `status_before/session_id/covered_until_entry_id` 纳入 event id 计算，保持 V0 event id 稳定性。
  - 日志：`canonical.canonicalize input=N output=N`。

- `extensions/memory-core/src/canonical/store.ts`
  - `CanonicalStore`、`getCanonicalStore()`、`closeAllCanonicalStores()`。
  - `reset()`、`setMeta()`、`bumpMetric()`、`recordExtractorLatency()`。
  - `upsertEvents()`、`refreshEntityStates()`、`searchEvents()`、`getStatus()`、`exportData()` / `exportJsonl()`。
  - M1 起 store 支持 `schema_version=v0` sidecar 的 in-place 升级，并在 `reset()` 时同步清空 `entity_aliases`。
  - 日志：`canonical.store.open`、`canonical.store.schema_ready`、`canonical.store.upsert_events`、`canonical.store.refresh_states`、`canonical.store.close_all`。

- `extensions/memory-core/src/canonical/reducer.ts`
  - `reduce(events, prevStates)` 从 event 归并出最新 entity state。
  - M1 起 reducer 还会填充 `entity_type`、`supporting_event_ids`、`confidence`。
  - 日志：`canonical.reduce events=N states=N`。

- `extensions/memory-core/src/canonical/retriever.ts`
  - `search_graph(store, query, k)` 实现 V0 FTS + recency 检索。
  - 日志：`canonical.search query=... k=... hits=N`。

- `extensions/memory-core/src/canonical/prompt.ts`
  - `renderGraphHit()`、`graphHitToMemorySearchResult()`。
  - 负责 `source_ref` 到 `path/startLine/endLine` 的转换。

- `extensions/memory-core/src/canonical/bootstrap.ts`
  - `bootstrapCanonicalIndex()` 枚举 `MEMORY.md` 与 `memory/YYYY-MM-DD.md`。
  - `force` 时先 `reset()`。
  - 使用规则 extractor 做 V0 reindex。

- `extensions/memory-core/src/canonical/usage.ts`
  - `recordReturnedGraphHits()` 记录 `hitsReturned` 和 recent candidate。
  - `markGraphHitsUsedFromMemoryGet()` / `markGraphHitsUsedFromAssistantTexts()` 记录 `hitsUsedRaw` 与 `hitsUsedUniqueRefs`。
  - `hitsUsed` 保留为兼容 alias，语义为 `hitsUsedUniqueRefs`。
  - 写入 memory host events：`memory.graph.recall.recorded`、`memory.graph.recall.used`。

- `extensions/memory-core/src/canonical/index.ts`
  - 对外 runtime 出口。
  - `handleGraphFlushResult()`、`maybeBootstrapCanonicalIndex()`、`searchGraphForMemoryTool()`、`getCanonicalStatus()`、usage helper。
  - M0-fix 后对 flush/search/bootstrap/status/usage 入口统一加 try/catch fallback；graph 异常只 warning，不外溢到 memory / flush / compaction / active-memory。
  - `handleGraphFlushResult()` 在 persist 前校验 `source_ref`：语法、路径范围、文件存在、起止行号和文件总行数；非法 event 只跳过并计入 `sourceRefRejected`。

- `extensions/memory-core/src/canonical/flush-scenarios.test.ts`
  - M1 新增 fixture 驱动测试。
  - 锁住 3 份代表性 flush transcript fixture 仍然能被当前规则 extractor 抽出至少 3 个事件，并产出精确行段 `source_ref`。

### 6.2 Memory-Core 与 Core 接线

- `extensions/memory-core/index.ts`
  - 注册 `flushResultHandler: handleGraphFlushResult`。
  - 注册 `memory_search`、`memory_get`。
  - 注册 `after_tool_call` / `llm_output` hooks，用于 graph hit 使用计量。

- `src/plugins/memory-state.ts`
  - `MemoryPluginCapability` 增加 `flushResultHandler?: MemoryFlushResultHandler`。
  - `resolveMemoryFlushResultHandler()` 从当前 memory capability 读取 handler。

- `src/memory-host-sdk/runtime-core.ts`
  - 导出 `MemoryFlushResultHandler` 类型。

- `src/auto-reply/reply/agent-runner-memory.ts`
  - flush agent 结束后调用 `resolveMemoryFlushResultHandler()`。
  - handler 失败只记录 warning/verbose，不影响 flush metadata 和 compaction 流程。

- `extensions/memory-core/src/tools.ts`
  - 在 `memory_search` chunk branch 后调用 `searchGraphForMemoryTool()`。
  - graph result append 到尾部。

- `extensions/memory-core/src/tools.shared.ts`
  - 扩展工具层结果类型，支持 `corpus: "graph"` 和 `graphMeta`。

- `extensions/memory-core/src/prompt-section.ts`
  - 在 Memory Recall section 末尾说明 `corpus: "graph"` 是结构化 hint，需要用 `memory_get` 验证。

- `extensions/memory-core/openclaw.plugin.json`
  - config schema 接受 `graphIndex.enabled`、`graphIndex.bootstrapOnStart`、`graphIndex.extractDuringFlush`。

### 6.3 Watcher EMFILE 降级处理

为解决或绕开 builtin chunk manager / watcher 初始化时的 `EMFILE: too many open files, watch`，当前仓库增加了 watcher error 降级逻辑：

- `extensions/memory-core/src/memory/manager-sync-ops.ts`
  - `watcher.on("error", ...)` 记录 `memory watch disabled after watcher error: ...`。
  - 如果当前 manager 仍持有该 watcher，则清空 `this.watcher` 并 best-effort close。

- `extensions/memory-core/src/memory/qmd-manager.ts`
  - QMD watcher 同样记录 `qmd watch disabled after watcher error: ...` 并关闭 watcher。

- `extensions/memory-core/src/memory/manager.ts`
  - FTS-only 场景下，`search()` 只有在 `this.vector.enabled` 时才初始化 embedding provider，避免 `store.vector.enabled=false` 时仍走 provider 初始化。

- `extensions/memory-core/src/memory/manager.watcher-config.test.ts`
  - 测试模拟 `EMFILE` error，断言 watcher 被 close，证明 watcher error 会进入 best-effort degraded mode。

## 7. 数据流与生命周期

### 7.1 Flush 写入路径

1. `flush-plan.ts` 给 flush prompt 增加 graph JSON 约束。
2. flush agent 输出 Markdown memory append 和 JSON block。
3. `agent-runner-memory.ts` 聚合 `finalAssistantVisibleText` 与 payload text。
4. `resolveMemoryFlushResultHandler()` 找到 memory-core handler。
5. `handleGraphFlushResult()`：
   - `parseGraphJsonBlockWithStatus()`
   - M1 后可接受含 `status_before` 的 flush event
   - 基于 workspace 做 `source_ref` 强校验：只接受 `MEMORY.md` 或 `memory/YYYY-MM-DD.md`，文件必须存在，`startLine/endLine` 必须落在文件总行数内
   - `canonicalize()`
   - `store.upsertEvents()`
   - `store.refreshEntityStates()`
   - metrics：parse success/failure、latency、`sourceRefValidated`、`sourceRefRejected`、persisted count

非法 `source_ref` 不会写入 sidecar，也不会让 flush 失败。当前新增 warning 使用 `[canonical] source_ref.rejected ...` 前缀；历史 V0 日志仍保留原 `canonical.*` 形式，避免无关 churn。

### 7.2 Bootstrap/Reindex 路径

1. `bootstrapCanonicalIndex()` 枚举 `MEMORY.md` 与 `memory/YYYY-MM-DD.md`。
2. 跳过隐藏目录、`.dreams/`、`dreaming/`。
3. 对每个文件调用规则 `extract()`。
4. 事件 canonicalize 后写入 sidecar。
5. refresh state，写入 extractor version 和指标。

注意：当前 bootstrap/reindex 已可用，但使用规则 extractor；独立 LLM extractor 属于 M7 待做。

### 7.3 Search 路径

1. `memory_search` 正常调用现有 memory manager 做 chunk search。
2. `searchGraphForMemoryTool()` 检查 `graphIndex.enabled`。
3. `search_graph()` 查询 sidecar FTS，并补 state。
4. `graphHitToMemorySearchResult()` 生成 `path/startLine/endLine/snippet/corpus/graphMeta`。
5. graph hit append 到 chunk results 后。
6. 若有 `agentSessionKey`，记录 recent graph candidates 和 `hitsReturned`。

### 7.4 Usage 路径

1. graph hit 被 `memory_search` 返回后写入 `recent_graph_hits`。
2. 后续 `memory_get` 读取对应 path/line 范围，或 assistant output 包含对应 `source_ref` 时，标记 usage。
3. usage 计量分两层：
   - `hitsUsedRaw`：命中的 candidate 原始条数。
   - `hitsUsedUniqueRefs`：按 `source_ref` 去重后的使用数。
   - `hitsUsed`：兼容字段，当前等于 `hitsUsedUniqueRefs`。
4. 通过 `memory.graph.recall.recorded` / `memory.graph.recall.used` 写入 host event log。

`extensions/memory-core/src/canonical/integration.test.ts` 已通过真实 hook runner dispatcher 触发 memory-core 注册的 `after_tool_call` 与 `llm_output` handlers，并验证 `hitsUsedRaw` / `hitsUsedUniqueRefs` 会更新。完整 agent runtime 的人工 live hook smoke 仍待补充。

## 8. 评测与验证设计

### 8.1 单测覆盖

当前 graph 相关单测包括：

- `extensions/memory-core/src/canonical/extractor.test.ts`
  - 解析 fenced JSON。
  - 坏 JSON 不 throw。
  - 规则抽取覆盖 checklist/status/owner/decision/status sentence/source_ref 精度。
  - M1 新增 `status_before/status_after` parser roundtrip。

- `extensions/memory-core/src/canonical/canonicalizer.test.ts`
  - 同一 RawEvent 稳定生成 event/entity id。
  - 缺 actor/object/status 时仍合法。
  - `MEMORY.md` / `memory/*.md` 落到 `memory_file` source type。

- `extensions/memory-core/src/canonical/store.test.ts`
  - schema 创建、meta、upsert 幂等、FTS、state refresh、reset、metrics、close。

- `extensions/memory-core/src/canonical/migration.test.ts`
  - 构造 v0 sidecar 并验证打开后自动升到 v1。
  - 验证 migration 后 event/state 新列默认值稳定，且 FTS 可继续查询旧 event。

- `extensions/memory-core/src/canonical/reducer.test.ts`
  - 同一 entity 多事件取最新 state。
  - 空输入返回空。
  - M1 新增 `entity_type`、`supporting_event_ids`、`confidence` 字段断言。

- `extensions/memory-core/src/canonical/retriever.test.ts`
  - seeded event/state 可被 `search_graph()` 搜到。
  - hit 带 `source_ref`。

- `extensions/memory-core/src/canonical/usage.test.ts`
  - returned hit、memory_get usage、llm_output usage metrics。
  - 同一 `source_ref` 同时返回 state/event 时，验证 `hitsUsedRaw` 可大于 `hitsUsedUniqueRefs`。

- `extensions/memory-core/src/canonical/integration.test.ts`
  - flush -> store -> direct `search_graph()` -> real memory tool wrapper -> `memory_get` -> log proof。
  - flush persist 前拒绝文件缺失与行号越界的 `source_ref`，并验证 rejected event 不入库。
  - 通过真实 hook runner dispatcher 触发 `after_tool_call` 与 `llm_output`，验证 usage 计量。

- `extensions/memory-core/src/cli.test.ts`
  - graph CLI runtime smoke：`status --json`、`reindex --json`、`search --json`、`export --json`。

- `extensions/memory-core/src/tools.test.ts`
  - graph disabled 行为保持。
  - graph enabled 时 graph hit append，带 `corpus: "graph"`、`graphMeta`、`debug.graph`。

- `extensions/memory-core/src/prompt-section.test.ts`
  - Memory Recall 文案包含 `corpus: "graph"` 与 `memory_get` verification 提示。

- `extensions/memory-core/src/flush-plan.test.ts`
  - flush prompt 包含 graph JSON 指令。
  - M1 新增多事件抽取约束：`3-10 events`、`status_before`、`source_ref`、`occurred_at`。

- `extensions/memory-core/src/canonical/flush-scenarios.test.ts`
  - 使用 3 份 flush fixture 验证当前规则 extractor 仍可抽出多事件，并带精确 `#Lx-Ly` `source_ref`。

- `extensions/memory-core/src/config.test.ts`
  - manifest config schema 接受 graphIndex 三个开关。

- `src/plugins/memory-state.test.ts`
  - generic memory capability 注册/解析。

- `src/auto-reply/reply/agent-runner-memory.test.ts`
  - flush 后调用 handler。
  - handler 抛错不阻断 flush 成功路径。

- `extensions/memory-core/src/memory/manager.watcher-config.test.ts`
  - watcher EMFILE/error 进入 best-effort degraded mode。

### 8.2 Integration Proof

`extensions/memory-core/src/canonical/integration.test.ts` 构造了完整链路：

1. 写入临时 `memory/2026-04-15.md`。
2. 构造 flush output JSON，其中 `source_ref = "memory/2026-04-15.md#L12-L18"`。
3. 调用 `handleGraphFlushResult()`。
4. 断言 status：`eventsTotal=1`、`entitiesTotal=1`、`extractorVersion="v0-2026.04"`。
5. 调用 `search_graph()`。
6. 调用真实 memory tool wrapper：`createMemorySearchToolOrThrow()`。
7. 从 graph hit 的 `path/startLine/endLine` 调用 `memory_get`。
8. 断言 log 包含：
   - `canonical.flush.parsed`
   - `canonical.store.upsert_events`
   - `canonical.reduce`
   - `canonical.search`
   - `canonical.memory_search.graph_hits`
   - `canonical.usage.used`

M0-fix 新增两类 proof：

1. `source_ref` 强校验 proof：
   - 同一 flush output 中混入合法 event、缺失文件 event、行号越界 event。
   - 期望只持久化合法 event。
   - 期望 metrics 为 `sourceRefValidated=1`、`sourceRefRejected=2`。
2. hook dispatcher proof：
   - 通过 memory-core plugin 注册真实 `after_tool_call` / `llm_output` hook。
   - 通过 hook runner 触发 `memory_get` 与 assistant output event。
   - 期望 `hitsUsedRaw` 与 `hitsUsedUniqueRefs` 更新，且 hook 内 graph 失败不会阻断 runner。

### 8.3 Live E2E

V0 阶段额外运行过一次 live E2E，使用真实 `createMemorySearchTool()` / `createMemoryGetTool()`、真实 builtin memory manager 和真实 graph sidecar。为了避免本机 watcher fd 限制影响报告生成，该 live E2E 配置了 `sync.watch=false`；EMFILE watcher 降级由专门单测和代码日志点验证。

M0-fix 阶段追加了一个更聚焦的 proof：直接调用 canonical flush/search/usage 出口，混入合法、缺失文件、行号越界三类 `source_ref`，证明强校验和 raw/unique usage metrics 生效。

Live E2E 验证目标：

- `handleGraphFlushResult()` 能解析并持久化 flush JSON。
- 真实 `memory_search` 结果包含原 chunk hit 和 append 的 graph hits。
- graph hit 带 `corpus: "graph"`、`graphMeta`、`path/startLine/endLine`。
- `memory_get` 能按 graph hit 回读原始 Markdown 行段。
- metrics 能看到 `eventsTotal`、`entitiesTotal`、`hitsReturned`、`hitsUsedRaw`、`hitsUsedUniqueRefs`、`sourceRefValidated`、`sourceRefRejected`。

## 9. 自证评测报告

### 9.1 测试与 Gate 结果

本报告更新时，M0/M1 touched-surface 相关 gate 通过情况如下：

```text
corepack pnpm test extensions/memory-core/src/canonical/store.test.ts extensions/memory-core/src/canonical/migration.test.ts

Test Files  2 passed (2)
Tests       4 passed (4)
```

```text
corepack pnpm test extensions/memory-core/src/canonical/canonicalizer.test.ts extensions/memory-core/src/canonical/reducer.test.ts

Test Files  2 passed (2)
Tests       6 passed (6)
```

```text
corepack pnpm test extensions/memory-core/src/canonical/extractor.test.ts extensions/memory-core/src/canonical/flush-scenarios.test.ts extensions/memory-core/src/flush-plan.test.ts

Test Files  3 passed (3)
Tests       6 passed (6)
```

```text
corepack pnpm test extensions/memory-core/src/canonical/integration.test.ts

Test Files  1 passed (1)
Tests       3 passed (3)
```

此前 M0 targeted gates 也已通过：

```text
corepack pnpm test extensions/memory-core/src/canonical extensions/memory-core/src/tools.test.ts extensions/memory-core/src/cli.test.ts

Test Files  9 passed (9)
Tests       68 passed (68)
```

```text
corepack pnpm test src/plugins/memory-state.test.ts src/auto-reply/reply/agent-runner-memory.test.ts

unit-fast:
Test Files  1 passed (1)
Tests       12 passed (12)

auto-reply:
Test Files  1 passed (1)
Tests       5 passed (5)
```

```text
corepack pnpm tsgo

passed
```

```text
corepack pnpm plugin-sdk:api:check

OK docs/.generated/plugin-sdk-api-baseline.sha256
passed
```

```text
corepack pnpm build

passed
```

说明：`corepack pnpm build` 首次在 sandbox 内运行时，runtime-postbuild staging bundled plugin runtime deps 期间因为 `amazon-bedrock` 的 `npm install` 失败而中断；按 sandbox 指引用提升权限重跑后通过。该失败属于本地 sandbox/install 环境问题，不是 graph/canonical 代码错误。

```text
git diff --check

passed
```

本报告更新时也运行了更宽 gate，结果如下：

```text
corepack pnpm test

result: failed
```

全量测试失败项未落在 memory graph 触达面。已观察到的失败包括：

- `src/gateway/server.health.test.ts`：shutdown broadcast timeout。
- `src/gateway/server.sessions-send.test.ts`：gateway send timeout。
- `src/gateway/server.tools-catalog.test.ts`：catalog timeout。
- `test/ui.presenter-next-run.test.ts`：当前 locale 输出中文，但测试期望英文 `n/a` / weekday。
- `src/agents/skills.sherpa-onnx-tts-bin.test.ts`：缺少 `skills/sherpa-onnx-tts/bin/sherpa-onnx-tts` fixture。
- `src/auto-reply/reply/export-html/template.security.test.ts`：缺少 `src/auto-reply/reply/export-html/vendor/marked.min.js`。

全量测试中的 `extension-memory` shard 通过：`35 files, 312 tests`。

```text
corepack pnpm check

result: failed
```

`pnpm check` 失败在 repo 现有 oxlint 债，主要是 `typescript-eslint(no-unnecessary-type-parameters)` 等规则，分布在多个无关文件；本轮没有把这些无关 lint 修复混入 M0-fix。

真实 package CLI smoke 状态：

- 已通过 `extensions/memory-core/src/cli.test.ts` 的 CLI runtime smoke 覆盖 `memory graph status|reindex|search|export --json`。
- 人工尝试 `corepack pnpm openclaw memory graph status --agent main --json` 时，dirty worktree 下 `scripts/run-node.mjs` 进入自动 rebuild 路径并卡住；进程已被终止。
- 直接 `node openclaw.mjs ...` / `node --import tsx src/entry.ts ...` 不加载 extension CLI，返回 `unknown command 'memory'`，因此不计为有效 package CLI smoke。

### 9.2 Live E2E 输入

临时 memory 文件内容中，第 12-18 行为：

```text
line 12: task_123 is blocked by Alice
line 13: owner: Alice
line 14: status: blocked
line 15: Alice decided to ship task_123
line 16: supporting note
line 17: more context
line 18: end of source span.
```

M0-fix proof 使用的 flush JSON：

```json
{
  "events": [
    {
      "actor": "Alice",
      "action": "changed_status",
      "object": "task_123",
      "status_after": "blocked",
      "occurred_at": "2026-04-15",
      "source_ref": "memory/2026-04-15.md#L12-L18"
    },
    {
      "action": "changed_status",
      "object": "task_missing",
      "status_after": "blocked",
      "source_ref": "memory/2026-04-16.md#L1-L1"
    },
    {
      "action": "changed_status",
      "object": "task_overflow",
      "status_after": "blocked",
      "source_ref": "memory/2026-04-15.md#L12-L200"
    }
  ]
}
```

其中第一条合法，第二条指向不存在文件，第三条行号越界。预期结果是只写入第一条，后两条只记录 warning 和 `sourceRefRejected`。

### 9.3 Live E2E 日志证据

M0-fix proof 关键日志如下，已去掉绝对临时路径和 logger JSON metadata：

```text
[memory] canonical.extract.parse_ok events=3
[memory] canonical.store.open agent=main path=<temp-state>/memory/main.graph.sqlite
[memory] canonical.store.schema_ready
[memory] [canonical] source_ref.rejected reason=file_missing source_ref=memory/2026-04-16.md#L1-L1
[memory] [canonical] source_ref.rejected reason=line_range source_ref=memory/2026-04-15.md#L12-L200
[memory] canonical.flush.parsed events=1
[memory] canonical.canonicalize input=1 output=1
[memory] canonical.store.upsert_events records=1
[memory] canonical.reduce events=1 states=1
[memory] canonical.store.refresh_states states=1
[memory] canonical.flush.persisted records=1
[memory] canonical.search query=task_123 k=5 hits=2
[memory] [canonical] usage.returned session=proof-session hits=2
[memory] canonical.memory_search.graph_hits hits=2 rendered=2
[memory] [canonical] usage.used via=memory_get source_ref=memory/2026-04-15.md#L12-L18
[memory] [canonical] usage.used via=llm_output source_ref=memory/2026-04-15.md#L12-L18
[memory] canonical.store.close_all count=1
```

说明：

- `canonical.flush.parsed events=1` 证明 flush JSON 被解析。
- `canonical.store.upsert_events records=1` 证明 event 写入 sidecar。
- `canonical.reduce events=1 states=1` 证明 event -> state 已归并。
- `canonical.search query=task_123 k=5 hits=2` 证明 graph retrieval 工作。
- `canonical.memory_search.graph_hits hits=2 rendered=2` 证明 graph branch render/append 出口能返回可交给 `memory_search` 合并的结果；完整 memory tool wrapper 合并由 `canonical/integration.test.ts` 覆盖。
- `[canonical] source_ref.rejected` 证明 flush persist 前会拒绝缺失文件和越界行号。
- `[canonical] usage.used` 分别通过 `memory_get` 与 `llm_output` 路径触发。
- `hitsUsedRaw` 与 `hitsUsedUniqueRefs` 的差异证明同一 `source_ref` 下 state/event 两个候选会被 raw 计数保留，但 unique metric 已按 source_ref 去重。

### 9.4 V0 Live `memory_search` 返回样例

V0 live E2E 中真实 `memory_search` 返回摘要：

```json
{
  "resultCount": 3,
  "corpora": ["memory", "graph", "graph"],
  "graphDebug": {
    "enabled": true,
    "hits": 2,
    "renderedHits": 2
  },
  "graphHit": {
    "path": "memory/2026-04-15.md",
    "startLine": 12,
    "endLine": 18,
    "corpus": "graph",
    "graphMeta": {
      "type": "state",
      "entity_id": "ent_ff2e8473c188"
    },
    "snippet": "[Graph state]\nentity: ent_ff2e8473c188\nstatus: blocked\nowner: Alice\nlast_updated: 2026-04-17\nsource: memory/2026-04-15.md#L12-L18"
  }
}
```

这证明 graph hit 被 append 到真实 `memory_search` 结果中，并且包含 `path/startLine/endLine`，可以直接喂给 `memory_get`。

### 9.5 Live `memory_get` 回读样例

使用 graph hit 的 `path/startLine/endLine` 调用真实 `memory_get` 后返回：

```json
{
  "path": "memory/2026-04-15.md",
  "text": "line 12: task_123 is blocked by Alice\nline 13: owner: Alice\nline 14: status: blocked\nline 15: Alice decided to ship task_123\nline 16: supporting note\nline 17: more context\nline 18: end of source span."
}
```

这证明 graph hit 能回读原始 Markdown 行段，符合“graph 是 hint，Markdown 是 source of truth”的设计。

### 9.6 Live Graph Status 样例

Live E2E 最终 status：

```json
{
  "enabled": true,
  "bootstrapOnStart": false,
  "extractDuringFlush": true,
  "schemaVersion": "v1",
  "extractorVersion": "v0-2026.04",
  "eventsTotal": 1,
  "entitiesTotal": 1,
  "metrics": {
    "hitsReturned": 2,
    "hitsUsedRaw": 4,
    "hitsUsedUniqueRefs": 2,
    "sourceRefValidated": 1,
    "sourceRefRejected": 2,
    "extractSuccesses": 1,
    "extractFailures": 0,
    "extractLatencyMsSum": 10,
    "extractLatencyMsCount": 1,
    "hitsUsed": 2,
    "extractLatencyMsAvg": 10
  }
}
```

说明：

- `eventsTotal=1` 与 flush JSON 中 1 个 event 对齐。
- `entitiesTotal=1` 与 `task_123` entity 对齐。
- `hitsReturned=2` 来自 state + event 两个 graph hits。
- `sourceRefValidated=1`、`sourceRefRejected=2` 证明 flush persist 强校验生效。
- `hitsUsedRaw=4` 来自 `memory_get` 与 `llm_output` 两条 usage 路径分别命中 state/event 两个候选。
- `hitsUsedUniqueRefs=2` / `hitsUsed=2` 表示兼容字段已收敛为 unique source_ref 语义。

### 9.7 Watcher EMFILE 降级处理验证

当前仓库实现了两层处理：

1. `extensions/memory-core/src/memory/manager-sync-ops.ts` 和 `extensions/memory-core/src/memory/qmd-manager.ts` 对 watcher `error` 注册 handler，遇到 `EMFILE` 等 watcher 初始化/运行错误时记录 warning 并关闭 watcher。
2. `extensions/memory-core/src/memory/manager.ts` 在 FTS-only 路径避免不必要的 embedding provider 初始化。

单测证据：

```text
extensions/memory-core/src/memory/manager.watcher-config.test.ts
case: turns watcher errors into best-effort degraded mode
action: watcher.emit("error", Object.assign(new Error("too many open files, watch"), { code: "EMFILE" }))
assertion: watcher.close called once
```

本报告生成时的 live E2E 为避免本机 fd 限制导致报告生成耗时不可控，使用了 `sync.watch=false`；因此本次 live E2E 日志没有复现真实 EMFILE。EMFILE 降级能力已由代码路径和 targeted test 验证，完整 watcher-on live smoke 标记为待补充。

## 10. 当前交付物

### 10.1 Runtime 能力

- Graph sidecar schema 与 store。
- Flush piggyback JSON parser 与 handler。
- 规则 extractor，可用于 bootstrap/reindex。
- Canonical event/state pipeline。
- V0 FTS graph retrieval。
- `memory_search` append graph hits。
- `memory_get` 回读 graph hit source lines。
- Flush persist 前 `source_ref` 强校验：文件缺失、路径不合法、行号越界的 event 不入库。
- Graph metrics：`hitsReturned`、`hitsUsedRaw`、`hitsUsedUniqueRefs`、`hitsUsed` 兼容 alias、`sourceRefValidated`、`sourceRefRejected`、`extractSuccesses`、`extractFailures`、`extractLatencyMsSum/Count/Avg`。
- Recent graph hit 记录与 usage 标记。
- Memory host event 类型：`memory.graph.recall.recorded`、`memory.graph.recall.used`。
- canonical runtime fallback：graph 异常不阻塞 memory / flush / compaction / active-memory。
- Watcher EMFILE degraded mode。
- Schema v1 sidecar 与 migration：
  - `event_records` / `entity_states` 新列已落地
  - `entity_aliases` 表已建，但行为未启用
  - 旧 v0 sidecar 可原地升级到 v1
- M1 flush prompt 与 parser 升级：
  - 多事件抽取提示
  - `status_before` / `status_after` 支持
  - 3 份 flush 场景 fixture 与自动化验证

### 10.2 CLI / Debug 面

已实现 graph CLI runtime：

- `openclaw memory graph status`
- `openclaw memory graph reindex`
- `openclaw memory graph search`
- `openclaw memory graph export`

已新增 CLI runtime smoke 测试覆盖上述四个 JSON 子命令。真实 package CLI 人工 smoke 仍待补充；本报告更新时，`corepack pnpm openclaw memory graph status --agent main --json` 在 dirty worktree 自动 rebuild 路径中卡住，未作为通过项记录。

### 10.3 测试交付物

已落入仓库的关键测试：

- `extensions/memory-core/src/canonical/integration.test.ts`
- `extensions/memory-core/src/canonical/usage.test.ts`
- `extensions/memory-core/src/canonical/extractor.test.ts`
- `extensions/memory-core/src/canonical/canonicalizer.test.ts`
- `extensions/memory-core/src/canonical/store.test.ts`
- `extensions/memory-core/src/canonical/retriever.test.ts`
- `extensions/memory-core/src/tools.test.ts`
- `extensions/memory-core/src/flush-plan.test.ts`
- `extensions/memory-core/src/prompt-section.test.ts`
- `extensions/memory-core/src/config.test.ts`
- `src/plugins/memory-state.test.ts`
- `src/auto-reply/reply/agent-runner-memory.test.ts`
- `extensions/memory-core/src/memory/manager.watcher-config.test.ts`

### 10.4 Dry-run 工具

`scripts/memory-graph-dryrun.ts` 可离线读取 memory 文件并输出 Markdown 报告，包括：

- 样本文件。
- 抽取到的 `RawEvent[]`。
- action 分布。
- `occurred_at` 覆盖率。
- `source_ref` 精度摘要。

## 11. 已知限制与风险

### 11.1 Extractor 质量限制

当前 bootstrap/reindex 使用规则 extractor。它能覆盖 checklist、status、owner、decision 和显式 task 状态句，但不能理解复杂上下文、跨段落状态归因、隐式 owner、指代消解或 alias。

M7 独立 LLM bootstrap extractor 尚未实现。

### 11.2 Source Ref 校验限制

M0-fix 后，flush persist 前已经验证 `source_ref` 对应的 memory 文件存在，且 `startLine/endLine` 落在文件总行数内。非法 event 会被跳过并计入 `sourceRefRejected`，不会写入 sidecar。

仍然存在的限制：

- bootstrap/reindex 规则抽取依赖文件枚举过程中的真实路径，通常能生成合法行段；但 `memory_search` render 阶段仍只做 `source_ref` 语法解析，不会再次读取文件确认该行段仍存在。
- 如果 memory 文件在 event 入库后被删除或缩短，旧 sidecar hit 仍可能进入 `memory_search`，直到 `memory_get` 回读阶段暴露空读或错误。
- 当前强校验只验证本地 Markdown 文件存在与行号范围，不验证行段语义是否真的支撑 event 内容。

### 11.3 Metrics 语义限制

M0-fix 已将 usage metrics 拆成：

- `hitsUsedRaw`：保留 hit-level 原始命中数。
- `hitsUsedUniqueRefs`：每次 usage 路径按 `source_ref` 去重后的命中数。
- `hitsUsed`：兼容 alias，当前等于 `hitsUsedUniqueRefs`。

仍需注意：`hitsUsedUniqueRefs` 是按每次 `memory_get` 或 `llm_output` usage 事件内部去重，不是全库 lifetime distinct source_ref 集合。同一 `source_ref` 如果在不同轮次多次被使用，会多次累计。

### 11.4 Hook Live Smoke 待补充

`extensions/memory-core/index.ts` 已注册 `after_tool_call` 和 `llm_output` hooks；`usage.ts` 的 usage primitive 有单测覆盖；`canonical/integration.test.ts` 也已经通过真实 hook runner dispatcher 触发 memory-core 注册的 hook handler。

仍待补充的是完整 agent runtime 人工 live smoke，也就是在真实 assistant run 中由 tool event 与 LLM output event 自然触发 hook，而不是测试内直接调用 hook runner。

### 11.5 Performance 风险

本报告生成时的 live E2E 中，`canonical.search` 日志时间与 flush persist 日志之间约 59 秒。该耗时发生在真实 builtin memory manager 的 `memory_search` 前置路径中，可能与本地 auth/profile sync、manager 初始化或 lazy sync 有关；本报告未对该耗时做进一步 profiling。

Graph branch 本身的 sidecar event 数为 1，`search_graph()` 返回 2 hits。需要后续针对更大 memory 数据集补充性能评估。

### 11.6 Watcher-on Live Smoke 待补充

当前代码和测试已经验证 watcher error 降级，但本报告生成时的 live E2E 使用 `sync.watch=false` 绕开 watcher。建议补充一个受控环境下的 watcher-on live smoke，确认真实 `EMFILE` 或同类 watcher error 会被记录为：

```text
memory watch disabled after watcher error: EMFILE: too many open files, watch
```

且不会阻断 `memory_search` graph branch。

### 11.7 宽 Gate 结果与待补充项

本报告更新时已运行全量 `corepack pnpm test`、`corepack pnpm build`、`corepack pnpm tsgo`、`corepack pnpm plugin-sdk:api:check`。其中：

- `corepack pnpm build`、`corepack pnpm tsgo`、`corepack pnpm plugin-sdk:api:check` 通过。
- `corepack pnpm test` 失败在 gateway timeout、UI locale、缺失本地 fixture/vendor 文件等无关面；`extension-memory` shard 通过。
- `corepack pnpm check` 失败在 repo 现有 oxlint 债，未归因到本轮 graph 改动。
- CLI graph 子命令 package 人工 smoke 仍待补充。

这些不影响本报告对 M0-M6 与 M0-fix scoped 功能的描述，但进入 landing/发布前建议补齐或明确豁免。

## 12. V0.1 / M7 待做

M7 及 V0.1 建议范围：

1. 独立 LLM bootstrap extractor。
   - reindex 时在规则抽取之外调用 LLM。
   - 对长文件分块抽取。
   - 增加抽取质量 golden fixtures。

2. Source ref 二次校验与漂移处理。
   - flush persist 强校验已完成。
   - 后续需要在 search render 或定期 maintenance 阶段处理“入库后文件被删除/缩短”的 stale source_ref。
   - 对 stale source_ref 记录 warning 并过滤或触发 reindex。

3. Usage hook live smoke。
   - 测试内真实 hook runner dispatcher 已完成。
   - 后续需要通过完整 agent runtime 跑一次人工 live smoke，确认真实 tool event 与 assistant output event 会自然触发 memory-core hooks。

4. CLI smoke 固化。
   - `openclaw memory graph status --json`
   - `openclaw memory graph reindex --json`
   - `openclaw memory graph search "task_123" --json`
   - `openclaw memory graph export --json`

5. Performance profiling。
   - 分离 builtin manager 初始化耗时、chunk sync 耗时、graph search 耗时。
   - 对 100/1k/10k events 做 sidecar search latency 测试。

6. Retrieval quality。
   - entity alias。
   - status/owner/action 权重。
   - state/event 去重策略。
   - query-aware graph hit selection。

7. Metrics 接入全局观测。
   - 当前 metrics 落在 graph sidecar 内部。
   - 后续可接入全局 OTEL/Prometheus 或统一 host event analytics。
   - 明确 `hitsUsedRaw` 与 `hitsUsedUniqueRefs` 在 eval 报告中的口径。

## 13. 结论

当前仓库已经实现 Graph Index V0 的可用闭环：

```text
flush JSON
  -> parse
  -> canonicalize
  -> sidecar upsert
  -> reduce state
  -> search_graph
  -> memory_search append corpus: "graph"
  -> memory_get 回读原文
  -> usage metrics
```

测试和 live E2E 均证明 graph branch 能在真实 `memory_search` 链路中返回结果，并能通过 `memory_get` 回到原 Markdown 行段。M0-fix 进一步证明：flush persist 会拒绝缺失文件和行号越界的 `source_ref`；usage metrics 已从单一 hit-level `hitsUsed` 收敛为 raw 与 unique source_ref 双口径；memory-core 注册的 `after_tool_call` / `llm_output` hook 可通过真实 hook runner dispatcher 触发。Watcher EMFILE 问题也已经从 crash/阻断风险收敛为 best-effort degraded mode，并有 targeted test 覆盖。

V0 的核心价值是把“结构化 hint + 原文可验证”的链路打通，并保持默认关闭、失败隔离、chunk branch 不变。M0-fix 后，V1 后续工作可以在更可信的基线上进入 M1 schema v1 / alias / embedding。下一阶段重点不应再扩主链路，而应补强 M7 抽取质量、stale source_ref 漂移处理、完整 agent runtime hook live smoke、package CLI smoke 和性能评估。
