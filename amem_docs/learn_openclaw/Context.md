# OpenClaw Context 实现解析

本文聚焦 `openclaw-main` 中 **context 如何被构造、组织、选取、处理、进入模型、压缩和观测**。这里的 context 不是一个单独长期保存的大对象，而是每次模型运行前由运行时临时组装出来的“模型可见输入包”。

## 1. 一句话总览

OpenClaw 的 context = **system prompt + 当前用户 prompt + 会话历史 messages + 工具定义/JSON schema + 附件/图片 + 插件/运行时补充上下文 + provider 适配包装**。

它的核心特点是：

- **持久层只保存会话和 transcript**，不保存“最终 context 快照”。
- **每次运行前重新组装**，因此 workspace 文件、工具策略、模型、provider、sandbox、skills、插件 hook 都会影响当次 context。
- **上下文管理分两类**：
  - 轻量、请求内处理：sanitize、validate、history limit、image prune、tool result prune/truncate。
  - 持久化压缩：compaction，把旧历史总结为 transcript 里的 `compaction` entry。
- **Context Engine 是可插拔层**，默认 `legacy` engine 只透传消息，把实际清洗、裁剪、压缩委托给 OpenClaw/Pi 现有流水线。

## 2. 关键源码地图

| 模块                        | 关键文件                                                                                                                  | 作用                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Context Engine 接口         | `src/context-engine/types.ts`                                                                                             | 定义 `bootstrap / maintain / ingest / assemble / compact / afterTurn` 生命周期 |
| Context Engine 默认实现     | `src/context-engine/legacy.ts`                                                                                            | 默认 `legacy`：ingest/afterTurn no-op，assemble 透传，compact 委托 runtime     |
| Context Engine 注册选择     | `src/context-engine/registry.ts`, `src/context-engine/init.ts`                                                            | 注册内置 `legacy`，从 `plugins.slots.contextEngine` 选择 engine                |
| 运行入口                    | `src/agents/pi-embedded-runner/run.ts`                                                                                    | 解析模型、context window、context engine、重试、overflow compaction            |
| 单次 attempt                | `src/agents/pi-embedded-runner/run/attempt.ts`                                                                            | 真正组装 system prompt、session messages、tools，并调用模型                    |
| attempt context engine glue | `src/agents/pi-embedded-runner/run/attempt.context-engine-helpers.ts`                                                     | 触发 engine bootstrap / assemble / afterTurn / ingest / maintain               |
| system prompt               | `src/agents/system-prompt.ts`, `src/agents/pi-embedded-runner/system-prompt.ts`                                           | 拼接固定系统指令、Project Context、Skills、Memory、Runtime 等                  |
| Project Context 文件        | `src/agents/workspace.ts`, `src/agents/bootstrap-files.ts`, `src/agents/pi-embedded-helpers/bootstrap.ts`                 | 加载 workspace bootstrap 文件，截断，转换为 `{ path, content }`                |
| inbound context             | `src/auto-reply/reply/get-reply-run.ts`, `src/auto-reply/reply/inbound-meta.ts`, `src/auto-reply/reply/prompt-prelude.ts` | 把渠道消息、群聊信息、引用消息、线程历史等变成 prompt/system context           |
| session / transcript        | `src/agents/pi-embedded-runner/session-manager-init.ts`, `docs/reference/session-management-compaction.md`                | SessionManager 从 JSONL transcript 恢复消息上下文                              |
| history hygiene             | `src/agents/pi-embedded-runner/replay-history.ts`                                                                         | 图片、tool call、tool result、provider replay 的清洗修复                       |
| history limit               | `src/agents/pi-embedded-runner/history.ts`                                                                                | 按渠道/DM 配置保留最近 N 个 user turn                                          |
| context pruning             | `src/agents/pi-hooks/context-pruning/*`                                                                                   | 请求内裁剪旧 tool result，不改 transcript                                      |
| tool result truncate        | `src/agents/pi-embedded-runner/tool-result-truncation.ts`, `tool-result-context-guard.ts`                                 | 防止单个或累计工具输出撑爆 context                                             |
| pre-prompt overflow check   | `src/agents/pi-embedded-runner/run/preemptive-compaction.ts`                                                              | 在真正调用模型前估 token，决定是否截断或 compact                               |
| compaction                  | `src/agents/compaction.ts`, `src/agents/pi-embedded-runner/compact.ts`                                                    | 旧消息摘要、保留近期尾部、写入 compaction summary                              |
| tools/schema                | `src/agents/pi-tools.ts`, `src/agents/pi-tools.schema.ts`, `src/agents/pi-embedded-runner/tool-schema-runtime.ts`         | 生成工具、按策略过滤、provider schema 规范化                                   |
| `/context` 观测             | `src/auto-reply/reply/commands-context-report.ts`, `src/agents/system-prompt-report.ts`                                   | 展示 system prompt、bootstrap 文件、skills、tool schema 的大小                 |

## 3. Context 包含哪些部分

### 3.1 System Prompt

System prompt 是 OpenClaw 每次运行生成的系统级指令，主要由 `buildAgentSystemPrompt()` 生成。

典型包含：

