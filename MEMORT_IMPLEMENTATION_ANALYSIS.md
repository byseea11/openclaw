# OpenClaw Memory 实现解析

本文基于 `openclaw-main` 当前本地代码做静态分析，重点解释 memory 的架构、分层、核心处理、数据流和实现方式。

## 一句话总览

OpenClaw 的 memory 不是模型内部的隐藏状态，而是一套“可审计 Markdown 记忆文件 + 可插拔检索后端 + 工具/Prompt 注入 + 后台整理晋升”的系统。

核心默认实现是 `extensions/memory-core`。它把长期事实放在工作区 Markdown 文件里，把检索索引放在每个 agent 独立的 SQLite 或 QMD 索引里，并通过 `memory_search`、`memory_get`、pre-compaction flush、dreaming/promotion、active-memory 子代理等机制，把记忆从“写入、索引、召回、读取、整理、晋升”串起来。

## 关键文件地图

主要入口与插件：

- `extensions/memory-core/index.ts`：默认 memory 插件入口，注册 embedding provider、memory capability、工具和 CLI。
- `extensions/memory-core/openclaw.plugin.json`：插件声明，`kind: "memory"`，并声明 dreaming 配置 schema。
- `extensions/active-memory/index.ts`：可选的主动记忆插件，在主回复前运行一个阻塞 memory 子代理。
- `extensions/memory-wiki/`：旁路知识库插件，把 durable memory 编译为 provenance-rich wiki。
- `extensions/memory-lancedb/`：另一个 LanceDB 长期记忆插件示例/替代实现。

默认检索与索引：

- `extensions/memory-core/src/memory/manager.ts`：`MemoryIndexManager`，内置 SQLite 后端的主类。
- `extensions/memory-core/src/memory/manager-sync-ops.ts`：文件监听、增量同步、session 同步、安全全量重建。
- `extensions/memory-core/src/memory/manager-embedding-ops.ts`：chunk embedding、缓存、批处理、重试、写入 chunks/FTS/vector。
- `extensions/memory-core/src/memory/manager-search.ts`：向量搜索、FTS/BM25 搜索、FTS-only 降级搜索。
- `extensions/memory-core/src/memory/hybrid.ts`：向量结果和关键词结果的混合排序。
- `extensions/memory-core/src/memory/qmd-manager.ts`：QMD sidecar 后端管理器。
- `extensions/memory-core/src/memory/search-manager.ts`：根据配置选择 QMD 或 builtin，并实现 QMD 失败回退 builtin。

Memory host SDK：

- `src/memory-host-sdk/host/internal.ts`：memory 文件发现、extraPaths、multimodal 文件、Markdown chunking。
- `src/memory-host-sdk/host/memory-schema.ts`：SQLite `meta/files/chunks/embedding_cache/chunks_fts` schema。
- `src/memory-host-sdk/host/read-file.ts`：`memory_get` 的路径约束和安全读取。
- `src/memory-host-sdk/host/backend-config.ts`：`memory.backend`、QMD collections、scope、limits 配置解析。
- `src/memory-host-sdk/host/qmd-process.ts`：QMD CLI spawn、可用性探测、输出限制。

工具、Prompt、运行时集成：

- `extensions/memory-core/src/tools.ts`：实现 `memory_search` 和 `memory_get`。
- `extensions/memory-core/src/tools.shared.ts`：工具 schema、manager 解析、wiki supplement 聚合。
- `extensions/memory-core/src/prompt-section.ts`：给模型注入 memory tool 使用指导。
- `src/plugins/memory-state.ts`：全局 memory capability 注册状态。
- `src/context-engine/delegate.ts`：给 context engine 提供 `buildMemorySystemPromptAddition`。
- `src/auto-reply/reply/agent-runner-memory.ts`：pre-compaction memory flush。
- `extensions/memory-core/src/flush-plan.ts`：flush 触发阈值、目标文件和安全提示。

整理与晋升：

- `extensions/memory-core/src/short-term-promotion.ts`：短期 recall 信号记录、打分、晋升到 `MEMORY.md`。
- `extensions/memory-core/src/dreaming.ts`：托管 dreaming cron、deep promotion。
- `extensions/memory-core/src/dreaming-phases.ts`：light / REM / deep 阶段。
- `extensions/memory-core/src/rem-evidence.ts`：grounded REM/backfill 的候选提取。

## 几层设计

OpenClaw memory 可以理解为 7 层。

### 第 1 层：用户可审计的文件记忆层

最底层是 agent workspace 里的 Markdown 文件：

- `MEMORY.md`：长期记忆，放稳定事实、偏好、决策。
- `memory/YYYY-MM-DD.md`：每日短期记忆，放当天上下文、观察、工作记录。
- `DREAMS.md`：dreaming/REM/backfill 的人类可读报告。
- `memory/.dreams/`：机器状态，包括短期 recall store、phase signals、事件日志等。

这一层的设计重点是“记忆可看、可编辑、可备份”。项目文档也明确说，模型只记得写到磁盘的东西，没有隐藏状态。

### 第 2 层：memory 插件能力层

默认插件是 `memory-core`。它在 `index.ts` 中注册一组统一能力：

- `promptBuilder`：生成系统 prompt 中的 memory recall 指导。
- `flushPlanResolver`：给 compaction 前的记忆写入提供计划。
- `runtime`：暴露 `getMemorySearchManager`、`resolveMemoryBackendConfig` 等运行时能力。
- `publicArtifacts`：给 `memory-wiki` 这类插件读取公共 memory artifact。
- `memory_search` / `memory_get` 工具。
- `openclaw memory ...` CLI。

这一层把“memory 是哪个实现”抽象为插件能力。`src/plugins/memory-state.ts` 只保存当前 memory capability，因此默认是 `memory-core`，但理论上可以由其他 memory 插件替换。

### 第 3 层：检索后端选择层

`getMemorySearchManager` 根据配置选择后端：

- `memory.backend` 未设置或不是 `qmd`：使用 builtin SQLite 后端。
- `memory.backend = "qmd"`：优先创建 `QmdMemoryManager`。
- 如果 QMD binary 不存在、初始化失败或运行失败：记录 warning，并 fallback 到 builtin。

这个 fallback 包装在 `FallbackMemoryManager` 中。QMD 第一次失败后，会关闭 primary、驱逐 cache，之后本次 manager 使用 builtin 搜索；下一次创建 manager 时还可以重新尝试 QMD。

### 第 4 层：内置 SQLite 索引层

默认 builtin 后端由 `MemoryIndexManager` 实现，索引通常存储在：

```text
~/.openclaw/memory/{agentId}.sqlite
```

SQLite schema 主要包括：

- `meta`：记录 provider/model/chunk 配置/FTS tokenizer/vector dims 等索引元数据。
- `files`：记录 path/source/hash/mtime/size。
- `chunks`：记录 chunk 文本、行号、model、embedding JSON。
- `embedding_cache`：可选，按 provider/model/providerKey/chunk hash 缓存 embedding。
- `chunks_fts`：FTS5 虚拟表，做 BM25/关键词搜索。
- `chunks_vec`：sqlite-vec 虚拟表，做向量搜索；不可用时退回进程内 cosine similarity。

这一层负责把 Markdown/session 文本变成可检索 chunk。

### 第 5 层：Embedding 与检索排序层

支持的 embedding provider 通过 adapter 注册，默认包括：

- `local`
- `openai`
- `gemini`
- `voyage`
- `mistral`
- `bedrock`
- `ollama`
- `lmstudio`

`provider: "auto"` 会按 adapter 的 `autoSelectPriority` 选择可用 provider。若没有 provider，builtin 不直接失效，而是进入 FTS-only 模式。

搜索时有三条路径：

- vector：把 query embedding 后查 `chunks_vec`，或者退回读取 `chunks.embedding` 后进程内 cosine。
- keyword：FTS5 + BM25，中文/日文/韩文可用 trigram tokenizer，并对短 CJK token 做 substring fallback。
- hybrid：按 `vectorWeight` 和 `textWeight` 合并，再可选 temporal decay 和 MMR。

### 第 6 层：运行时注入与工具层

模型看到 memory 的方式主要有两种：

