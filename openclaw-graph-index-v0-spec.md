# OpenClaw Graph Index Framework V0 — 实施清单

> 本文档面向 Codex 执行。所有路径、函数名、schema 均以 `openclaw-main` 当前代码结构为准。

---

## 0. 项目定位

**名称**:OpenClaw Graph Index Framework V0 (内部模块名 `canonical-memory`,对外仍可称 Graph Index)

**一句话目标**:在不破坏现有 memory / compaction 主链路的前提下,为 OpenClaw 新增一条 graph branch,使 `memory_search` 能同时返回 chunk hit 和结构化 graph hit。

**V0 不是**:高质量事件抽取、query-aware retrieval、完整 GraphRAG。质量问题属于 V1+。

---

## 1. 五个已冻结的决策

| #   | 决策项             | 决定                                                                                                  |
| --- | ------------------ | ----------------------------------------------------------------------------------------------------- |
| 1   | 插件位置           | 内嵌 `memory-core` 作为内部子模块,不新开 `plugins.slots.memory` 槽位                                  |
| 2   | 存储位置           | Sidecar 文件 `~/.openclaw/memory/{agentId}.graph.sqlite`,与现有 chunks SQLite 完全分离                |
| 3   | Extractor 策略     | Piggyback 在 pre-compaction memory flush 的 LLM turn 上,一次调用双产出(Markdown append + 结构化 JSON) |
| 4   | Catch-up hook 位置 | 与决策 3 合并 — 不新增 hook,直接复用 flush turn 的输出                                                |
| 5   | 检索返回协议       | Graph hit 通过 `corpus: "graph"` 标记,每条必须带 `source: "memory/YYYY-MM-DD.md#L12-L18"` 回指        |

---

## 2. V0 明确不做

- 不新增 `graph_Memory.md / graph_memory/*.md` 文件体系
- 不替换 compaction summary
- 不实现 query classifier / query rewriting
- 不做 entity-entity relation 表(V0 只有 event + state)
- 不做复杂 rerank / graph expansion
- 不改 `memory_search` / `memory_get` 对外 schema(只扩展返回字段)
- 不抽取 session transcript(只抽 memory 文件 + flush 上下文)
- 不做 afterTurn 实时增量抽取(freshness 由 chunk branch 兜底)

---

## 3. 模块边界(四个接口,先立住)

所有新代码放在 `extensions/memory-core/src/canonical/` 下。

```
extensions/memory-core/src/canonical/
├── index.ts               # 对外 runtime 出口
├── schema.ts              # SQLite schema + TypeScript 类型
├── store.ts               # sidecar SQLite manager
├── extractor.ts           # flush turn piggyback 抽取
├── canonicalizer.ts       # RawEvent -> EventRecord
├── reducer.ts             # EventRecord[] -> EntityState
├── retriever.ts           # search_graph(query, k)
├── bootstrap.ts           # 首次从 memory 文件冷启动抽取
└── prompt.ts              # graph hit 注入时的 snippet 渲染
```

### 3.1 接口签名

```ts
// extractor.ts
export type RawEvent = {
  actor?: string;
  action: string;
  object?: string;
  status_after?: string;
  occurred_at?: string; // ISO8601 或 "YYYY-MM-DD"
  source_ref: string; // e.g. "memory/2026-04-15.md#L12-L18"
  confidence?: number; // 0..1, 默认 0.5
};

export function extract(
  text: string,
  sourceRef: string,
  llmClient?: LLMClient, // 可选,用于独立 LLM 抽取;piggyback 模式不传
): Promise<RawEvent[]>;

// canonicalizer.ts
export type EventRecord = {
  event_id: string; // sha256(source_ref + actor + action + object + occurred_at)
  source_type: "memory_file" | "flush_turn";
  source_ref: string;
  occurred_at: string;
  entity_id: string; // 由 canonicalizer 生成
  actor: string | null;
  action: string;
  object: string | null;
  status_after: string | null;
  confidence: number;
  extractor_version: string; // 重要:用于日后重抽判定
  created_at: number;
};

export function canonicalize(raw: RawEvent[], extractorVersion: string): EventRecord[];

// reducer.ts
export type EntityState = {
  entity_id: string;
  latest_status: string | null;
  latest_owner: string | null;
  last_event_id: string;
  last_updated_at: number;
};

export function reduce(events: EventRecord[], prevStates: Map<string, EntityState>): EntityState[];

// retriever.ts
export type GraphHit = {
  type: "event" | "state";
  entity_id: string;
  source_ref: string; // 必须存在,可回指 Markdown
  snippet_structured: Record<string, unknown>;
  score: number;
};

export function search_graph(store: CanonicalStore, query: string, k: number): Promise<GraphHit[]>;
```

