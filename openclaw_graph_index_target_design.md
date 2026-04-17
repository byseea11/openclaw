# OpenClaw Graph Index 目标方案（原始处理 vs 目标处理）

## 一、文档目的

这份文档只做两件事：

1. 说明 **原始 OpenClaw 怎么处理 memory / index / context**
2. 说明 **我们预期要把 Graph Index 改成什么样**

这里不再讨论当前 V0 的折中实现细节，也不再把 graph 继续描述成“从 Markdown 再扫一遍”的索引。  
这份文档的目标，是把后续开发的目标形态说清楚。

---

## 二、先说明“真相源”是什么意思

“真相源”不是“历史信息”的同义词。

“历史信息”是一个很宽的概念，session、memory 文件、summary、tool result 都可以算历史。  
**真相源**更具体，指的是：

> **当系统要重建、校验、发生冲突仲裁时，最后以哪份原始载体为准。**

所以，“真相源”更接近以下三个问题：

- **什么是原始记录**
- **什么是派生结果**
- **冲突时信谁**

---

## 三、原始 OpenClaw 的处理方式

原始 OpenClaw 的 memory 是一个：

**Markdown 记忆文件 + 检索索引 + 工具召回 + flush / promotion**

组成的系统。

它的核心特点是：

- 长期事实写进 `MEMORY.md`
- 每日短期上下文写进 `memory/YYYY-MM-DD.md`
- 再把这些文件编译成 SQLite / QMD 索引供 `memory_search` 检索
- 检索索引只是派生层，不是新的事实源

### 3.1 原始 OpenClaw 的写入方式

典型路径是：

- 用户让系统“记住 …”时，agent 决定写 `MEMORY.md` 或 `memory/YYYY-MM-DD.md`
- 上下文快满时，pre-compaction flush 会把重要内容 append 到 `memory/YYYY-MM-DD.md`
- promotion / dreaming 会把高分候选追加到 `MEMORY.md`

写入完成后，memory 文件变化会触发索引 dirty / 同步，索引对象是 chunk。

### 3.2 原始 OpenClaw 的检索方式

原始 OpenClaw 的 builtin memory index 会把：

- `MEMORY.md`
- `memory/**/*.md`
- 可选的 session transcripts

先转成 chunk，再写入：

- `files`
- `chunks`
- `chunks_fts`
- `chunks_vec`

之后：

- `memory_search` 检索这些 chunk
- `memory_get` 再按 path/line 安全回读原文

所以，原始 OpenClaw 的主检索对象是：

**文本块（chunk）**

而不是：

- 事件对象
- 状态对象
- 实体关系对象

### 3.3 原始 OpenClaw 的上下文组织

OpenClaw 的会话历史真正保存在 transcript 中。  
compaction 会把旧历史折叠成 transcript 里的 `compaction` entry。  
同时，context engine 有这几个生命周期：

- `afterTurn`
- `ingest`
- `maintain(reason=turn)`
- `compact()`
- `maintain(reason=compaction)`

这说明：

**session transcript 本来就是系统里最细粒度的会话原始流。**

---

## 四、我们预期要改成什么样

我们现在要改的重点，不是再从 Markdown 里抽一遍 graph。

真正的变化是：

> **把 graph 的主抽取来源，从 Markdown 改成 session transcript span。**

更准确地说：

- **Markdown 继续保留**
- 因为它是人类可审计、可编辑的 durable memory 载体
- **但 graph 的主抽取不再从 md 做**
- **而是从 transcript delta / transcript span 做 canonicalization**
- 然后把结果写进 `EventRecord / EntityState` 这种 sidecar 结构化层

所以这里真正要表达的，不是：

- “真相源改成 graph”

而是：

- **graph 的主输入源，从 Markdown 改成 transcript**

---

## 五、我们目标里的两类“真相源”

### 5.1 会话事件的真相源：transcript

对 graph 来说，最重要的是：

- 谁在什么时间说了什么
- 工具返回了什么
- 状态是怎么变化的
- 哪个事件覆盖了哪个旧事件

这些信息最完整、最细粒度、最不容易被摘要化抹平的载体，其实是：

**session transcript JSONL**

而不是：

`memory/YYYY-MM-DD.md`

因为 daily memory 本身是 flush 或人工沉淀后的抽取视图，不是完整事件流。  
如果只从 daily memory 抽，很多结构化关系会在 compaction 或 flush 阶段被压平。

### 5.2 可审计 durable memory 的真相源：Markdown

另一方面，长期稳定事实和人类可见记忆，仍然应该落在：

- `MEMORY.md`
- `memory/YYYY-MM-DD.md`

因为原始 OpenClaw 的哲学就是：

**长期记忆必须落在可审计文件中；索引只是召回加速层。**

这一点不应该改变。

所以目标设计里要明确区分：