- 被动工具：系统 prompt 要求模型在需要旧事实、偏好、日期、决策、todo 时调用 `memory_search`，再用 `memory_get` 拉取必要行。
- 主动插件：`active-memory` 在 `before_prompt_build` hook 中先跑一个 memory 子代理，把相关记忆总结成隐藏 system context 后再进入主回复。

此外，context engine 插件可以调用 `buildMemorySystemPromptAddition`，把 memory prompt section 接入自己的 context assembly。

### 第 7 层：整理、晋升与知识库层

短期记忆不是直接全部进入 `MEMORY.md`。`memory-core` 会记录召回信号，然后通过 promotion/dreaming 做筛选：

- `memory_search` 命中的短期文件会异步写入 `memory/.dreams/short-term-recall.json`。
- deep dreaming 或 `openclaw memory promote --apply` 会根据频率、相关性、查询多样性、recency、跨天 consolidation、concept tags 等打分。
- 通过阈值的候选才追加到 `MEMORY.md`。
- `memory-wiki` 可以作为旁路知识库，把 durable memory 编译为结构化 wiki、claims、evidence、dashboards 和 digest。

## 主数据流

### 1. 写入数据流

普通写入通常不是由 `memory-core` 直接硬编码完成，而是由 agent 根据系统提示和工具权限写 workspace 文件：

```text
用户说“记住 ...”
  -> agent 选择写入 MEMORY.md 或 memory/YYYY-MM-DD.md
  -> 文件变化被 watcher 捕获
  -> memory index 被标记 dirty 并重建/增量同步
```

有两类系统主动写入：

- pre-compaction flush：上下文快满时，运行一个静默 agentic turn，把还没落盘的重要上下文追加到 `memory/YYYY-MM-DD.md`。
- dreaming deep promotion：后台或 CLI 根据短期 recall store，把高分候选追加到 `MEMORY.md`。

### 2. Builtin 索引数据流

```text
MEMORY.md / memory/**/*.md / extraPaths / session transcripts
  -> listMemoryFiles / listSessionFilesForAgent
  -> buildFileEntry / buildSessionEntry
  -> chunkMarkdown
  -> embed chunks 或 FTS-only
  -> 写 files
  -> 写 chunks
  -> 写 chunks_fts
  -> 写 chunks_vec 或保留 JSON embedding
  -> 写 meta
```

关键处理：

- `chunkMarkdown` 约按 token budget 切块，默认文档描述为约 400 tokens、80 overlap；代码按配置换算成字符预算，并对 CJK-heavy 文本做更细切分。
- session JSONL 会先扁平化为文本，再用 `remapChunkLines` 把 chunk 行号映射回原 JSONL 行。
- 文件 hash 未变时跳过重建。
- provider/model/providerKey、chunk 配置、scope、FTS tokenizer 或 vector dims 变化时触发全量 reindex。
- 全量 reindex 默认使用临时 DB 构建成功后再原子替换，避免半成品索引污染生产 DB。

### 3. Builtin 查询数据流

```text
memory_search({ query })
  -> resolve agentId 和 memory config
  -> getMemorySearchManager
  -> MemoryIndexManager.search
  -> 若无索引，先同步一次
  -> keyword search + vector search
  -> hybrid merge
  -> temporal decay / MMR
  -> citations / max injected chars
  -> wiki supplement 可选合并
  -> 异步记录短期 recall 信号
  -> 返回 JSON
```

无 embedding provider 时：

- 仍然使用 FTS5。
- 若完整 AND 查询没结果，会提取关键词分别搜索。
- 开启 fallback lexical scoring，按 query-term 覆盖度、文本密度、路径命中、文本长度做轻量 boost。

这让 memory 在没有 API key 或 embedding provider 故障时仍能工作，只是语义召回能力下降。

### 4. QMD 查询数据流

QMD 后端把 OpenClaw 的 memory root、memory dir、extra paths、session export 映射为 QMD collections：

```text
memory.backend = "qmd"
  -> resolveMemoryBackendConfig
  -> QmdMemoryManager.initialize
  -> qmd collection add
  -> qmd update
  -> qmd embed
  -> memory_search
  -> qmd search / qmd vsearch / qmd query
  -> parseQmdQueryJson
  -> docid -> QMD index.sqlite documents 表解析路径
  -> 返回 MemorySearchResult
```

QMD 的实现细节：

- 每个 agent 有隔离的 QMD home：`~/.openclaw/agents/<agentId>/qmd/`。
- QMD 内部 index 位于该目录的 `xdg-cache/qmd/index.sqlite`。
- OpenClaw 只给 QMD 子进程设置 XDG 环境变量，不污染全局 `process.env`。
- collections 名称会带 agent 后缀，避免多 agent 冲突。
- 对旧 QMD CLI flag、collection list 输出、unsupported search flags 都有兼容 fallback。
- 搜索 scope 默认允许 direct/channel，拒绝 group，避免群聊意外注入私有记忆。
- 若 QMD 搜索或初始化失败，`FallbackMemoryManager` 切换到 builtin。

### 5. `memory_get` 读取数据流

`memory_get` 是安全读取，不是任意文件读取：

```text
memory_get({ path, from, lines })
  -> builtin: readAgentMemoryFile/readMemoryFile
  -> QMD: QmdMemoryManager.readFile
  -> 校验路径在允许范围内
  -> 只允许 .md
  -> 可按 from/lines 返回片段
```

Builtin 只允许：

- workspace 内 `MEMORY.md`、`memory.md`、`DREAMS.md`、`memory/**`
- 或配置的 `memorySearch.extraPaths` 中的 Markdown 文件/目录
- 忽略 symlink extra path

QMD 对 `qmd/<collection>/<path>` 虚拟路径做 collection root containment 检查，防止路径逃逸。

### 6. Active Memory 数据流

`active-memory` 是独立可选插件，不替代 `memory-core`。它在主回复前多跑一次小型 memory 子代理：

```text
before_prompt_build
  -> 检查 plugin enabled
  -> 检查 agent 是否在 config.agents
  -> 检查 session 是否 interactive persistent user turn
  -> 检查 chatType 是否允许
  -> buildQuery(message/recent/full)
  -> runEmbeddedPiAgent
       toolsAllow = ["memory_search", "memory_get"]
       silentExpected = true
       timeoutMs 有硬限制
  -> 子代理返回 NONE 或短摘要
  -> 主回复追加隐藏 system context
```

它的核心目的不是增加新存储，而是让 memory 从“主模型想起来才查”变成“回复前先给一次有限召回机会”。

防护点：

- 子代理只能使用 `memory_search` 和 `memory_get`。
- 默认不保留子代理 transcript，除非 `persistTranscripts` 打开。
- 有 session toggle：`/active-memory on|off|status`。
- summary 有长度上限和格式限制。
- 注入给主模型的 context 明确要求把 memory 当作不可信历史上下文，而不是指令。

### 7. Pre-compaction Flush 数据流

上下文接近 compaction 阈值时，`agent-runner-memory.ts` 会运行 memory flush：

```text
每次回复前估算 context window / token count / transcript size
  -> resolveMemoryFlushPlan
  -> 判断不是 heartbeat、不是 CLI provider、workspace 可写
  -> 判断接近阈值或 transcript 超过字节阈值
  -> runEmbeddedPiAgent 静默执行 flush prompt
  -> 要求追加到 memory/YYYY-MM-DD.md
  -> 保存 memoryFlushAt / memoryFlushCompactionCount 等元数据
  -> 后续 compaction 再总结
```

`flush-plan.ts` 的默认安全策略很明确：

- 只写 `memory/YYYY-MM-DD.md`。
- 已存在则 append-only。
- 不创建带小时分钟的变体文件。
- 把 `MEMORY.md`、`DREAMS.md`、`SOUL.md`、`TOOLS.md`、`AGENTS.md` 等 bootstrap/reference 文件视为只读。
- 无需用户可见回复时返回 `NO_REPLY`。

这个设计避免 compaction 把重要上下文压缩丢失。

## 核心处理细节

### 文件发现与路径处理

`listMemoryFiles` 默认扫描：

- `MEMORY.md`
- `memory.md`
- `memory/`
- `memorySearch.extraPaths`

处理规则：

- 默认只收 Markdown。
- extraPaths 可以是文件或目录。
- symlink 会被忽略。
- 重复 realpath 会 dedupe。
- multimodal 打开时，extraPaths 中的图片/音频也可被索引。

### Chunking