---

## 4. 数据层(V0.1)

### 4.1 Sidecar SQLite 文件

**路径**:`~/.openclaw/memory/{agentId}.graph.sqlite`

**打开时机**:首次调用 `getCanonicalStore(agentId)` 时懒初始化。`memory.backend = "qmd"` 的用户也能正常工作,因为这张表和 builtin chunks 表无关。

### 4.2 Schema

```sql
-- 元数据表,用于判定是否需要全量重抽
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- 预置:meta.extractor_version, meta.schema_version = "v0"

CREATE TABLE IF NOT EXISTS event_records (
  event_id         TEXT PRIMARY KEY,
  source_type      TEXT NOT NULL,     -- "memory_file" | "flush_turn"
  source_ref       TEXT NOT NULL,     -- 回指 Markdown 的 path#Lx-Ly
  occurred_at      TEXT NOT NULL,     -- ISO8601
  entity_id        TEXT NOT NULL,
  actor            TEXT,
  action           TEXT NOT NULL,
  object           TEXT,
  status_after     TEXT,
  confidence       REAL NOT NULL DEFAULT 0.5,
  extractor_version TEXT NOT NULL,
  created_at       INTEGER NOT NULL   -- unix ms
);

CREATE INDEX IF NOT EXISTS idx_events_entity    ON event_records(entity_id);
CREATE INDEX IF NOT EXISTS idx_events_occurred  ON event_records(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_source    ON event_records(source_ref);

CREATE TABLE IF NOT EXISTS entity_states (
  entity_id        TEXT PRIMARY KEY,
  latest_status    TEXT,
  latest_owner     TEXT,
  last_event_id    TEXT NOT NULL,
  last_updated_at  INTEGER NOT NULL,
  FOREIGN KEY(last_event_id) REFERENCES event_records(event_id)
);

-- FTS5 虚拟表,用于 V0 的朴素 keyword graph search
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
  event_id UNINDEXED,
  entity_id,
  actor,
  action,
  object,
  status_after,
  tokenize = 'unicode61 remove_diacritics 2'
);
```

### 4.3 Canonicalizer 的 entity_id 规则(V0 粗粒度)

```ts
// canonicalizer.ts
function canonicalizeEntityId(raw: string): string {
  const normalized = raw
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^\p{L}\p{N}_\-]/gu, "");
  return `ent_${sha1(normalized).slice(0, 12)}`;
}
```

V1 再接 alias resolution,此处不要直接 inline,必须走 `canonicalizeEntityId()` 函数,方便将来替换。

---

## 5. 构建层(V0.2)

### 5.1 Bootstrap 抽取(首次冷启动 / 手动 reindex)

触发条件:

- Agent 启动时检测到 `{agentId}.graph.sqlite` 不存在或 `meta.extractor_version` 与当前代码版本不一致
- 用户执行 `openclaw memory graph reindex`(新增 CLI 子命令)

流程:

1. 枚举 `MEMORY.md`、`memory/YYYY-MM-DD.md`(不含 `memory/.dreams/`、`memory/dreaming/`、`memory/.*`)
2. 对每个文件跑 **规则 + LLM 混合抽取**:
   - 先用正则扫描 `- [x]`、`status: xxx`、`owner: xxx`、`decided to ...`、日期头 等明显模式
   - 如果文件长度 > 500 字符,额外调一次 LLM 抽取(可复用 memory-core 的 LLM provider)