- **graph 抽取的主输入源：transcript**
- **durable memory 的人类审计源：Markdown**

---

## 六、原始处理 vs 目标处理

### 6.1 原始 OpenClaw

```text
用户消息 / flush / promotion
  -> 写 MEMORY.md 或 memory/YYYY-MM-DD.md
  -> 索引系统把 Markdown 切 chunk
  -> memory_search 检索 chunk
  -> memory_get 回读原文
```

这里的主思路是：

**先写文件，再围绕文件做检索。**

### 6.2 我们预期的改造

```text
session transcript delta / toolResult / assistant turn
  -> event extraction
  -> canonicalize
  -> append EventRecord
  -> merge EntityState
  -> graph retrieval

同时：
重要内容仍可写回 MEMORY.md / memory/YYYY-MM-DD.md
  -> 作为人类可审计记忆
  -> 作为校正 / 回流 / provenance 绑定层
```

也就是说，新的 graph 处理逻辑应该是：

**先从 session 抽事件，再把结果投影进 graph sidecar；Markdown 不再是 graph 的主抽取源，而是 durable memory 和人工校正层。**

---

## 七、Graph Index 的生命周期应该怎么设计

这里是这版方案最关键的部分。

Graph Index 不应该继续沿用原始 chunk index 的：

**file dirty -> reindex**

主语义。

因为 chunk index 的主对象是：

- 文件文本
- chunk

而 Graph Index 的主对象应该是：

- transcript span
- canonical event
- current entity state

所以 Graph Index 应该从：

**reindex graph index**

改成：

**update graph index**

也就是：

- append 事件
- merge 状态
- 推进覆盖边界
- 只在少数情况下做 full rebuild

---

## 八、Graph Index 的核心数据层

### 8.1 EventRecord

`EventRecord` 用于保存会话中的标准化事件流。

建议字段：

- `event_id`
- `session_id`
- `source_type`（transcript / tool_result / flush / promotion / memory_write）
- `source_ref`
- `occurred_at`
- `entity_id`
- `entity_type`
- `actor`
- `action`
- `object`
- `status_before`
- `status_after`
- `owner`
- `participants`
- `project_id`
- `task_id`
- `decision_id`
- `supersedes`
- `confidence`
- `extraction_version`

### 8.2 EntityState

`EntityState` 用于保存某个实体的当前态。

建议字段：

- `entity_id`
- `entity_type`
- `latest_status`
- `latest_owner`
- `latest_due_date`
- `latest_decision`
- `latest_summary`
- `open_questions`
- `supporting_event_ids`
- `last_event_id`
- `last_updated_at`
- `confidence`

### 8.3 Projection Cursor / Coverage State

为了让 graph index 真正变成“update”而不是“反复重建”，建议新增一层覆盖状态表。

例如：

- `source_projection_state`
  - `source_kind`
  - `source_id`
  - `covered_until_entry_id`
  - `covered_until_line`
  - `last_projected_at`
  - `projection_version`
  - `status`

这张表的意义是：

- 记录哪些 transcript span 已经投影
- 记录哪些 flush append 已处理
- 记录哪些 promotion append 已处理
- 避免重复 append
- 避免遗漏更新

---

## 九、Graph Index 的 3 个主挂点

### 9.1 afterTurn：主增量抽取点

每轮结束后，从本轮新增的：

- `user`
- `assistant`
- `toolResult`

里做轻量 event extraction，生成 `EventRecord`，再更新受影响的 `EntityState`。

它的意义是：

**graph 不再等文件变化或 reindex，而是跟着 session 实时演进。**

这一层是 Graph Index 的主增量入口。

---

### 9.2 pre-compaction catch-up：兜底抽取点

在真正 compaction 前，对：

**即将被 compact 掉的 transcript span**

做一次更重的结构化抽取，然后再 compaction。

它的意义是：

**保证历史在被 summary 抹平之前，graph 已经拿到足够细的事件关系。**

这一层负责补齐 afterTurn 可能漏掉的结构化关系。

---

### 9.3 memory 文件变更后：补充校正点

`MEMORY.md` 和 `memory/YYYY-MM-DD.md` 的变化不再是 graph 的主抽取入口，而只作为：

- 用户手工修正后的回流
- long-term promotion 后的 state 修正
- provenance 绑定增强
- durable memory 与 graph 之间的一致性校对

也就是说：

**memory 文件变更后，不是 reindex graph，而是 update graph 的校正分支。**

---

## 十、Graph Index 的更新操作应该是什么

Graph Index 的更新不应该被设计成：

- 搜索前重扫所有 md
- 文件 dirty 后直接 reindex 全部 graph

而应该拆成 3 种显式操作。

### 10.1 appendGraphEvents(source)

输入：

- turn transcript span
- flush append
- promotion append
- memory write context

输出：

- append 到 `EventRecord`

特点：

- append-only
- 可追踪 source
- 可回放
- 可幂等