Markdown 按行聚合成 chunk：

- 用 `chunking.tokens * CHARS_PER_TOKEN_ESTIMATE` 得到字符预算。
- flush 后保留 overlap 行/字符，保证跨 chunk 连贯性。
- 对超长单行会先粗切，再按 token 预算细切。
- 对 CJK-heavy 文本用 `estimateStringChars` 近似更高 token 密度，避免 chunk 过大。

### Embedding 缓存和 batch

embedding 层做了几件事：

- 按 chunk hash 查 `embedding_cache`，命中则不重复请求 provider。
- 支持 OpenAI/Gemini/Voyage batch embedding。
- batch 失败有计数，达到阈值后禁用 batch，退回普通 embedding。
- embedding 调用有超时、重试、rate limit backoff。
- provider 失败且配置了 fallback 时，可以切换 fallback provider 并安全 reindex。

### FTS 与 CJK

FTS 默认 `unicode61`，也支持 `trigram`。

关键词搜索逻辑：

- 普通 tokenizer：把 query token quote 后用 AND 组合。
- trigram tokenizer：短 CJK token 不适合 trigram MATCH 时，转为 `LIKE` substring fallback。
- FTS-only 模式下不按 provider model 过滤，以便旧索引仍可用。

### Hybrid 排序

`mergeHybridResults` 做：

```text
score = vectorWeight * vectorScore + textWeight * textScore
```

然后可选：

- temporal decay：只衰减 dated daily memory 或有 mtime 的非 evergreen 内容；`MEMORY.md` 和非 dated memory topic 文件视为 evergreen。
- MMR：用 token/Jaccard similarity 做多样性重排，减少 top results 近重复。

### Citations 与注入长度

`memory_search` 会根据 `memory.citations` 决定是否给 snippet 装饰 `Source: <path#line>`。

QMD 后端还会按 `memory.qmd.limits.maxInjectedChars` 限制最终注入字符数，避免一次搜索把 prompt 撑爆。

### 短期 recall 信号

`memory_search` 返回后，`tools.ts` 会异步调用 `recordShortTermRecalls`。它只记录 `source === "memory"` 且路径属于短期记忆的结果：

- `memory/YYYY-MM-DD.md`
- `memory/.dreams/session-corpus/YYYY-MM-DD.md|txt`
- basename 为 `YYYY-MM-DD.md`

记录内容包括：

- path、startLine、endLine、snippet
- recallCount / dailyCount / groundedCount
- totalScore / maxScore
- queryHashes
- recallDays
- conceptTags
- claimHash
- promotedAt

写入文件：

```text
memory/.dreams/short-term-recall.json
memory/.dreams/phase-signals.json
memory/.dreams/events.jsonl
```

写入时有进程内 lock 和文件 lock，避免并发覆盖。

### Promotion 打分

短期候选晋升到长期记忆前会综合打分。默认权重：

- frequency：0.24
- relevance：0.30
- diversity：0.15
- recency：0.15
- consolidation：0.10
- conceptual：0.06

另外 light/REM phase signals 可提供小幅 boost。

候选要过阈值，默认文档和代码倾向是：

- 最低分数
- 最低 recall count
- 最低 unique queries
- 最大年龄

晋升时会重新读 live daily note，避免把已被用户编辑/删除的旧 snapshot 直接晋升。

### Dreaming

Dreaming 是可选后台整理系统，默认关闭。启用后 `memory-core` 管理一个 cron sweep，阶段是：

```text
light -> REM -> deep
```

职责大致是：

- light：整理/去重短期 recall material。
- REM：反思主题、生成可 review 的 diary/report。
- deep：把符合阈值的 durable facts 追加到 `MEMORY.md`。

只有 deep 写长期记忆。人类可读输出写到 `DREAMS.md` 或 `memory/dreaming/<phase>/YYYY-MM-DD.md`。

### Memory Wiki

`memory-wiki` 不是替代 `memory-core`，而是旁路知识层：

- active memory plugin 仍负责 recall、index、promotion、dreaming。
- wiki 负责 compiled pages、claims、evidence、dashboards、digest。
- `memory_search corpus=all` 可以聚合 memory 与 wiki supplement。
- `wiki_search` / `wiki_get` 用于需要 provenance、claim、page-level 结构的场景。

这说明 OpenClaw 将“原始记忆召回”和“整理后的知识库”分开处理。

### LanceDB 插件

`memory-lancedb` 是另一个 memory plugin：

- 用 LanceDB 存 `{id,text,vector,importance,category,createdAt}`。
- 用 OpenAI embeddings。
- 提供 `memory_recall`、`memory_store`、`memory_forget`。
- 可在 `before_agent_start` 自动召回并注入 `<relevant-memories>`。
- 可在 `agent_end` 从 user messages 里按规则捕获可记忆内容。

它与 `memory-core` 的风格不同：更像传统 vector long-term memory store，而 `memory-core` 更偏 file-backed、可审计、可检索的记忆系统。

## 配置入口

主要配置面：

- `plugins.slots.memory`：选择 active memory plugin slot，默认是 `memory-core`。
- `agents.defaults.memorySearch` / `agents.list[].memorySearch`：builtin search、embedding、chunking、extraPaths、session source 等配置。
- `memory.backend`：`builtin` 或 `qmd`。
- `memory.qmd.*`：QMD collections、update、limits、scope、sessions。
- `memory.citations`：`auto` / `on` / `off`。
- `plugins.entries.memory-core.config.dreaming`：dreaming 开关、频率、phase 设置。
- `plugins.entries.active-memory.config`：主动记忆插件的 agent、chat type、query mode、prompt style、timeout、transcript 等。

## 实现上的取舍

优点：

- 记忆源文件是 Markdown，可审计、可手改、可备份。
- 检索索引与源文件分离，索引坏了可以重建。
- builtin 后端无需外部服务，QMD 可选增强。
- 无 embedding provider 时仍有 FTS-only 降级。
- QMD 失败可回退 builtin。
- pre-compaction flush 解决长会话压缩前的信息落盘问题。
- dreaming/promotion 通过阈值控制长期记忆质量，避免所有短期噪声都进入 `MEMORY.md`。
- `memory_get` 和 QMD virtual path 都做了路径 containment 防护。

代价：

- 层次较多，理解需要同时看 plugin capability、tools、manager、host SDK、agent runner、dreaming。
- 记忆写入依赖 agent 行为和 prompt 约束，普通“记住”不是一个强事务 API。
- QMD 带来 sidecar 生命周期、collection 兼容、CLI timeout、embed lock 等复杂度。
- active-memory 会增加主回复前延迟，所以有 timeout/cache/eligibility gates。
- 短期 promotion 信号链路长，需要 `memory_search` 命中或 daily/grounded ingestion 才能形成晋升候选。

## 总结

OpenClaw 的 memory 是一个分层、可插拔、偏本地优先的记忆系统：

```text
Markdown source of truth
  -> memory-core capability
  -> builtin SQLite/QMD backend
  -> embedding + FTS + hybrid retrieval
  -> memory_search/memory_get tools
  -> active-memory/pre-compaction/context-engine 注入
  -> short-term recall signals
  -> dreaming/promotion
  -> MEMORY.md / memory-wiki durable knowledge
```

最核心的设计思想是：长期记忆必须落在可审计文件中；检索后端只是索引和召回加速层；真正写入长期记忆前要经过显式写文件、flush 或 promotion/dreaming 的筛选。

## 补充：Memory 到底怎么存、何时写、何时搜

这一节用更直白的方式回答几个实际问题：OpenClaw 的 memory 到底存在哪里，存储形式是什么，数据格式是什么，什么时候写入，什么时候搜索，以及搜索哪些文件。

### 1. Memory 的真正源数据存在哪里

OpenClaw memory 的“源数据”主要存为工作区里的普通文件，而不是存在模型内部。

默认工作区通常是某个 agent 的 workspace。核心文件是：

```text
<workspace>/
  MEMORY.md
  memory.md
  memory/
    2026-04-14.md
    2026-04-15.md
    ...
    .dreams/
      short-term-recall.json
      phase-signals.json
      events.jsonl
      session-corpus/
        2026-04-14.md
    dreaming/
      light/
      rem/
      deep/
  DREAMS.md
```

其中最重要的是：