3. `RawEvent[]` → `canonicalize()` → `EventRecord[]` → 批量写入 SQLite
4. `reduce()` 更新 `entity_states`
5. 写入 `meta.extractor_version`

**成本控制**:bootstrap 对每个 agent 只跑一次。如果文件数 > 50,分批跑并打印进度。

### 5.2 Catch-up 抽取(piggyback 在 memory flush 上)

**改动点**:`extensions/memory-core/src/flush-plan.ts` 的 flush prompt。

**当前 flush prompt 语义**:静默 agent 读取 transcript,把 durable 信息 append 到 `memory/YYYY-MM-DD.md`,完成后 `NO_REPLY`。

**V0 新增**:在 flush prompt 中增加一段结构化输出要求。

**新 prompt 片段(追加到 flush prompt 末尾)**:

````
除了将内容追加到 memory/YYYY-MM-DD.md 之外,你还必须在本次回复的最后
输出一个 JSON 代码块,格式如下:

```json
{
  "events": [
    {
      "actor": "Alice",
      "action": "changed_status",
      "object": "task_123",
      "status_after": "blocked",
      "occurred_at": "2026-04-15",
      "source_ref": "memory/2026-04-15.md#L12-L18",
      "confidence": 0.8
    }
  ]
}
````

规则:

- 只抽取**新追加到 daily memory 的内容**中涉及的事件
- source_ref 必须是你**刚刚写入**的 memory/YYYY-MM-DD.md 的行范围
- 如果没有可抽取的事件,输出 {"events": []}
- 如果本轮无需回复(NO_REPLY),仍须输出这个 JSON 块

````

**解析**:在 `agent-runner-memory.ts` 的 `runMemoryFlushIfNeeded` 回调里,flush agent 结束后:

```ts
// 伪代码
const flushOutput = await runFlushAgent(...);
const rawEvents = parseGraphJsonBlock(flushOutput);  // 容错解析,失败返回 []
if (rawEvents.length > 0) {
  const store = getCanonicalStore(agentId);
  const records = canonicalize(rawEvents, EXTRACTOR_VERSION);
  await store.upsertEvents(records);
  await store.refreshEntityStates(records);
  metrics.inc("canonical.flush_events_extracted", records.length);
}
````

**容错原则**:graph 抽取失败**不得**影响 flush 本身。所有 catch 到的异常记 warning log,继续走。

### 5.3 Extractor 版本号

`extractor_version` 当前固定为 `"v0-2026.04"` 常量。日后修改抽取逻辑时 bump 版本号,bootstrap 检测到不一致则全量重建 graph SQLite。

---

## 6. 检索层(V0.3)

### 6.1 `memory_search` 改动

文件:`extensions/memory-core/src/tools.ts` + `extensions/memory-core/src/tools.shared.ts`

**不改 tool schema**,只在内部增加一路:

```ts
// 伪代码
async function memorySearch(args) {
  const [chunkHits, graphHits] = await Promise.all([
    existingChunkSearch(args),
    config.graphIndex.enabled
      ? search_graph(store, args.query, args.maxResults ?? 5)
      : Promise.resolve([]),
  ]);

  // V0 融合策略:最朴素的 union,不做 rerank
  const merged = [
    ...chunkHits, // 保持原顺序
    ...graphHits.map((h) => renderGraphHit(h)), // 附加在后面
  ];

  return merged;
}
```

### 6.2 返回结构扩展

Chunk hit 保持原样。Graph hit 的形态:

```json
{
  "path": "memory/2026-04-09.md",
  "startLine": 12,
  "endLine": 18,
  "score": 0.7,
  "snippet": "[Graph state]\nentity: task_123\nstatus: blocked\nowner: Alice\nlast_updated: 2026-04-10\nsource: memory/2026-04-09.md#L12-L18",
  "source": "memory",
  "corpus": "graph",
  "graphMeta": {
    "type": "state",
    "entity_id": "ent_abc123def456"
  }
}
```