- OpenClaw 身份说明。
- Tooling：当前可用工具列表和使用规则。
- Safety。
- Tool Call Style / Execution Bias。
- Skills 元信息。
- Memory prompt 指南。
- OpenClaw CLI quick reference。
- Workspace 信息。
- Documentation 信息。
- Sandbox 信息。
- Authorized Senders。
- Current Date & Time。
- Workspace Files 说明。
- Project Context 文件内容。
- Silent Replies、Messaging、Voice、Reaction 等渠道行为规则。
- Runtime 行：agent、host、repo、os、node、model、channel、capabilities、reasoning 等。

system prompt 有三种模式：

- `full`：主 agent 默认模式，包含完整说明。
- `minimal`：子 agent、cron 等轻量会话使用，跳过大量主 agent 指南。
- `none`：只返回基本身份行。

实现位置：

- `src/agents/system-prompt.ts`
- `src/agents/pi-embedded-runner/system-prompt.ts`
- `src/agents/pi-embedded-runner/run/attempt.ts`

### 3.2 Project Context

Project Context 是被注入 system prompt 的 workspace 文件内容，数据格式是：

```ts
type EmbeddedContextFile = {
  path: string;
  content: string;
};
```

默认候选文件来自 workspace 根目录：

- `AGENTS.md`
- `SOUL.md`
- `TOOLS.md`
- `IDENTITY.md`
- `USER.md`
- `HEARTBEAT.md`
- `BOOTSTRAP.md`
- `MEMORY.md`，如果不存在则 fallback 到 `memory.md`

当前代码中，加载顺序由 `loadWorkspaceBootstrapFiles()` 给出；真正写入 system prompt 时又按 `CONTEXT_FILE_ORDER` 排序：

1. `AGENTS.md`
2. `SOUL.md`
3. `IDENTITY.md`
4. `USER.md`
5. `TOOLS.md`
6. `BOOTSTRAP.md`
7. `MEMORY.md` / `memory.md`

`HEARTBEAT.md` 被视为 dynamic context file，会放在 prompt cache boundary 之后。

注意：

- `memory/*.md` 日记文件不会作为普通 Project Context 全量注入。
- bare `/new` 或 `/reset` 时，runtime 可以读取最近几天 `memory/YYYY-MM-DD.md`，作为启动 prompt prelude 注入当前用户 prompt。

### 3.3 当前用户 Prompt

当前用户 prompt 不是简单的原始消息文本。它会经过：

- 命令解析和授权。
- slash command / inline shortcut 处理。
- 频道消息正文清洗。
- 群聊/线程/引用/转发/历史上下文封装。
- 媒体提示注入。
- 系统事件注入。
- thinking directive 解析和剥离。
- bare `/new` / `/reset` 的启动上下文注入。

核心文件：

- `src/auto-reply/reply/get-reply-run.ts`
- `src/auto-reply/reply/inbound-meta.ts`
- `src/auto-reply/reply/prompt-prelude.ts`
- `src/auto-reply/reply/startup-context.ts`

### 3.4 会话历史 Messages

会话历史来自 transcript JSONL，由 `SessionManager` 恢复为 `AgentMessage[]`。

常见 message role：

- `user`
- `assistant`
- `toolResult`
- `system`，主要用于合成估算或内部上下文
- `compactionSummary` 一类由底层/兼容层转换出的摘要消息

Transcript 中重要 entry 类型：

- `message`：普通 user/assistant/toolResult。
- `custom_message`：会进入模型上下文，但可对 UI 隐藏。
- `custom`：不进入模型上下文，只保存运行时状态。
- `compaction`：持久化摘要，包含 `summary`、`firstKeptEntryId`、`tokensBefore`。
- `branch_summary`：分支摘要。

OpenClaw 不是每次都把整个 transcript 原样塞给模型。它会先恢复活跃分支，再经过 sanitize、validate、filter、limit、context engine assemble。

### 3.5 Tool Definitions 和 JSON Schema

工具也是 context 的一部分，虽然不一定以普通文本出现在 system prompt 中。

每个工具大致是：

```ts
{
  name: string;
  label?: string;
  description?: string;
  parameters?: JSONSchemaLike;
  execute: Function;
}
```

OpenClaw 会同时把工具：

- 作为 system prompt 里的工具摘要文本展示给模型。
- 作为 provider 原生 tool/function schema 传给模型。

因此 `/context detail` 会单独统计：

- Tool list text size。
- Tool schemas JSON size。

工具来源：

- Pi coding 内置工具：read/write/edit 等。
- OpenClaw 自有工具：message、sessions、subagents、gateway、cron、image、browser、canvas 等。
- channel tools。
- plugin tools。
- MCP / LSP bundle tools。
- client tools。

工具会按用户、agent、provider、group、sandbox、subagent、owner 权限等策略过滤。

### 3.6 Skills

Skills 不是一次性把所有 `SKILL.md` 内容塞入 context。

System prompt 中默认只注入 skills 的元信息列表，例如 name、description、location。模型真正需要使用某个 skill 时，再用读文件工具读取对应 `SKILL.md`。

相关文件：