- `MEMORY.md`：长期记忆。稳定事实、长期偏好、长期决策最终应该进入这里。
- `memory/YYYY-MM-DD.md`：每日短期记忆。会话中临时但可能有价值的事实通常先进入这里。
- `DREAMS.md`：dreaming、REM、backfill 的人类可读回顾报告。
- `memory/.dreams/*.json` / `events.jsonl`：机器用的短期信号、阶段信号和事件日志，不是主要给人直接编辑的长期记忆。

所以可以把它理解成：

```text
Markdown 文件 = 真实记忆源
SQLite/QMD/LanceDB = 为了搜索而建立的索引或替代存储
```

### 2. 存储形式是什么

OpenClaw 同时有几种存储形式，但默认主路径是 Markdown + SQLite 索引。

#### Markdown 源文件

`MEMORY.md`、`memory/YYYY-MM-DD.md`、`DREAMS.md` 都是普通 Markdown。

它们没有强制数据库 schema。也就是说，长期记忆不是一行一条的 rigid JSON，而是可读的 Markdown 文本。模型或者用户可以用标题、列表、段落组织内容。

示意：

```markdown
# Memory

## User Preferences

- User prefers TypeScript for backend examples.
- User likes concise implementation notes with concrete file references.

## Project Decisions

- OpenClaw memory should keep durable facts in Markdown and rebuild indexes from source files.
```

每日记忆通常类似：

```markdown
# 2026-04-14

## Session Notes

- User asked for a detailed analysis of OpenClaw memory implementation.
- Created MEMORY_IMPLEMENTATION_ANALYSIS.md in the repository root.
```

#### SQLite 索引

默认 builtin 后端会把 Markdown 切成 chunk，然后写入每个 agent 的 SQLite：

```text
~/.openclaw/memory/{agentId}.sqlite
```

这个 SQLite 不是 memory 的唯一真实来源，而是搜索索引。删掉它后理论上可以从 Markdown 重新构建。

主要表结构含义：

- `meta`：索引元数据，例如 provider、model、chunk 参数、FTS tokenizer、vector dims。
- `files`：每个被索引文件的 path、source、hash、mtime、size。
- `chunks`：每个文本 chunk 的 path、行号、text、embedding、model。
- `embedding_cache`：可选 embedding 缓存，避免同一 chunk 重复请求 provider。
- `chunks_fts`：FTS5 虚拟表，做关键词/BM25 搜索。
- `chunks_vec`：sqlite-vec 虚拟表，做向量相似度搜索。

一个 chunk 的逻辑数据大致是：

```json
{
  "id": "hash(source:path:startLine:endLine:chunkHash:model)",
  "path": "memory/2026-04-14.md",
  "source": "memory",
  "start_line": 12,
  "end_line": 25,
  "hash": "chunk-content-sha256",
  "model": "text-embedding-3-small",
  "text": "chunk text...",
  "embedding": "[0.012, -0.031, ...]",
  "updated_at": 1776123456789
}
```

#### QMD 索引

如果配置：

```json
{
  "memory": {
    "backend": "qmd"
  }
}
```

则会优先使用 QMD sidecar。QMD 的索引在：

```text
~/.openclaw/agents/<agentId>/qmd/
```

OpenClaw 会把 workspace memory 文件、extra paths、可选 session exports 映射成 QMD collections，然后调用：

```text
qmd collection add
qmd update
qmd embed
qmd search / qmd vsearch / qmd query
```

QMD 失败时会回退到 builtin SQLite。

#### 短期晋升信号 JSON

`memory_search` 命中每日短期记忆后，会异步记录“这条短期记忆被召回过”的信号，位置是：

```text
memory/.dreams/short-term-recall.json
```

格式大致是：

```json
{
  "version": 1,
  "updatedAt": "2026-04-14T00:00:00.000Z",
  "entries": {
    "memory:memory/2026-04-14.md:10:12:abc123": {
      "key": "memory:memory/2026-04-14.md:10:12:abc123",
      "path": "memory/2026-04-14.md",
      "startLine": 10,
      "endLine": 12,
      "source": "memory",
      "snippet": "User prefers TypeScript examples.",
      "recallCount": 3,
      "dailyCount": 0,
      "groundedCount": 0,
      "totalScore": 2.1,
      "maxScore": 0.86,
      "firstRecalledAt": "2026-04-14T00:00:00.000Z",
      "lastRecalledAt": "2026-04-14T01:00:00.000Z",
      "queryHashes": ["..."],
      "recallDays": ["2026-04-14"],
      "conceptTags": ["typescript", "preference"],
      "claimHash": "abc123"
    }
  }
}
```

这个 JSON 不直接给模型作为长期记忆使用，而是给 promotion/dreaming 判断“哪些短期内容值得进入 `MEMORY.md`”。

#### LanceDB 插件存储

如果使用 `memory-lancedb` 插件，它会把记忆存在 LanceDB 表里，格式大致是：

```ts
type MemoryEntry = {
  id: string;
  text: string;
  vector: number[];
  importance: number;
  category: "preference" | "fact" | "decision" | "entity" | "other";
  createdAt: number;
};
```

但这不是默认 `memory-core` 的主路径。默认主路径仍是 Markdown 源文件 + SQLite/QMD 搜索索引。

### 3. 什么时候会写入 memory

OpenClaw memory 的写入分几类。

#### 用户或 agent 显式要求记住时

典型场景：

```text
用户：记住我喜欢 TypeScript 示例。
```

此时主 agent 会根据系统提示，把内容写入合适的 memory 文件：

- 稳定长期事实：倾向写 `MEMORY.md`。
- 当天会话记录、临时上下文：倾向写 `memory/YYYY-MM-DD.md`。

注意：默认 `memory-core` 没有一个简单的 `memory_store` 工具来强制写入。写入通常是 agent 通过普通文件写能力完成的。因此这一步更像“agentic file write”，不是数据库 insert API。

#### 会话快要 compaction 前

这是 OpenClaw 一个很关键的生命周期。

当上下文快满、准备压缩历史时，`runMemoryFlushIfNeeded` 会判断是否需要 memory flush：

```text
主回复前
  -> 估算当前 token / context window / transcript size
  -> 如果接近 compaction 阈值
  -> 运行一个静默 memory flush turn
  -> 要求 agent 把重要信息追加到 memory/YYYY-MM-DD.md
  -> 再进行 compaction
```

默认 flush 的安全要求是：

- 只写 `memory/YYYY-MM-DD.md`。
- 已存在则只追加，不覆盖。
- 不写 `MEMORY.md`、`DREAMS.md`、`AGENTS.md`、`SOUL.md` 等参考文件。
- 如果没什么要保存，返回 `NO_REPLY`。

所以 compaction 前的写入目标主要是每日短期记忆，而不是直接长期记忆。

#### `memory_search` 之后记录短期召回信号

每次 `memory_search` 返回结果后，`tools.ts` 会异步调用 `recordShortTermRecalls`。

这一步不会改 `MEMORY.md`。它写的是机器信号：

```text
memory/.dreams/short-term-recall.json
memory/.dreams/events.jsonl
```

它记录哪些每日短期记忆被搜索命中过、命中过几次、分数多高、被哪些 query 召回过。后续 promotion/dreaming 会使用这些信号。

#### Dreaming / Promotion 时

当启用 dreaming，或手动运行：

```bash
openclaw memory promote --apply
```

系统会从 `memory/.dreams/short-term-recall.json` 里读取候选，按权重打分。通过阈值的内容才会追加到：

```text
MEMORY.md
```

也就是说：

```text
每日短期记忆
  -> 被搜索召回
  -> 形成短期信号
  -> promotion/dreaming 打分
  -> 通过阈值
  -> 追加到 MEMORY.md
```

这个设计避免 `MEMORY.md` 变成所有会话碎片的垃圾桶。

#### QMD session export 时

如果 QMD session indexing 开启，OpenClaw 会把 session transcript 导出成 Markdown 文件，再交给 QMD collection 索引。

导出位置通常在：

```text
~/.openclaw/agents/<agentId>/qmd/sessions/
```

这不是长期记忆源，而是为了让 QMD 能搜索历史会话。

### 4. 什么时候会 search

Search 发生在以下生命周期。

#### 模型主动调用 `memory_search`

默认 memory prompt 会告诉模型：