**关键约束**:

- `path` / `startLine` / `endLine` 必须能让 `memory_get` 成功读取原文
- `corpus: "graph"` 是模型区分的依据
- `snippet` 是人类可读的结构化渲染,见 `prompt.ts::renderGraphHit`

### 6.3 `renderGraphHit` 渲染规则

```ts
// prompt.ts
function renderGraphHit(hit: GraphHit): string {
  if (hit.type === "state") {
    const { entity_id, latest_status, latest_owner, last_updated_at } = hit.snippet_structured;
    return [
      "[Graph state]",
      `entity: ${entity_id}`,
      latest_status && `status: ${latest_status}`,
      latest_owner && `owner: ${latest_owner}`,
      `last_updated: ${formatDate(last_updated_at)}`,
      `source: ${hit.source_ref}`,
    ]
      .filter(Boolean)
      .join("\n");
  }
  // event 类似
  return [
    "[Graph event]",
    `${formatDate(hit.occurred_at)} ${actor} ${action} ${object} -> ${status_after}`,
    `source: ${hit.source_ref}`,
  ].join("\n");
}
```

### 6.4 V0 的 graph search 实现

```ts
// retriever.ts,V0 只做 FTS + 最近性 boost
async function search_graph(store, query, k) {
  const fts = await store.db.all(
    `SELECT e.*, bm25(event_fts) AS fts_score
     FROM event_fts
     JOIN event_records e ON e.event_id = event_fts.event_id
     WHERE event_fts MATCH ?
     ORDER BY fts_score LIMIT ?`,
    [tokenize(query), k * 2]
  );

  // 每个 entity 至多返回 1 个 state + 1 个 event
  const seen = new Set<string>();
  const hits: GraphHit[] = [];
  for (const row of fts) {
    if (seen.has(row.entity_id)) continue;
    seen.add(row.entity_id);
    const state = await store.getEntityState(row.entity_id);
    if (state) hits.push({ type: "state", ... });
    hits.push({ type: "event", ... });
    if (hits.length >= k) break;
  }
  return hits;
}
```

V1 再换成 embedding / entity-aware retrieval,接口不变。

---

## 7. 注入层(V0.4)

### 7.1 Prompt 指南同步

文件:`extensions/memory-core/src/prompt-section.ts`

在 `buildMemoryPromptSection()` 已有的 memory 工具使用指导末尾追加:

```
Some memory_search results may have `corpus: "graph"`. These are structured
evidence extracted from your memory files:
- `[Graph state]` shows the current state of an entity (task, project, person).
- `[Graph event]` shows a recorded change event.
- Graph hits always carry a `source:` line pointing back to the original
  memory file. You can call `memory_get` on that path to verify the raw text.
- Treat graph hits as **hints**, not ground truth. If a decision depends on
  the exact wording, always `memory_get` the source.
```

### 7.2 合并到现有 recall 区域

不要单独开一个新的 prompt section。graph hit 与 chunk hit 走同一条 recall pipeline,模型不需要知道它们存储在不同表里。

---

## 8. 开关与观测(V0.5)

### 8.1 配置开关

在 `memory-core` 的 plugin config schema 中新增:

```json
{
  "plugins": {
    "entries": {
      "memory-core": {
        "config": {
          "graphIndex": {
            "enabled": true,
            "bootstrapOnStart": true,
            "extractDuringFlush": true
          }
        }
      }
    }
  }
}
```

默认 `enabled: false`,灰度可控。

### 8.2 指标(最少 6 个)

| 指标                               | 含义                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------- |
| `canonical.events_total`           | 累计 event 数(gauge)                                                             |
| `canonical.entities_total`         | 累计 entity 数(gauge)                                                            |
| `canonical.hits_returned`          | graph hit 被 `memory_search` 返回的次数(counter)                                 |
| `canonical.hits_used`              | **关键**:graph hit 返回后,模型在随后工具调用或回复中 citing 该 source_ref 的次数 |
| `canonical.extractor_latency_ms`   | flush piggyback 抽取延迟分布(histogram)                                          |
| `canonical.extractor_failure_rate` | 抽取失败 / 总次数(counter pair)                                                  |