- `src/agents/skills/*`
- `src/agents/system-prompt.ts`

### 3.7 Memory 作为 Context 来源

Memory 不是 context engine 的同义词。Memory 可以通过几条路径进入 context：

- `MEMORY.md` / `memory.md` 作为 Project Context bootstrap 文件注入 system prompt。
- memory 插件注册 `promptBuilder`，由 `buildMemoryPromptSection()` 生成 memory 工具使用指南。
- 模型调用 `memory_search` / `memory_get` 后，搜索结果或读取结果作为 tool result 进入后续 context。
- bare `/new` / `/reset` 时，最近几天 `memory/YYYY-MM-DD.md` 可以被启动上下文读取后塞入当前用户 prompt。
- compaction 前 memory flush 可能把会话摘要写入 memory 文件，但写入后的内容是否进入模型，要等后续通过 bootstrap、startup 或 memory search/get 路径被读取。

### 3.8 附件、图片和媒体

图片/媒体可能来自：

- 当前入站消息附件。
- prompt 中引用的本地图片路径。
- 工具返回的媒体路径。
- 历史消息中的 image blocks。

处理要点：

- vision-capable model 才会用原生图片输入。
- prompt 中图片是 prompt-local，运行时通过 `detectAndLoadPromptImages()` 加载。
- 图片会按配置做大小和维度限制。
- 老历史图片会被 prune，避免长期占用 context。
- 工具结果中的媒体路径最终会经过 reply payload 解析和发送层处理。

### 3.9 Plugin Hook 补充 Context

插件可通过 `before_prompt_build` 注入 context：

```ts
type PluginHookBeforePromptBuildResult = {
  systemPrompt?: string;
  prependContext?: string;
  prependSystemContext?: string;
  appendSystemContext?: string;
};
```

语义：

- `systemPrompt`：覆盖整个 system prompt，优先级高，但风险也高。
- `prependContext`：prepend 到本次用户 prompt 前。
- `prependSystemContext`：加到 system prompt 前部。
- `appendSystemContext`：加到 system prompt 后部。

多个 hook 的文本会按顺序合并；`systemPrompt` 只取第一个定义的值。

## 4. Context 的组织方式

### 4.1 顶层模型输入结构

送给模型的输入可以理解为：

```text
Provider Request
├─ system prompt
│  ├─ stable prefix
│  ├─ Project Context stable files
│  ├─ OPENCLAW_CACHE_BOUNDARY
│  ├─ dynamic Project Context, e.g. HEARTBEAT.md
│  ├─ extra system prompt, e.g. group chat context
│  └─ runtime section
├─ messages
│  ├─ compaction summary if any
│  ├─ historical user/assistant/toolResult messages
│  └─ newly appended current user prompt during activeSession.prompt()
├─ tools / function schemas
├─ images / media input
└─ provider wrappers and transport-specific metadata
```

注意：当前用户 prompt 在 `activeSession.prompt(effectivePrompt)` 时由 Pi session 加入当前 turn；调用前 `activeSession.messages` 主要是历史上下文。

### 4.2 System Prompt 的 stable/dynamic 分层

`SYSTEM_PROMPT_CACHE_BOUNDARY` 是一个显式分界：

```text
<!-- OPENCLAW_CACHE_BOUNDARY -->
```

边界前尽量放稳定内容，利于 Anthropic-family 等 provider 的 prompt cache：

- 工具说明。
- safety。
- skills 元信息。
- memory prompt 指南。
- workspace 固定说明。
- stable Project Context 文件。

边界后放更容易变化的内容：

- dynamic Project Context，例如 `HEARTBEAT.md`。
- group chat / subagent extra system prompt。
- provider dynamic suffix。
- heartbeat prompt。
- runtime 行。

Context engine 的 `systemPromptAddition` 会通过 `prependSystemPromptAdditionAfterCacheBoundary()` 插入：如果存在 cache boundary，就插在 boundary 后、dynamic suffix 前，避免破坏稳定前缀缓存。

### 4.3 Project Context 文件的选取

选取流程：

1. `loadWorkspaceBootstrapFiles(workspaceDir)` 读取默认候选文件。
2. `resolveMemoryBootstrapEntry()` 在 `MEMORY.md` 和 `memory.md` 中选一个。
3. `filterBootstrapFilesForSession()` 根据 session 类型过滤。
4. `applyContextModeFilter()` 根据 bootstrap mode 过滤：
   - `full`：保留全部候选。
   - `lightweight + heartbeat`：只保留 `HEARTBEAT.md`。
   - `lightweight + default/cron`：不注入 bootstrap context。
5. `applyBootstrapHookOverrides()` 允许插件修改 bootstrap 文件列表。
6. `buildBootstrapContextFiles()` 截断并转换成 `{ path, content }`。
7. `buildAgentSystemPrompt()` 排序并写入 `# Project Context`。

session 类型过滤的当前代码逻辑：

- 普通 session：保留所有候选。
- subagent / cron session：只保留 `MINIMAL_BOOTSTRAP_ALLOWLIST`，当前包括 `AGENTS.md`、`TOOLS.md`、`SOUL.md`、`IDENTITY.md`、`USER.md`。