```text
如果要回答 prior work、decisions、dates、people、preferences、todos 等问题，
先调用 memory_search，再用 memory_get 拉取必要行。
```

所以在普通回复过程中，只要模型判断需要旧记忆，就会调用：

```text
memory_search({ query, maxResults?, minScore?, corpus? })
```

然后可能继续调用：

```text
memory_get({ path, from, lines })
```

#### Active Memory 主动搜索

如果启用了 `active-memory` 插件，它会在主回复前的 `before_prompt_build` 生命周期运行：

```text
before_prompt_build
  -> active-memory 判断当前 session 是否符合条件
  -> 构造 memory query
  -> 启动一个小型 memory 子代理
  -> 子代理只能用 memory_search / memory_get
  -> 返回 NONE 或短记忆摘要
  -> 摘要作为隐藏 system context 注入主回复
```

也就是说，active-memory 会让搜索发生在主模型正式回复之前。

#### CLI 搜索

用户也可以直接运行：

```bash
openclaw memory search "query"
```

这会走同一套 manager/search pipeline。

#### QMD 搜索前的更新

如果使用 QMD，搜索前可能会：

- 等待 pending update。
- 如果 dirty 且配置了 onSearch，则先 `qmd update`。
- 必要时触发 session-start warm sync。

#### Builtin 搜索前的同步

如果 builtin 后端发现还没有 indexed content，第一次搜索会先强制同步一次：

```text
search
  -> hasIndexedContent false
  -> sync({ reason: "search", force: true })
  -> 再搜索
```

这保证进程刚启动时第一次搜索不会因为后台 watcher 还没建好索引而直接空结果。

### 5. 搜索到底搜哪些文件

默认 builtin 后端搜索这些来源。

#### 默认 memory 文件

默认会索引并搜索：

```text
<workspace>/MEMORY.md
<workspace>/memory.md
<workspace>/memory/**/*.md
```

注意代码里是递归扫描 `memory/` 目录，不只是 `memory/*.md` 顶层文件。因此这些也可能被索引：

```text
memory/2026-04-14.md
memory/projects/foo.md
memory/dreaming/rem/2026-04-14.md
memory/.dreams/session-corpus/2026-04-14.md
```

但短期 promotion 记录 recall 信号时会过滤，只把 daily short-term 相关路径当成晋升候选；例如 `memory/dreaming/` 报告不会被当作普通短期 daily memory 晋升。

#### extraPaths

如果配置：

```json
{
  "agents": {
    "defaults": {
      "memorySearch": {
        "extraPaths": ["../team-docs", "/srv/shared-notes"]
      }
    }
  }
}
```

那么 builtin 会额外扫描这些路径：

- 如果是目录：递归扫描 Markdown。
- 如果是文件：只接受允许的文件，默认主要是 `.md`。
- symlink 会被忽略。
- multimodal 打开时，extraPaths 中符合条件的图片/音频也能被索引。

#### session transcripts

session memory 是可选的。只有配置开启后，才会把历史 session transcript 作为搜索源。

相关配置大意是：

```json
{
  "agents": {
    "defaults": {
      "memorySearch": {
        "experimental": {
          "sessionMemory": true
        },
        "sources": ["memory", "sessions"]
      }
    }
  }
}
```

开启后，搜索来源就包括：

```text
source = memory
source = sessions
```

session JSONL 会被转换成可索引文本，chunk 行号会映射回原 transcript 行号。

#### QMD backend 搜索范围

QMD 默认 collections 包括：

```text
workspace/MEMORY.md
workspace/memory/**/*.md
```

再加上：

- `memory.qmd.paths`
- `memorySearch.extraPaths`
- `memorySearch.qmd.extraCollections`
- 可选 session export collection

QMD 结果返回时，OpenClaw 会把 QMD docid 映射回：

- workspace 相对路径，例如 `memory/2026-04-14.md`
- 或虚拟路径，例如 `qmd/<collection>/<relative-path>`

后者可以继续被 `memory_get` 安全读取。

### 6. 具体怎么 search

Builtin 搜索逻辑可以拆成 5 步。

#### 第一步：确保索引可用

`memory_search` 先拿到当前 agent 的 manager。如果索引为空或 dirty，会触发同步。

同步会做：

```text
扫描文件
  -> 判断 hash 是否变化
  -> 变化的文件重新 chunk
  -> 重新写 chunks / FTS / vector
  -> 删除已不存在文件的旧索引
```

#### 第二步：关键词搜索

关键词路径使用 SQLite FTS5：

```text
query
  -> token 化
  -> 构造 FTS MATCH query
  -> bm25(chunks_fts)
  -> 转成 textScore
```

它适合：

- 精确术语
- 文件名
- ID
- 配置 key
- 人名
- 日期
- 错误字符串

#### 第三步：向量搜索

如果 embedding provider 可用：

```text
query
  -> embedQuery
  -> sqlite-vec 查 chunks_vec
  -> 或退回进程内 cosineSimilarity
```

它适合：

- 同义表达
- 用户用不同措辞问旧事实
- 宽泛语义匹配

#### 第四步：Hybrid 合并

如果 hybrid 打开，OpenClaw 会合并两路结果：

```text
score = vectorWeight * vectorScore + textWeight * textScore
```

默认思想是：

- 向量负责“意思像不像”。
- FTS 负责“关键词准不准”。

还可以加：

- temporal decay：旧 daily note 分数变低，`MEMORY.md` 不衰减。
- MMR：减少重复结果，提升多样性。

#### 第五步：装饰和返回

最后：

- 根据 `memory.citations` 决定是否附 `Source: path#line`。
- QMD 后端会按 maxInjectedChars 裁剪注入字符。
- 如果 `corpus=wiki` 或 `corpus=all`，会合并 `memory-wiki` supplement 结果。
- 返回 JSON 给模型。

返回结构大致是：

```json
{
  "results": [
    {
      "path": "memory/2026-04-14.md",
      "startLine": 10,
      "endLine": 14,
      "score": 0.82,
      "snippet": "User prefers TypeScript examples.",
      "source": "memory",
      "corpus": "memory"
    }
  ],
  "provider": "openai",
  "model": "text-embedding-3-small",
  "citations": "auto",
  "mode": "n/a",
  "debug": {
    "backend": "builtin",
    "searchMs": 123,
    "hits": 1
  }
}
```

### 7. 一个完整例子

假设用户说：

```text
记住我以后要 TypeScript 示例。
```

可能发生：

```text
agent 写入 memory/2026-04-14.md
  -> watcher 发现文件变化
  -> builtin SQLite 重新索引该文件
  -> chunk 写入 chunks
  -> 文本写入 chunks_fts
  -> embedding 写入 chunks / chunks_vec
```

几天后用户问：

```text
你还记得我喜欢什么代码示例风格吗？
```

可能发生：

```text
主模型看到 memory prompt
  -> 调用 memory_search("喜欢什么代码示例风格")
  -> builtin 同时做 FTS 和 vector search
  -> 找到 memory/2026-04-14.md 相关 chunk
  -> 返回 path、line、snippet、score
  -> 异步记录 short-term recall 信号
  -> 模型调用 memory_get 拉取必要行
  -> 模型回答用户
```

如果这条记忆后来经常被召回：

```text
short-term-recall.json 中 recallCount 增长
  -> dreaming/deep promotion 计算分数
  -> 通过阈值
  -> 追加到 MEMORY.md
```

这就是 OpenClaw memory 的核心闭环：

```text
写入 Markdown
  -> 建索引
  -> 搜索召回
  -> 记录召回信号
  -> 晋升长期记忆
  -> 后续更稳定地召回
```

## 再补充：写入到底从哪里提取、怎么处理、写到哪里

上一节讲了什么时候写。这里把“写入链路”拆得更明确一点。

OpenClaw 里至少有 6 种不同意义的“写入”：

1. agent 主动把对话内容写入 Markdown 记忆文件。
2. compaction 前从会话上下文提取重要信息，追加到每日记忆。
3. indexing 从 Markdown/session 文件提取 chunk，写入 SQLite/QMD 索引。
4. `memory_search` 后把召回结果写成短期晋升信号。
5. dreaming/promotion 从短期信号和每日记忆里提取候选，追加到 `MEMORY.md`。
6. QMD session memory 从 session JSONL 导出 Markdown，供 QMD 搜索。