`hits_used` 参照 `memory-core` 现有 `short-term-recall` 的信号记录机制实现:`memory_search` 返回后异步记录候选 ID,主 agent 结束本轮后检查本轮 transcript 中是否出现 `source_ref` 字符串或 `memory_get(path)` 调用。

### 8.3 CLI 子命令

新增 `openclaw memory graph ...`:

```
openclaw memory graph status       # 显示 event/entity 数量、上次抽取时间
openclaw memory graph reindex      # 全量重抽 bootstrap
openclaw memory graph search <q>   # 调 search_graph 返回 JSON,用于调试
openclaw memory graph export       # 导出 events + states 为 JSONL,调试用
```

---

## 9. 动工前必做的 dry-run(强制)

**不要直接进入 V0.1 编码**。先做离线 extractor 验证,避免架构跑通但抽取完全不可用。

### Dry-run 步骤

1. 挑 3 份真实 `memory/YYYY-MM-DD.md` + 1 份 `MEMORY.md` 作为样本
2. 单独实现 `extractor.ts` 的 LLM 版本(不接任何 OpenClaw 管线)
3. 跑一遍,人工评估输出的 `RawEvent[]`:
   - entity_id 分布是否合理(不要有一半 event 指向同一个 `ent_other`)
   - action 字段是否有足够多样性
   - occurred_at 覆盖率(应 > 60%)
   - source_ref 是否准确
4. 同步跑一遍 flush piggyback prompt,确认 JSON 块能稳定输出且可解析(失败率 < 10%)
5. **如果任一步骤明显不行**,先调整 prompt / 加规则预处理,不要进入 V0.1

Dry-run 产物:一份 `canonical-extractor-dryrun.md` 报告,包含样本、输出、质量评估、prompt 版本号。

---

## 10. 完成标准(V0 is done when...)

V0 不以"回答质量提升"为验收标准。以下 7 条工程标准全部成立即完成:

1. ✅ `memory-core` 原有 memory 文件语义未改变(bootstrap 文件、daily note、flush 行为、dreaming)
2. ✅ 原有 chunk index 正常工作,`memory.backend` 为 builtin 或 qmd 均不受影响
3. ✅ 关闭 `graphIndex.enabled` 时,系统行为与 V0 之前完全一致
4. ✅ 开启后,flush 发生时 graph 表被更新(可通过 `openclaw memory graph status` 观察)
5. ✅ `memory_search` 返回结果中可见 `corpus: "graph"` 的 hit
6. ✅ Graph hit 的 `path/startLine/endLine` 能被 `memory_get` 成功读取
7. ✅ 可以在不改框架的前提下,独立替换 `extractor.ts` / `retriever.ts` / `reducer.ts` 中任意一个

---

## 11. Milestone 拆分(建议给 Codex 按此分 PR)

| Milestone | 内容                                                              | 可独立验证                                  |
| --------- | ----------------------------------------------------------------- | ------------------------------------------- |
| M0        | Dry-run 报告                                                      | 手动 review                                 |
| M1        | `canonical/` 目录骨架 + schema.ts + store.ts + 单元测试           | SQLite 创建、CRUD 通过                      |
| M2        | canonicalizer + reducer + 单元测试                                | 给定 RawEvent[],输出稳定 EventRecord[]      |
| M3        | bootstrap.ts(规则部分) + CLI `graph reindex` + `graph status`     | 跑一次 MEMORY.md 能看到 events              |
| M4        | Flush piggyback:改 flush prompt + 解析器 + 容错                   | 关 flush 仍正常;开 flush 能看到 events 增长 |
| M5        | retriever.ts(FTS 版) + `memory_search` 集成 + prompt-section 更新 | 模型能看到 `corpus: "graph"` hit            |
| M6        | 观测指标 + `hits_used` 追踪                                       | metric endpoint 有数据                      |
| M7        | bootstrap 的 LLM 部分(可选,若 dry-run 发现规则够用可跳过)         |                                             |