### 4.4 Messages 的选取

历史消息选取不是一次完成的，分多步：

1. `SessionManager.open(sessionFile)` 从 transcript 恢复活跃分支。
2. `sanitizeSessionHistory()` 做通用清洗。
3. `validateReplayTurns()` 做 provider-specific replay 校验。
4. `filterHeartbeatPairs()` 移除或压缩心跳 pair。
5. `limitHistoryTurns()` 根据渠道配置保留最近 N 个 user turns。
6. 截断后再次修复 tool use / tool result pairing。
7. `contextEngine.assemble()` 最后可重排、裁剪或补充 system prompt。
8. `before_prompt_build` hook 可再为当前 prompt/system prompt 添加上下文。
9. prompt 前做图片 prune、preemptive overflow check。

默认 `legacy` context engine 在第 7 步只透传，所以主要行为来自第 1-6 和第 8-9 步。

### 4.5 Tools 的选取

工具选取流程：

1. `createOpenClawCodingTools()` 构造候选工具。
2. 根据 sandbox 决定 read/write/edit/apply_patch 是否使用 sandbox wrapper。
3. 根据模型/provider 决定是否支持 tools。
4. 应用工具策略：
   - profile policy。
   - provider profile policy。
   - global policy。
   - agent policy。
   - group policy。
   - sandbox policy。
   - subagent policy。
   - owner-only policy。
   - message provider policy。
5. 合并 MCP/LSP bundle tools。
6. 规范化 JSON schema：
   - root union flatten 成 object。
   - 空 schema 转 `{ type: "object", properties: {} }`。
   - Gemini / xAI / compat 配置移除不支持的 schema keyword。
7. `splitSdkTools()` 把所有工具转成 custom tool definitions 交给 Pi/provider。

## 5. 每个部分经过了什么处理

### 5.1 Inbound Prompt 处理

处理目标：把“渠道消息”变成“模型可理解但不被用户内容污染的 prompt”。

主要处理：

- `buildInboundMetaSystemPrompt()` 生成可信 metadata，放入 extra system prompt。
- `buildInboundUserContextPrefix()` 生成不可信 metadata，放入用户 prompt 前缀。
- 不可信内容用 JSON block 包裹，并标注 untrusted。
- 字符串会去掉 null bytes。
- JSON 字符串最长 2000 chars。
- inbound history 最多保留 20 条。
- markdown fence 会被 neutralize，避免破坏外层 block。
- quoted/replied/forwarded/thread/history/context 都标为 untrusted。
- `appendUntrustedContext()` 会把外部 `UntrustedContext` 追加到 prompt。

数据流：

```text
channel raw message
  -> TemplateContext / MsgContext
  -> buildInboundMetaSystemPrompt()        -> extraSystemPrompt
  -> buildInboundUserContextPrefix()       -> user prompt prefix
  -> buildReplyPromptBodies()              -> prefixedCommandBody / queuedBody
  -> runEmbeddedPiAgent(prompt=...)
```

### 5.2 Startup Context 处理

bare `/new` 或 `/reset` 时，如果配置允许，会读取最近日记：

- 路径：`memory/YYYY-MM-DD.md`
- 默认天数：2 天。
- 单文件默认读取上限：16 KB。
- 单文件默认注入字符上限：2000 chars。
- 总注入默认上限：4500 chars。

格式：

````text
[Startup context loaded by runtime]
...
[Untrusted daily memory: memory/2026-04-14.md]
BEGIN_QUOTED_NOTES
```text
...
```
END_QUOTED_NOTES
````

这些日记被明确标注为 untrusted，只能作为背景，不可当指令执行。

### 5.3 Bootstrap / Project Context 处理

文件读取：

- 使用 `openBoundaryFile()` 做 workspace root 边界校验。
- 单个 bootstrap 文件最多读 2 MB。
- 文件缓存按 path + dev/ino/size/mtime identity，避免 stale read。
- 读取失败会生成 missing entry。

截断逻辑：

- `agents.defaults.bootstrapMaxChars`：单文件注入上限，默认 `20000` chars。
- `agents.defaults.bootstrapTotalMaxChars`：所有 bootstrap 注入总上限，默认 `150000` chars。
- 文件过大时保留 head 70% + tail 20%，中间加入 truncation marker。
- missing 文件会注入 `[MISSING] Expected at: <path>`。
- 如果剩余总预算低于 64 chars，会跳过后续文件。

写入 system prompt：

- stable 文件写入 `# Project Context`。
- dynamic 文件写入 cache boundary 后的 `# Dynamic Project Context`。

### 5.4 System Prompt 处理

system prompt 的构建顺序大致是：

```text
buildEmbeddedSystemPrompt()
  -> buildAgentSystemPrompt()
  -> transformProviderSystemPrompt()
  -> createSystemPromptOverride()
  -> applySystemPromptOverrideToSession()
```

处理点：

- 工具列表按固定顺序输出，未知工具按字母序追加。
- provider 可提供 `stablePrefix`、`dynamicSuffix`、section override。
- Project Context 文件按固定顺序排序。
- `HEARTBEAT.md` 等 dynamic 文件放 cache boundary 后。
- context engine 的 `systemPromptAddition` 插到 cache boundary 后。
- plugin hook 可以覆盖或追加 system prompt。