---

### 10.2 mergeEntityState(entity_ids)

输入：

- 受影响 entity 的 id 集合

输出：

- 更新 `EntityState`

特点：

- 不简单覆盖
- 基于 reducer / merge policy
- 支持：
  - 时间新旧
  - authority
  - confidence
  - supersedes

---

### 10.3 drainPendingGraphUpdates()

输入：

- 尚未投影的 source
- 尚未 merge 的事件

输出：

- 在 search 前补齐 graph update

这一步的意义是：

**搜索前不做 graph reindex，只做 pending update drain。**

---

## 十一、什么时候才需要 full rebuild

Graph Index 不是永远不重建，而是：

**只在 graph 自己的 schema / extractor / reducer 规则变化时重建。**

例如：

- canonical schema version 变化
- extractor version 变化
- event_id / entity_id 生成规则变化
- reducer / merge policy 变化
- source_ref 解析规则变化
- alias resolution 规则变化
- graph FTS schema 变化

这些情况应该触发：

**rebuildGraphIndex()**

但以下这些 chunk index 的配置变化，不应该自动强制 graph rebuild：

- embedding provider 变化
- vector dims 变化
- chunk tokenizer 变化

因为这些主要影响的是 chunk branch，不一定影响 graph branch。

---

## 十二、Prompt 构建前：Query-Aware Evidence Packaging

这里不要直接把 graph 生硬塞进 system prompt。

建议挂在两条现有路径上。

### 路径 A：memory_search 内部扩展成 hybrid retrieval

保持 `memory_search` 仍是唯一对外 recall 工具。  
但在内部：

- 始终并行运行 chunk branch 和 graph branch
- 用 fusion rerank 做统一排序
- 不再只是 graph append-only hint
- 而是统一的 recall 结果

也就是说：

```text
memory_search
  -> chunk branch
  -> graph branch
  -> fusion rerank
  -> unified recall results
```

这里不建议先做强 query classifier。  
第一版直接双路并行，再用轻量 query features 调权就够了。

---

### 路径 B：active-memory / contextEngine.assemble() 使用内部 evidence pack builder

这里新增一个内部：

`buildEvidencePack(query)`

输入：

- unified recall results

输出三个部分：

#### A. state view
优先来自 `EntityState`，而不是自由摘要。  
如果 `EntityState` 不足，再由命中的 `EventRecord` 临时 rollup。

#### B. supporting events
2–5 条关键事件，按时间或因果顺序排列。

#### C. raw evidence refs / spans
少量原文 path + line range 或直接原文片段，保证可回溯。

这个 evidence pack 的意义是：

- 不改变工具协议
- 不新增 graph tool
- 不把 graph 直接硬塞进 system prompt
- 但让 graph 真正服务当前 query

---

## 十三、Prompt 里的接入顺序

建议按下面这个顺序演进：

### 第一步：接到 active-memory
在 `before_prompt_build` 路径里先接入 evidence pack builder。  
这样可以低侵入地先做 graph-aware recall。

### 第二步：接到 contextEngine.assemble()
再把同一个 evidence pack builder 接到 `contextEngine.assemble()`，放到 cache boundary 后的动态 evidence slots。

推荐的动态槽位顺序：

1. recent live context
2. query-specific state view
3. supporting events
4. top-1 / top-3 raw evidence
5. current user prompt

这样：

- stable prefix 继续保持稳定
- query-aware 内容不污染缓存前缀
- 最关键证据靠近当前 query
- 更适合 prompt-cache-aware serving

---

## 十四、原始 OpenClaw vs 目标 Graph Index 的一句话总结

**原始 OpenClaw 是“以 Markdown 为可审计记忆源、以 chunk 为检索对象”的系统；我要改成的是“仍保留 Markdown 作为 durable memory，但 graph 的主抽取来源改为 session transcript span，并把事件流持续投影为 `EventRecord / EntityState`，让 graph 成为 transcript-driven 的 canonical memory 层”；在 prompt 构建前，再通过 `memory_search` 内部 hybrid retrieval 与 `buildEvidencePack(query)` 实现 query-aware evidence packaging，让 graph 不只是结构化 hint，而是真正服务当前轮上下文构建。**

---

## 十五、最后的设计原则

这版方案最后可以收敛成 5 条原则：

1. **不改 OpenClaw 的 durable memory 哲学**
   - Markdown 仍是可审计记忆载体

2. **graph 的主抽取来源改成 transcript**
   - 不再以 md 为 graph 主抽取源

3. **graph index 的主语义改成 update**
   - append events
   - merge states
   - drain pending updates
   - 不是默认 reindex

4. **对外工具协议尽量不变**
   - 仍然是 `memory_search / memory_get`

5. **graph 最终要服务 prompt 构建**
   - hybrid retrieval
   - evidence pack
   - cache-boundary-aware placement