它们的来源、处理、目标文件并不一样。

### 0. 按生命周期看：什么时候写入、什么时候搜索、什么时候晋升

先把结论说清楚：OpenClaw 的 memory 不是一个“每轮对话结束后统一保存”的模块。它拆成了几个独立生命周期：

1. 主回复前的 runner 前置阶段：检查是否需要 compaction 和 memory flush。
2. prompt 构建前阶段：`active-memory` 可以提前搜索，并把相关记忆注入系统上下文。
3. 主 agent 正常工具循环：模型按需调用 `memory_search` / `memory_get`，也可能用普通文件写能力写 Markdown memory。
4. `memory_search` 之后的召回跟踪阶段：搜索命中的短期记忆会被记录成 promotion 信号。
5. 索引同步阶段：Markdown / session 文件变化后，更新 SQLite 或 QMD 索引。
6. dreaming / deep promotion 阶段：把多次被召回、分数足够高的短期记忆晋升到 `MEMORY.md`。
7. CLI / 手工维护阶段：用户手动执行 `openclaw memory search`、`openclaw memory promote --apply` 等命令。

它们之间的关系可以这样理解：

```text
写入 daily memory
  不等于 search
  不等于 promotion

search
  会读取索引和 memory 文件
  可能顺手写一条 short-term recall 信号
  但不会立刻把内容写进 MEMORY.md

promotion
  是后续单独生命周期
  读取 short-term recall 信号和 live daily note
  通过阈值后才追加到 MEMORY.md
```

#### 生命周期总表

| 生命周期                         | 触发时机                                                 | 是否写入 memory                                                         | 是否搜索 memory                                                                | 是否晋升                             | 关键代码                                                            |
| -------------------------------- | -------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------ | ------------------------------------------------------------------- |
| 插件初始化                       | OpenClaw 启动、加载 `memory-core` 插件                   | 不直接写用户记忆，只注册工具和配置                                      | 不搜索                                                                         | 不晋升，只可能注册 dreaming 定时任务 | `extensions/memory-core/index.ts`                                   |
| 主回复前 runner 前置阶段         | 收到一轮用户消息后，真正跑主 agent 之前                  | 可能写：触发 memory flush 时追加 `memory/YYYY-MM-DD.md`                 | flush run 本身不使用 `memory_search`，只允许 `read` / `write`                  | 不晋升                               | `src/auto-reply/reply/agent-runner.ts`、`agent-runner-memory.ts`    |
| Prompt 构建前 active-memory 阶段 | 构建主模型 prompt 前的 `before_prompt_build` hook        | 不写 memory 文件                                                        | 可能搜索：启用且会话合格时，启动静默子 agent 调 `memory_search` / `memory_get` | 不晋升                               | `extensions/active-memory/index.ts`                                 |
| 主 agent 工具循环                | 主模型开始处理用户请求之后                               | 可能写：用户要求“记住”或模型判断需要持久化时，用普通文件工具写 Markdown | 可能搜索：模型按系统提示或任务需要调用 `memory_search` / `memory_get`          | 不晋升                               | `extensions/memory-core/src/tools.ts`、普通文件工具                 |
| `memory_search` 执行后           | 每次 `memory_search` 返回结果后                          | 写的是召回信号，不是正式记忆：`memory/.dreams/short-term-recall.json`   | 已经完成一次搜索                                                               | 不晋升，只累积晋升候选的证据         | `extensions/memory-core/src/tools.ts`、`short-term-promotion.ts`    |
| 索引同步                         | memory 文件变更、索引 dirty、搜索前需要同步、CLI reindex | 写搜索索引，不写用户可读 memory                                         | 不算模型搜索，是为后续搜索准备索引                                             | 不晋升                               | `extensions/memory-core/src/memory/*`、QMD runtime                  |
| Dreaming light / REM             | 定时任务、heartbeat、CLI preview/backfill                | 可能写 dream report、phase signal、grounded candidate                   | 主要做整理和候选增强，不是主对话搜索                                           | 不直接写 `MEMORY.md`                 | `extensions/memory-core/src/dreaming-phases.ts`                     |
| Dreaming deep promotion          | managed dreaming heartbeat 或 CLI apply                  | 写长期记忆：追加 `MEMORY.md`                                            | 不走普通 `memory_search` 路径，而是读 short-term store 和 live source files    | 是，真正晋升发生在这里               | `extensions/memory-core/src/dreaming.ts`、`short-term-promotion.ts` |
| CLI 手工操作                     | 用户运行 `openclaw memory ...`                           | `promote --apply` 会写 `MEMORY.md`；其他命令可能只读或修复元数据        | `search` 命令会搜索                                                            | `promote --apply` 会晋升             | `extensions/memory-core/src/cli.runtime.ts`                         |

#### 一轮普通回复里，memory 生命周期的实际顺序

对普通聊天来说，顺序大致是：

```text
用户消息进入
  -> agent-runner.ts: runPreflightCompactionIfNeeded
  -> agent-runner.ts: runMemoryFlushIfNeeded
       如果 token / transcript size 达到条件：
         phase = memory_flushing
         启动静默 embedded agent
         trigger = "memory"
         只允许 read / write
         write 被限制为 append 到 memory/YYYY-MM-DD.md
         记录 memoryFlushAt / memoryFlushCompactionCount
  -> 构建主模型 prompt
  -> active-memory 的 before_prompt_build hook 可能先搜索
       子 agent 只允许 memory_search / memory_get
       搜到的摘要作为 supplemental context 注入主 prompt
  -> 主 agent 开始回答
       需要回忆时调用 memory_search
       需要原文时调用 memory_get
       需要保存时用文件写能力写 MEMORY.md 或 memory/YYYY-MM-DD.md
  -> memory_search 命中的短期 daily memory 被异步记录到 short-term-recall.json
  -> 本轮回答结束
```

注意两个边界：

1. `runMemoryFlushIfNeeded` 在主回复前执行，不是在主回复完成后执行。它的目的不是保存“刚刚生成的回答”，而是在上下文接近压缩或 transcript 过大时，先把已有会话上下文提炼到 daily memory。
2. `memory_search` 只发生在 active-memory 子 agent 或主 agent 显式调用搜索工具时。系统不会在每一轮都无条件搜索，除非 active-memory 配置开启且当前会话满足条件。

#### 什么时候会写入

OpenClaw 里“写入”至少有四类，要分开看：

第一类是正式记忆写入：

```text
触发：
  用户明确说“记住”
  或主 agent 判断某个偏好/事实/项目状态值得保存

生命周期：
  主 agent 正常工具循环中

来源：
  当前用户消息
  当前会话上下文
  已经检索到的相关 memory

处理：
  模型判断写长期还是短期
  组织成 Markdown bullet / section

目标：
  长期稳定事实 -> MEMORY.md
  当天上下文 / 暂存事实 -> memory/YYYY-MM-DD.md
```

第二类是 memory flush 写入：

```text
触发：
  主回复前 runMemoryFlushIfNeeded 检查通过

条件：
  非 heartbeat
  非 CLI provider
  当前 sandbox 可写
  token count 达到 contextWindow - reserveTokensFloor - softThresholdTokens
  或 transcript byte size 超过 forceFlushTranscriptBytes
  且当前 compactionCount 下尚未 flush 过

生命周期：
  主回复前 runner 前置阶段
  reply phase 会被设置为 memory_flushing

来源：
  session transcript
  当前 prompt
  最近 usage / token snapshot
  session metadata

处理：
  静默 embedded agent 读取上下文
  只抽取 durable / salient 信息
  遵守 append-only 规则
  文件工具层把 write 限制到 memory/YYYY-MM-DD.md

目标：
  memory/YYYY-MM-DD.md

额外状态：
  session store 写入 memoryFlushAt
  session store 写入 memoryFlushCompactionCount
```

第三类是搜索后的召回信号写入：

```text
触发：
  memory_search 返回结果后

生命周期：
  memory_search tool execution 的收尾阶段

来源：
  memory_search 的 rawResults / surfacedResults

处理：
  只保留 source = memory
  只保留短期路径：memory/YYYY-MM-DD.md 或 memory/.dreams/session-corpus/YYYY-MM-DD.md
  排除 memory/dreaming/ 下的 dream report
  生成 key、claimHash、queryHash
  更新 recallCount / dailyCount / groundedCount
  更新 totalScore / maxScore
  更新 recallDays / conceptTags / firstRecalledAt / lastRecalledAt

目标：
  memory/.dreams/short-term-recall.json

含义：
  这是“将来可能晋升”的证据，不是正式长期记忆。
```