### 5.5 Skills 处理

处理流程：

1. 根据 workspace/config/agentId 构建 skills snapshot。
2. snapshot 变成 skills prompt。
3. system prompt 中只放 skills 元信息。
4. 模型根据说明选择最多一个 skill 先读。

这样避免所有 skills 文件内容常驻 context。

### 5.6 Memory Prompt 处理

Memory prompt 来自：

```text
buildMemoryPromptSection({
  availableTools,
  citationsMode
})
```

它会合并：

- memory capability 的 `promptBuilder`
- legacy `registerMemoryPromptSection`
- memory prompt supplements

默认只有在非 minimal prompt 且 `includeMemorySection !== false` 时注入。

特殊点：

- legacy context engine 下，memory prompt 直接由 system prompt 构建注入。
- 非 legacy context engine 下，`includeMemorySection` 默认为 false，engine 可显式通过 `buildMemorySystemPromptAddition()` 复用同样的 memory prompt 指南。

### 5.7 History Hygiene 处理

`sanitizeSessionHistory()` 处理历史消息：

- 给 inter-session user messages 加 marker。
- 清洗历史图片。
- 根据 provider policy 删除 thinking blocks 或 thought signatures。
- 清洗 tool call inputs。
- 修复 tool_use/tool_result pairing。
- OpenAI Responses 路径降级 reasoning/function-call pair。
- 规范化 tool call id。
- 删除 `toolResult.details`，避免 verbose/untrusted payload 进入 token 估算或 compaction。
- 去掉旧 compaction 前 stale assistant usage snapshot。
- 调 provider replay hook 做 provider-specific 清洗。
- 必要时做 Google turn ordering 修复。

`validateReplayTurns()` 再做 provider replay 校验。

### 5.8 History Limit 处理

`limitHistoryTurns(messages, limit)` 按最近 user turn 数截断：

- `limit <= 0` 或未配置：不截断。
- 从后往前数 user 消息。
- 超过 limit 时，保留从第 N 个 user turn 开始到尾部的全部消息。

limit 来源：

- DM：per-DM `historyLimit` 优先，然后 provider `dmHistoryLimit`。
- group/channel：provider `historyLimit`。

截断后会再次修复 tool_use/tool_result pairing，避免孤儿 tool result。

### 5.9 Context Engine Assemble 处理

接口：

```ts
assemble({
  sessionId,
  sessionKey,
  messages,
  tokenBudget,
  availableTools,
  citationsMode,
  model,
  prompt
}) -> {
  messages,
  estimatedTokens,
  systemPromptAddition?
}
```

在 attempt 中的处理：

1. 上游 pipeline 已经得到 `activeSession.messages`。
2. 调 `contextEngine.assemble(...)`。
3. 如果返回的 `messages` 不是同一个引用，替换 session messages。
4. 如果返回 `systemPromptAddition`，插入 system prompt 并重新 apply 到 session。
5. assemble 失败时记录 warning，继续使用 pipeline messages。

默认 legacy engine：

- `assemble` 返回原 messages。
- `estimatedTokens = 0`。
- 不提供 `systemPromptAddition`。

### 5.10 Plugin Hook 处理

prompt 前会调用：

```text
resolvePromptBuildHookResult()
  -> before_prompt_build
  -> legacy before_agent_start compatibility
```

处理结果：

- `prependContext` prepend 到当前用户 prompt 前。
- `systemPrompt` 覆盖 system prompt。
- `prependSystemContext` / `appendSystemContext` 组合到 system prompt。
- 当前 active video/music generation task context 也会作为 prepend system context 注入。

### 5.11 图片处理

prompt 前处理：

- `pruneProcessedHistoryImages(activeSession.messages)` 清理旧历史图片。
- `detectAndLoadPromptImages()` 从 prompt 和显式 images 参数加载图片。
- 限制 max bytes 和 max dimension。
- sandbox 下校验路径边界。
- 有图片时 `activeSession.prompt(effectivePrompt, { images })`。
- 无图片时 `activeSession.prompt(effectivePrompt)`。

### 5.12 Pre-prompt Overflow 处理

真正请求模型前，OpenClaw 会估算：

```text
estimatedPromptTokens =
  estimateMessagesTokens(history)
  + estimateTokens(systemPrompt as synthetic system message)
  + estimateTokens(current prompt as synthetic user message)

再乘 SAFETY_MARGIN 1.2
```

然后比较：

```text
promptBudgetBeforeReserve = contextTokenBudget - effectiveReserveTokens
overflowTokens = estimatedPromptTokens - promptBudgetBeforeReserve
```

路由：

- `fits`：直接发模型。
- `truncate_tool_results_only`：只截断工具结果，跳过本次 prompt submission，让外层重试。
- `compact_only`：触发 compaction。
- `compact_then_truncate`：先 compact，再必要时截断工具结果。

### 5.13 Context Pruning 处理

Context pruning 是请求内处理，不写回 transcript。

接入点：