M1~M6 是硬要求,M0 是前置,M7 可视 dry-run 结果决定。

---

## 12. 风险与 fallback

| 风险                                       | 触发条件               | Fallback                                                                        |
| ------------------------------------------ | ---------------------- | ------------------------------------------------------------------------------- |
| Flush LLM 输出 JSON 解析失败               | prompt 不够稳定        | `try/catch` + `events: []`,不影响 flush。连续 3 次失败后本会话禁用 piggyback    |
| Graph SQLite 损坏                          | 异常崩溃 / 磁盘满      | 删库重来。Bootstrap 可从 memory 文件重建,无数据损失                             |
| Entity_id 爆炸(一天出现 > 500 个新 entity) | canonicalizer 规则太粗 | 告警 + 记 warning。V0 不自动清理,V1 接 entity resolution                        |
| Graph hit 挤占 chunk hit 位置              | `maxResults` 太小      | V0 的 union 策略已把 chunk 放在前面;若仍有问题,下调 graph `k`                   |
| QMD 用户报告异常                           | sidecar 路径冲突       | sidecar 路径与 QMD home 不重叠,不应发生;若发生,关闭 `graphIndex.enabled` 即恢复 |

---

## 13. 代码改动面汇总(给 Codex 快速定位)

| 文件                                           | 改动类型                                                             |
| ---------------------------------------------- | -------------------------------------------------------------------- |
| `extensions/memory-core/src/canonical/*`       | **新增**(9 个文件)                                                   |
| `extensions/memory-core/src/flush-plan.ts`     | **修改**:flush prompt 追加 JSON 块要求                               |
| `extensions/memory-core/src/tools.ts`          | **修改**:`memory_search` 内部 union graph hit                        |
| `extensions/memory-core/src/tools.shared.ts`   | **修改**:graph hit schema 纳入返回类型                               |
| `extensions/memory-core/src/prompt-section.ts` | **修改**:追加 graph hit 使用指南                                     |
| `extensions/memory-core/index.ts`              | **修改**:注册 canonical runtime、CLI 子命令、config schema           |
| `extensions/memory-core/openclaw.plugin.json`  | **修改**:新增 `graphIndex` config schema                             |
| `src/auto-reply/reply/agent-runner-memory.ts`  | **修改**:`runMemoryFlushIfNeeded` 解析 flush 输出,调 canonical store |

**明确不动的文件**:

- `src/context-engine/*`
- `src/agents/compaction.ts`
- `extensions/memory-core/src/memory/*`(chunks SQLite 相关)
- `extensions/memory-core/src/dreaming*.ts`
- `extensions/memory-core/src/short-term-promotion.ts`

---

## 14. 给 Codex 的执行提示

1. **先 M0**。Dry-run 不通过不要进 M1。
2. 每个 Milestone 一个 PR,PR 描述里必须说明"本 PR 前后,关闭 `graphIndex.enabled` 时行为是否一致"。
3. 所有 canonical 模块默认走 `try/catch + fallback`,**永远不得让 graph 异常阻塞主 memory / flush / compaction 流程**。
4. 单元测试放 `extensions/memory-core/src/canonical/__tests__/`,至少覆盖 canonicalizer、reducer、retriever 三个核心逻辑。
5. 所有 log 前缀 `[canonical]`,方便 grep。
6. 遇到 schema 或接口歧义,**不要自行推测** — 停下来回到本文档确认,或在 PR 里标注 `QUESTION:` 等待 review。

---

## 15. 版本与联系

- Spec version: `v0-2026.04.16`
- Extractor version(代码常量): `v0-2026.04`
- 本文档是 V0 的单一事实来源。任何偏离需更新本文档后再实施。