第四类是索引写入：

```text
触发：
  memory 文件变化
  session export 变化
  index dirty
  搜索前发现需要同步
  CLI reindex / status --index

生命周期：
  indexing / sync 生命周期

来源：
  MEMORY.md
  memory.md
  memory/**/*.md
  memorySearch.extraPaths
  可选 session transcripts
  QMD session export Markdown

处理：
  chunk
  hash
  embedding
  FTS / vector index
  QMD collection update

目标：
  builtin: ~/.openclaw/memory/{agentId}.sqlite
  QMD: ~/.openclaw/agents/<agentId>/qmd/.../index.sqlite

含义：
  这是检索加速结构，不是新的用户可读 memory 内容。
```

#### 什么时候会搜索

搜索主要有三种入口。

第一种是 active-memory 自动预搜索：

```text
触发：
  before_prompt_build hook
  active-memory 插件启用
  当前 session 未禁用 active-memory
  当前会话是 eligible interactive session
  chat type 被允许

处理：
  根据 latestUserMessage + recentTurns 构造 query
  启动静默 active-memory 子 agent
  子 agent 只允许 memory_search / memory_get
  子 agent 返回最相关摘要或 NONE

结果：
  有摘要时，注入主 prompt：
    prependSystemContext = ACTIVE_MEMORY_PLUGIN_GUIDANCE
    appendSystemContext = <active-memory>...</active-memory>
```

第二种是主 agent 按需搜索：

```text
触发：
  主模型在回答中判断需要回忆历史事实、偏好、todo、决策、日期、之前工作

处理：
  调用 memory_search(query, maxResults, minScore, corpus)
  根据结果 path / line / snippet / score 判断是否需要 memory_get
  memory_get 只读取指定 path 的必要行

结果：
  搜索结果进入当前工具结果上下文
  命中的短期 memory 会异步记录 short-term recall 信号
```

第三种是 CLI 搜索：

```text
触发：
  用户运行 openclaw memory search ...

处理：
  走 memory manager / backend search
  输出搜索结果

结果：
  用于人工检查
  也会 best-effort 调用 recordShortTermRecalls 写 short-term recall 信号
```

`memory_search` 搜哪些文件，取决于 backend 和配置，但核心集合是：

```text
MEMORY.md
memory.md
memory/**/*.md
memorySearch.extraPaths
可选 indexed session transcripts
可选 wiki / compiled-wiki supplements（corpus=wiki 或 corpus=all）
```

在 builtin backend 下，会走内置 SQLite 的 FTS / vector 检索；在 QMD backend 下，会走 QMD collection / index 检索。无论哪种 backend，工具返回给模型的都是结构化结果：

```text
path
startLine
endLine
snippet
score
source
```

#### 什么时候会晋升

晋升不是普通写入，也不是搜索当场发生。它只在 promotion 生命周期里发生。

晋升触发主要有两个：

```text
自动：
  managed dreaming heartbeat / cron
  deep phase 执行 durable promotion

手动：
  openclaw memory promote --apply
```

晋升的数据流是：

```text
memory/.dreams/short-term-recall.json
  -> rankShortTermPromotionCandidates
  -> 按分数和阈值筛选候选
  -> rehydratePromotionCandidate 重新读取 live memory/YYYY-MM-DD.md
  -> 确认 snippet 仍存在或能重定位
  -> applyShortTermPromotions
  -> 追加到 MEMORY.md
  -> 给候选写 promotedAt
```

默认晋升门槛来自 `short-term-promotion.ts`：

```text
minScore 默认 0.75
minRecallCount 默认 3
minUniqueQueries 默认 2
recencyHalfLifeDays 默认 14
```

打分会综合：

```text
frequency       被召回/日常/grounded 信号次数
relevance       平均搜索分数
diversity       queryHashes 或 recallDays 的多样性
recency         最近一次召回距离现在有多近
consolidation   跨天巩固程度或 groundedCount
conceptual      conceptTags 覆盖
phase boost     light / REM dreaming 反复命中的增强信号
```

真正写入 `MEMORY.md` 之前，还会做一个很关键的保护：

```text
短期 store 里保存的是旧 snapshot
  -> promotion 不直接相信它
  -> 会重新读取 live daily note
  -> 如果原 snippet 已不存在且无法重定位，就跳过
```

写入 `MEMORY.md` 的格式带有 promotion marker，便于去重和后续识别：

```markdown
## Promoted From Short-Term Memory (YYYY-MM-DD)

<!-- openclaw-memory-promotion:<candidate-key> -->

- <snippet> [score=... recalls=... avg=... source=memory/YYYY-MM-DD.md:line-line]
```

所以晋升可以总结成一句话：

```text
不是“写入 daily memory 后自动进 MEMORY.md”，
而是“被多次搜索召回 / dreaming 强化 / 达到阈值 / live 文本仍存在”之后，
才在 deep promotion 或 promote --apply 生命周期中追加到 MEMORY.md。
```

### 1. 用户说“记住”时：从当前对话提取，写入 Markdown

这是最直观的写入。

```text
来源：
  当前用户消息 + 当前会话上下文

处理：
  主 agent 根据系统 prompt 判断哪些内容值得保存
  判断是长期事实还是当天短期记录
  通过普通文件写能力编辑 memory 文件

写入目标：
  长期稳定事实 -> MEMORY.md
  当天会话记录 -> memory/YYYY-MM-DD.md
```

注意，这条路径不是 `memory-core` 直接执行一个数据库 insert。默认 `memory-core` 没有 `memory_store` 工具。它提供的是 prompt 指导和搜索工具，真正的 Markdown 写入通常由 agent 的文件编辑能力完成。

举例：

```text
用户：记住我以后想要 TypeScript 示例。
```

可能写入：

```text
memory/2026-04-14.md
```

内容可能是：

```markdown
- User prefers TypeScript examples for future code explanations.
```

如果 agent 判断这是稳定长期偏好，也可能写入：

```text
MEMORY.md
```

### 2. Compaction 前 flush：从 session transcript/会话上下文提取，写入每日记忆

这是更自动化的一条写入路径。

触发点在主回复前，代码路径是：

```text
src/auto-reply/reply/agent-runner-memory.ts
  -> runMemoryFlushIfNeeded
extensions/memory-core/src/flush-plan.ts
  -> buildMemoryFlushPlan
```

数据流：

```text
来源：
  当前持久会话 transcript
  当前 prompt
  最近 token usage / transcript size / session metadata

处理：
  判断上下文是否接近 compaction 阈值
  判断 transcript 是否超过强制 flush 字节阈值
  启动一个静默 embedded agent run
  给 agent 注入 memory flush prompt
  要求它只提取 durable / salient context
  要求 append-only

写入目标：
  memory/YYYY-MM-DD.md
```

默认 flush prompt 明确要求：

```text
只写 memory/YYYY-MM-DD.md
如果文件存在，只追加
不要覆盖
不要写 MEMORY.md / DREAMS.md / SOUL.md / TOOLS.md / AGENTS.md
没东西保存就返回 NO_REPLY
```

所以这条链路可以总结成：

```text
session transcript / 当前上下文
  -> 静默 memory flush agent 提取重要信息
  -> append 到 memory/当天日期.md
```

它不是直接把整段 transcript 塞进 memory，而是让 agent 做一次抽取和压缩。

### 3. Builtin indexing：从 memory 文件/session 文件提取，写入 SQLite 索引

这条链路不是写“真实记忆”，而是写“搜索索引”。

代码路径主要是：

```text
extensions/memory-core/src/memory/manager-sync-ops.ts
extensions/memory-core/src/memory/manager-embedding-ops.ts
src/memory-host-sdk/host/internal.ts
src/memory-host-sdk/host/memory-schema.ts
```

数据流：