```text
contextPruningExtension(api)
  -> api.on("context", ...)
  -> pruneContextMessages(...)
```

处理逻辑：

- 根据 model context window 估算 charWindow。
- 保留最近若干 assistant turns。
- 不裁剪第一个 user message 前的 bootstrap/身份读取上下文。
- 只裁剪允许裁剪的旧 `toolResult`。
- 先 soft trim tool result。
- 如果仍超过 hard threshold，再把旧 tool result 替换为 placeholder。

### 5.14 Tool Result Truncation 处理

工具结果截断分两类：

- live request path：防止当前工具输出撑爆下一轮 context。
- overflow recovery：precheck 判断只截断 tool result 即可恢复时，直接改 transcript/session。

单个 tool result 默认硬上限：

- `DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS = 40000`
- 单个结果最多占 context window 约 30%

截断策略：

- 一般保留开头。
- 如果尾部包含 error/exception/traceback/result/summary/JSON closing 等重要信息，保留 head + tail。
- 插入 truncation notice。

### 5.15 Compaction 处理

Compaction 是持久化上下文压缩。

触发：

- 手动 `/compact`。
- 模型返回 context overflow 后 recovery。
- Pi runtime threshold maintenance。
- pre-prompt overflow check 路由到 compact。

处理：

1. 重新创建 compaction session。
2. 构建和普通 run 类似的 system prompt/tools/provider transport。
3. 恢复 transcript messages。
4. sanitize + validate。
5. history limit。
6. before_compaction hooks。
7. `activeSession.compact(customInstructions)`。
8. 生成 summary。
9. transcript 写入 `compaction` entry。
10. 未来 context 由 summary + `firstKeptEntryId` 之后的 messages 重建。
11. after_compaction hooks / post side effects。
12. 可选 `truncateAfterCompaction` 清理被压缩的 transcript entry。

Compaction 会尽量保持 tool call 和 tool result pair 不被拆散。切 chunk 时如果边界落在工具调用和结果之间，会移动边界。

## 6. 生命周期视角

### 6.1 Gateway / 插件启动

发生：

- 加载 runtime plugins。
- 初始化 global hook runner。
- 注册 memory capability / memory prompt section / memory runtime。
- 注册 provider runtime、tool、context engine 等插件能力。
- `ensureContextEnginesInitialized()` 注册内置 `legacy` context engine。

Context 影响：

- 插件可以在后续 run 中提供工具、prompt hook、provider prompt contribution、memory prompt、context engine。

### 6.2 会话初始化 / reset

发生：

- inbound 消息映射到 `sessionKey`。
- `sessionKey` 解析当前 `sessionId` 和 transcript 文件。
- `/new`、`/reset`、daily reset、idle reset 可能创建新 `sessionId`。
- bare `/new` 或 `/reset` 可读取最近 daily memory，作为 startup context。

Context 影响：

- 决定读取哪个 transcript。
- 决定是否从旧 session 继承/分叉。
- 决定是否注入 startup memory prelude。

### 6.3 运行前：组装 prompt 和 system context

发生：

1. `get-reply-run.ts` 构建 inbound meta、group context、user prompt。
2. `runEmbeddedPiAgent()` 解析 workspace、provider、model、context window、context engine。
3. `runEmbeddedAttempt()` 解析 sandbox、skills、bootstrap files。
4. 创建 tools 并过滤。
5. 构建 system prompt 和 `systemPromptReport`。
6. 打开 SessionManager。
7. context engine `bootstrap()` / `maintain(reason=bootstrap)`。

Context 影响：

- system prompt 已包含 tools、skills、project context、runtime 等。
- SessionManager 已准备好 transcript active branch。
- Context engine 有机会导入历史或维护 transcript。

### 6.4 运行前：整理 history messages

发生：

1. 从 `activeSession.messages` 取历史。
2. `sanitizeSessionHistory()`。
3. `validateReplayTurns()`。
4. `filterHeartbeatPairs()`。
5. `limitHistoryTurns()`。
6. 修复 tool_use/tool_result pairing。
7. `contextEngine.assemble()`。

Context 影响：

- 决定最终哪些历史消息进入模型。
- 决定是否有 context engine 的 system prompt addition。

### 6.5 prompt 提交前：hook、图片、预算保护

发生：

1. `before_prompt_build` / legacy `before_agent_start` hook。
2. 合成 `prependContext`、system override、prepend/append system context。
3. prompt cache observation。
4. prompt 中图片检测和加载。
5. pre-prompt overflow check。
6. context pruning extension 可能在 Pi context event 中裁剪旧 tool results。

Context 影响：

- 插件可以最后补充 prompt/system context。
- 图片被作为本次 prompt-local 输入加入。
- 如果估算超限，可能不调用模型，先 truncate 或 compact。

### 6.6 模型运行中

发生：

- `activeSession.prompt(effectivePrompt, options)`。
- 模型看到 system prompt + history messages + 当前 user prompt + tools + images。
- 模型调用工具。
- tool result 追加到 session messages。
- stream wrappers 在每次 outbound request 前修复 thinking blocks、tool call ids、OpenAI reasoning pairs、malformed tool call names 等。
- tool-result context guard 防止工具循环中结果不断撑爆 context。

