# @openclaw/memory-wiki

面向 **OpenClaw** 的持久化 Wiki 编译器，以及对 Obsidian 友好的知识库。

这个插件独立于活动记忆插件。活动记忆插件仍然负责召回、提升和 dreaming。`memory-wiki` 会将持久知识编译成一个可导航的 Markdown 知识库，其中包含确定性的索引、来源信息、结构化的声明/证据元数据，以及可选的 Obsidian CLI 工作流。

当活动记忆插件暴露共享召回能力时，智能体可以使用 `memory_search` 并设置 `corpus=all`，一次性搜索持久记忆和已编译的 Wiki；当需要 Wiki 特定的排序或来源信息时，再回退到 `wiki_search` / `wiki_get`。

## 模式

- `isolated`：拥有自己的知识库、自己的来源，不依赖 `memory-core`
- `bridge`：通过公开接口读取公共记忆产物和记忆事件
- `unsafe-local`：显式的同机逃生通道，用于访问私有本地路径

默认模式是 `isolated`。

## 配置

将配置放在 `plugins.entries.memory-wiki.config` 下：

```json5
{
  vaultMode: "isolated",

  vault: {
    path: "~/.openclaw/wiki/main",
    renderMode: "obsidian", // 或 "native"
  },

  obsidian: {
    enabled: true,
    useOfficialCli: true,
    vaultName: "OpenClaw Wiki",
    openAfterWrites: false,
  },

  bridge: {
    enabled: false,
    readMemoryArtifacts: true,
    indexDreamReports: true,
    indexDailyNotes: true,
    indexMemoryRoot: true,
    followMemoryEvents: true,
  },

  unsafeLocal: {
    allowPrivateMemoryCoreAccess: false,
    paths: [],
  },

  ingest: {
    autoCompile: true,
    maxConcurrentJobs: 1,
    allowUrlIngest: true,
  },

  search: {
    backend: "shared", // 或 "local"
    corpus: "wiki", // 或 "memory" | "all"
  },

  context: {
    includeCompiledDigestPrompt: false, // 选择启用后，会将紧凑的已编译摘要快照附加到记忆提示词部分
  },

  render: {
    preserveHumanBlocks: true,
    createBacklinks: true, // 写入托管的 ## Related 区块，其中包含来源、反向链接和相关页面
    createDashboards: true,
  },
}