```text
来源文件：
  MEMORY.md
  memory.md
  memory/**/*.md
  memorySearch.extraPaths 中的 Markdown
  可选 session transcripts
  可选 multimodal extraPaths 文件

处理：
  扫描文件
  忽略 symlink
  去重 realpath
  读取文件 hash / mtime / size
  Markdown 按 chunking.tokens 和 overlap 切块
  session JSONL 先转换为文本，再 remap 行号
  有 embedding provider 时生成 embedding
  无 provider 时进入 FTS-only
  写 FTS5 关键词索引
  写 sqlite-vec 向量索引，或退回 JSON embedding

写入目标：
  ~/.openclaw/memory/{agentId}.sqlite
```

SQLite 内部大致写入这些表：

```text
files
chunks
chunks_fts
chunks_vec
embedding_cache
meta
```

所以这条链路是：

```text
Markdown/session 源文件
  -> chunk
  -> embedding/FTS
  -> SQLite 搜索索引
```

重要点：SQLite 里的内容是索引副本。真正可编辑、可审计的源仍然是 Markdown。

### 4. QMD indexing：从 memory 文件/extra paths/session export 提取，写入 QMD 索引

如果 `memory.backend = "qmd"`，优先走 QMD。

代码路径：

```text
extensions/memory-core/src/memory/qmd-manager.ts
src/memory-host-sdk/host/backend-config.ts
src/memory-host-sdk/host/qmd-process.ts
```

数据流：

```text
来源：
  workspace/MEMORY.md
  workspace/memory/**/*.md
  memory.qmd.paths
  memorySearch.extraPaths
  memorySearch.qmd.extraCollections
  可选 QMD session export Markdown

处理：
  为每类来源创建 QMD collection
  qmd collection add
  qmd update
  qmd embed
  必要时修复 collection 冲突、旧版 flag、重复 document、null-byte metadata 等问题

写入目标：
  ~/.openclaw/agents/<agentId>/qmd/xdg-cache/qmd/index.sqlite
```

如果 QMD session indexing 开启，还会先有一条导出链路：

```text
来源：
  agent session JSONL transcripts

处理：
  buildSessionEntry 读取 transcript
  转成简化 Markdown
  做 retention 过滤

写入目标：
  ~/.openclaw/agents/<agentId>/qmd/sessions/<session>.md
```

然后 QMD 再索引这些导出的 Markdown。

### 5. `memory_search` 后：从搜索结果提取，写入短期 recall 信号

这条写入很容易被忽略。它不会写长期记忆，而是写“哪些短期记忆被反复用到”的统计信号。

代码路径：

```text
extensions/memory-core/src/tools.ts
  -> queueShortTermRecallTracking
extensions/memory-core/src/short-term-promotion.ts
  -> recordShortTermRecalls
```

数据流：

```text
来源：
  memory_search 返回的 rawResults / surfacedResults

过滤：
  只接受 source === "memory"
  只接受短期 memory 路径
  例如 memory/YYYY-MM-DD.md
  排除 memory/dreaming/ 这类 dreaming 报告路径

处理：
  标准化 path
  标准化 snippet
  计算 claimHash
  计算 queryHash
  更新 recallCount / totalScore / maxScore
  更新 recallDays / queryHashes / conceptTags
  记录 memory.recall.recorded 事件

写入目标：
  memory/.dreams/short-term-recall.json
  memory/.dreams/events.jsonl
```

链路是：

```text
memory_search 命中的每日短期记忆 snippet
  -> 过滤短期路径
  -> 统计召回次数、分数、query 多样性、日期
  -> 写 memory/.dreams/short-term-recall.json
```

这一步是后续 promotion 的基础。

### 6. Daily ingestion / grounded backfill：从历史每日文件提取，写入短期候选或 DREAMS.md

Dreaming 相关代码还会从历史 Markdown 中提取候选。

代码路径：

```text
extensions/memory-core/src/dreaming-phases.ts
extensions/memory-core/src/rem-evidence.ts
extensions/memory-core/src/short-term-promotion.ts
```

常见来源：

```text
memory/YYYY-MM-DD.md
memory/.dreams/session-corpus/YYYY-MM-DD.md
用户通过 rem-backfill --path 指定的历史 Markdown 文件或目录
```

处理：

```text
解析 Markdown section
提取 list / paragraph snippet
过滤太泛、太弱、太像临时日志的内容
生成 grounded durable candidates
可选写入 short-term recall store
生成人类可读 REM/backfill 报告
```

写入目标：

```text
DREAMS.md
memory/.dreams/short-term-recall.json
memory/.dreams/phase-signals.json
memory/dreaming/<phase>/YYYY-MM-DD.md
```

其中 `DREAMS.md` 是 review surface，`short-term-recall.json` 是机器 ranking surface。

### 7. Deep promotion：从短期 recall store 和 live daily note 提取，写入 MEMORY.md

这是真正把短期内容升级为长期记忆的路径。

代码路径：

```text
extensions/memory-core/src/dreaming.ts
extensions/memory-core/src/dreaming-phases.ts
extensions/memory-core/src/short-term-promotion.ts
```

数据流：

```text
来源：
  memory/.dreams/short-term-recall.json
  memory/.dreams/phase-signals.json
  live memory/YYYY-MM-DD.md

处理：
  读取短期候选
  按 recallCount / avgScore / maxScore / uniqueQueries / recallDays / conceptTags 打分
  加入 recency、consolidation、conceptual、phase boost
  过滤已 promoted 或低分候选
  重新读取 live daily note
  确认 snippet 仍然存在或仍可 reconcile
  追加 promotion marker

写入目标：
  MEMORY.md
```

这条链路尤其重要：promotion 不是直接相信旧 JSON snapshot，而是会重新读当前 Markdown，避免用户后来已经删除或修改的内容被晋升。

简化成一句：

```text
short-term-recall.json 负责告诉系统“哪些候选值得考虑”
memory/YYYY-MM-DD.md 负责提供当前真实文本
MEMORY.md 才是最终长期写入目标
```

### 8. 写入链路总表

| 写入类型                 | 从哪里提取                                          | 主要处理                                           | 写到哪里                                            |
| ------------------------ | --------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------- |
| 显式记忆                 | 当前用户消息、当前会话上下文                        | agent 判断长期/短期，生成 Markdown                 | `MEMORY.md` 或 `memory/YYYY-MM-DD.md`               |
| Pre-compaction flush     | session transcript、当前 prompt、会话上下文         | 静默 agent 抽取 durable context，append-only       | `memory/YYYY-MM-DD.md`                              |
| Builtin index            | `MEMORY.md`、`memory/**/*.md`、extraPaths、sessions | chunk、hash、embedding、FTS、vector                | `~/.openclaw/memory/{agentId}.sqlite`               |
| QMD index                | memory roots、extra collections、session exports    | collection、`qmd update`、`qmd embed`              | `~/.openclaw/agents/<agentId>/qmd/.../index.sqlite` |
| Recall tracking          | `memory_search` 命中的短期 memory result            | 记录 recallCount、score、queryHash、conceptTags    | `memory/.dreams/short-term-recall.json`             |
| Daily/backfill ingestion | 历史 `memory/YYYY-MM-DD.md` 或指定 Markdown         | section/snippet 提取、grounded candidate、REM 报告 | `DREAMS.md`、`.dreams/*.json`                       |
| Deep promotion           | short-term store + live daily note                  | 打分、阈值、重新校验 live text、去重/标记          | `MEMORY.md`                                         |
| QMD session export       | session JSONL transcript                            | 转 Markdown、retention、collection 化              | `~/.openclaw/agents/<agentId>/qmd/sessions/*.md`    |

### 9. 最关键的理解

OpenClaw 不是把所有对话都直接写进长期记忆。

它更像一个分阶段管道：

```text
当前对话
  -> 显式记忆或 compaction flush
  -> memory/YYYY-MM-DD.md
  -> 被搜索召回后形成 short-term recall 信号
  -> dreaming/promotion 打分
  -> 通过阈值后进入 MEMORY.md
  -> SQLite/QMD 从这些文件重建搜索索引
```

所以回答“写入是从什么文件提取，经过什么处理，写入到什么文件”时，最核心的三条是：

```text
会话上下文/transcript
  -> agent 抽取
  -> memory/YYYY-MM-DD.md

memory/YYYY-MM-DD.md + search recall 信号
  -> promotion/dreaming 打分与校验
  -> MEMORY.md

MEMORY.md + memory/**/*.md + extraPaths + sessions
  -> chunk / embedding / FTS / vector
  -> SQLite 或 QMD 索引
```