Context 影响：

- 同一轮内多次 tool loop 会不断扩展临时 messages。
- wrappers 保证 provider 看到的 replay 结构合法。

### 6.7 运行后

发生：

1. 捕获 `messagesSnapshot`。
2. 更新 usage、prompt cache telemetry。
3. 写 session store 中的 system prompt report、tokens、compaction count 等。
4. context engine `afterTurn()`。
5. 如果 engine 没有 `afterTurn()`，fallback 到 `ingestBatch()` 或逐条 `ingest()`。
6. 成功时 `maintain(reason=turn)`。

Context 影响：

- transcript 已由 SessionManager 保存。
- context engine 可以把这轮消息写入自己的 store。
- maintain 可通过 runtime 提供的 `rewriteTranscriptEntries()` 安全改写 transcript active branch。

### 6.8 Compaction 生命周期

发生：

- 手动、overflow、threshold 或 precheck 触发。
- `contextEngine.compact()` 被调用。
- legacy engine 委托 `compactEmbeddedPiSessionDirect()`。
- 如果第三方 engine `ownsCompaction === true`，则由 engine 自己管理 compact。
- compact 成功后可触发 context engine maintenance。

Context 影响：

- 旧历史被摘要成 `compaction` entry。
- 后续 turn 不再看到完整旧消息，而看到 summary + kept tail。

### 6.9 `/context` 观测生命周期

`/context` 不直接读取“模型最后实际 payload”，而是：

- 优先使用上一次 run 保存的 `systemPromptReport`。
- 没有可用 run report 时，重新估算一个 commands system prompt bundle。

它展示：

- workspace。
- bootstrap max/file 和 max/total。
- injected workspace files raw vs injected size。
- system prompt size。
- Project Context size。
- skills prompt size。
- tool schema JSON size。
- session cached token usage。

## 7. 清晰数据流

### 7.1 普通用户消息到模型的主数据流

```text
Channel inbound message
  -> MsgContext / TemplateContext
  -> command parsing / authorization / directive stripping
  -> inbound trusted metadata          -> extraSystemPrompt
  -> inbound untrusted context         -> user prompt prefix
  -> media note / thread note / events -> user prompt
  -> followupRun
  -> runEmbeddedPiAgent()
  -> resolve model/provider/context window
  -> resolve context engine
  -> runEmbeddedAttempt()
  -> load bootstrap files              -> EmbeddedContextFile[]
  -> resolve skills                    -> skillsPrompt
  -> create/filter/normalize tools     -> AgentTool[]
  -> build system prompt
  -> open SessionManager               -> transcript messages
  -> sanitize/validate/filter/limit history
  -> contextEngine.assemble()
  -> before_prompt_build hooks
  -> detect/load images
  -> pre-prompt overflow check
  -> activeSession.prompt()
  -> provider request
```

### 7.2 System Prompt 数据流

```text
workspace files
  -> loadWorkspaceBootstrapFiles()
  -> filterBootstrapFilesForSession()
  -> applyContextModeFilter()
  -> applyBootstrapHookOverrides()
  -> buildBootstrapContextFiles()
  -> contextFiles: { path, content }[]

tools + skills + memory prompt + runtime info + contextFiles
  -> buildEmbeddedSystemPrompt()
  -> buildAgentSystemPrompt()
  -> transformProviderSystemPrompt()
  -> createSystemPromptOverride()
  -> applySystemPromptOverrideToSession()

contextEngine.systemPromptAddition / hook system context
  -> prepend/append around cache boundary
  -> final system prompt
```

### 7.3 History Messages 数据流

```text
~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl
  -> SessionManager.open()
  -> build active branch messages
  -> sanitizeSessionHistory()
     - images
     - thinking blocks
     - tool call inputs
     - tool ids
     - tool pair repair
     - provider replay hook
  -> validateReplayTurns()
  -> filterHeartbeatPairs()
  -> limitHistoryTurns()
  -> repair tool pair again
  -> contextEngine.assemble()
  -> activeSession.agent.state.messages
```

### 7.4 Tools / Schema 数据流

```text
codingTools + OpenClaw tools + channel tools + plugin tools
  -> createOpenClawCodingTools()
  -> sandbox wrapping
  -> memory flush special wrapping if trigger=memory
  -> message provider filtering
  -> model/provider filtering
  -> owner authorization filtering
  -> profile/global/agent/group/sandbox/subagent policy pipeline
  -> normalizeToolParameters()
  -> before_tool_call hook wrapper
  -> abort-signal wrapper
  -> deferred followup descriptions
  -> normalizeProviderToolSchemas()
  -> MCP/LSP bundle tools added
  -> splitSdkTools()
  -> provider native tool/function schemas
```

### 7.5 Context Engine 数据流

```text
plugins.slots.contextEngine
  -> resolveContextEngine()
  -> contextEngine instance

attempt start:
  -> contextEngine.bootstrap?()
  -> contextEngine.maintain?(reason=bootstrap)

before model:
  pipeline messages
  -> contextEngine.assemble()
  -> messages replacement and/or systemPromptAddition

after model:
  messagesSnapshot + prePromptMessageCount
  -> contextEngine.afterTurn?()
  -> else ingestBatch?()
  -> else ingest() per new message
  -> contextEngine.maintain?(reason=turn)

compaction:
  -> contextEngine.compact()
  -> legacy delegates runtime compaction
  -> contextEngine.maintain?(reason=compaction)
```

### 7.6 Compaction 数据流

```text
context too large / manual / threshold
  -> contextEngine.compact()
  -> legacy: compactEmbeddedPiSessionDirect()
  -> open session transcript
  -> sanitize + validate + limit
  -> before_compaction hooks
  -> activeSession.compact(customInstructions)
  -> summarize older history
  -> write transcript compaction entry
     {
       type: "compaction",
       summary,
       firstKeptEntryId,
       tokensBefore
     }
  -> future SessionManager context
     = compaction summary + messages after firstKeptEntryId
```

## 8. Context 与 Memory 的关系

Memory 是 context 的一个来源，而不是 context 本身。

| 场景                                  | Memory 如何进入 context                                                    |
| ------------------------------------- | -------------------------------------------------------------------------- |
| `MEMORY.md` 存在                      | 作为 Project Context bootstrap 文件进入 system prompt                      |
| `memory.md` 存在且 `MEMORY.md` 不存在 | 作为 lowercase fallback 进入 system prompt                                 |
| `memory/*.md` daily notes             | 默认不注入；bare `/new` / `/reset` 可读取最近日记作为 startup prompt       |
| memory prompt section                 | 作为 system prompt 指南，告诉模型何时用 `memory_search` / `memory_get`     |
| 模型调用 `memory_search`              | 搜索结果作为 tool result 进入后续 context                                  |
| 模型调用 `memory_get`                 | 文件片段作为 tool result 进入后续 context                                  |
| memory flush                          | 写入 memory 文件；后续是否进入 context 取决于 bootstrap/startup/search/get |

## 9. 需要特别区分的几个概念

### 9.1 Pruning vs Compaction

| 项           | Pruning                                | Compaction                      |
| ------------ | -------------------------------------- | ------------------------------- |
| 是否持久化   | 否                                     | 是                              |
| 主要处理对象 | 旧 tool result、旧图片                 | 旧 conversation messages        |
| 结果         | 当前请求内 messages 被裁剪             | transcript 写入 summary         |
| 目的         | 降低当前请求 token                     | 长期压缩历史                    |
| 入口         | Pi context extension / prompt 前 guard | `/compact`、overflow、threshold |

### 9.2 Project Context vs User Prompt Context

| 项       | Project Context                | User Prompt Context                           |
| -------- | ------------------------------ | --------------------------------------------- |
| 来源     | workspace bootstrap 文件       | 当前 inbound 消息、群聊、引用、线程、系统事件 |
| 位置     | system prompt                  | 当前 user prompt                              |
| 信任级别 | 用户可编辑，但作为项目说明注入 | 多数标注为 untrusted                          |
| 生命周期 | 每次 run 重新读取或缓存读取    | 当前消息一次性生成                            |

### 9.3 System Prompt Tool List vs Tool Schema

| 项              | Tool list                  | Tool schema                                |
| --------------- | -------------------------- | ------------------------------------------ |
| 形式            | 文本说明                   | JSON schema / provider function definition |
| 位置            | system prompt              | provider tools 参数                        |
| `/context` 统计 | `Tool list`                | `Tool schemas (JSON)`                      |
| 作用            | 告诉模型有哪些工具和怎么用 | 约束工具调用参数结构                       |

### 9.4 `contextTokens` vs 实际可用窗口

- model context window 是硬上限，来自模型配置或 `agents.defaults.contextTokens` cap。
- `sessions.json` 中 token 计数是运行后缓存/统计值，用于 `/status`、`/context` 等展示。
- pre-prompt check 使用估算值，并乘 1.2 safety margin。
- provider 真实包装开销可能无法完全由本地估算覆盖。

## 10. 小结

OpenClaw 的 context 实现可以理解成九层：

1. **Inbound 层**：把渠道消息变成 trusted system metadata + untrusted user context。
2. **Session 层**：从 `sessions.json` 和 transcript JSONL 找到当前会话历史。
3. **Bootstrap 层**：读取 workspace 文件，形成 Project Context。
4. **System Prompt 层**：把工具、skills、memory、workspace、runtime、Project Context 拼成系统提示。
5. **Tools 层**：构造工具、过滤策略、规范化 schema，并传给 provider。
6. **History Hygiene 层**：清洗、校验、修复历史消息。
7. **Context Engine 层**：可插拔地 assemble、ingest、compact、maintain。
8. **Budget Protection 层**：pruning、tool truncation、precheck、compaction。
9. **Observability 层**：`systemPromptReport` 和 `/context` 解释当前 context 构成。

最终效果是：OpenClaw 不把“所有知道的信息”都塞进模型，而是在每次运行前按会话、workspace、工具策略、模型能力、插件能力和 token 预算动态选择一份上下文，并在超限时优先裁工具结果、再压缩历史。
