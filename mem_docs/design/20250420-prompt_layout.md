# 实现目标 Prompt Layout 的计划

## Summary

这个目标是可行的，而且有提升空间，但需要明确一点：当前系统还没有严格实现你写的 layout。现在 Graph evidence 主要通过 `memory_search` tool result 进入上下文，位置更接近“用户问题之后、最终回答之前”，而不是“当前 user prompt 前的 tail evidence”。

要实现你要的顺序，最干净的方案是让 `memory-core` 注册一个 ContextEngine，在每轮模型调用前主动做轻量 recall，然后把内容分两段注入：

```text
stable system prompt
stable memory schema
cache boundary
short project state summary
recent live context
top-1/top-3 evidence near current query
current user prompt
```

可预期收益：

- 减少必须显式调用 `memory_search` 的轮次，降低工具调用 latency。
- Graph state/event 比 raw memory chunk 更短，可以作为 semantic compression。
- top evidence 更靠近当前 query，能缓解 Lost in the Middle。
- 对 state / why / timeline / relation 类问题最可能提升；对普通闲聊或无需历史的问题不应注入，避免 prompt 膨胀。

## Key Changes

- 注册 `memory-core` ContextEngine：
  - 在 `extensions/memory-core/index.ts` 调用 `api.registerContextEngine("memory-core", ...)`。
  - 将 plugin kind 扩展为 `["memory", "context-engine"]`。
  - 默认不替换全局 `legacy`，先通过配置 `plugins.slots.contextEngine = "memory-core"` 启用，避免影响全量用户。
  - 该 engine 只负责 assemble-time recall placement；第一层 afterTurn / beforeCompaction / drain 继续保持现有主链。

- 保留 stable memory schema 在 cache boundary 前：
  - 当前非 legacy context engine 会跳过基础 memory prompt section。
  - 对 `memory-core` engine 例外保留 memory prompt section，使 memory schema / tool guidance 仍属于稳定 system prompt。
  - 动态 project state 和 evidence 不放进 stable prefix，避免破坏 prompt cache。

- 扩展 ContextEngine assemble 输出：
  - 保留现有 `systemPromptAddition`，用于 cache boundary 后的 `short project state summary`。
  - 新增一个 ephemeral current-turn 字段，例如 `currentUserPromptPrefix`。
  - runner 在本轮调用模型前把它拼到当前 prompt 前面，不写回 transcript，不进入持久 session history。
  - 目标顺序变成：

```text
stable system prompt
stable memory schema
cache boundary
systemPromptAddition: short project state summary
recent live context
currentUserPromptPrefix: top-1/top-3 evidence near current query
current user prompt
```

- `short project state summary` 的来源：
  - 使用 Graph Index V2 查询，不走旧 semantic。
  - 优先从 `workflow_state_view_v2` 取当前 owner / stage / approval / blocker / next_action。
  - 只保留 3 到 5 条最相关 task state。
  - 字符预算建议默认 600 到 1000 chars。
  - 没有明确 memory intent 或没有 graph hit 时不注入。

- `top-1/top-3 evidence near current query` 的来源：
  - 同时考虑 graph hits 和 memory hits，不只 reorder graph。
  - Graph hits 来自 `searchGraphV2`。
  - Memory hits 来自现有 memory manager search。
  - 使用统一 query-aware ordering：
    - state query：graph state 优先，raw memory 作为补充。
    - why query：slot_versions 对应 event + evidence 优先。
    - timeline query：graph events 按 occurred_at 排序，必要时补 raw evidence。
    - list_relation query：graph edge / workflow state 优先。
  - 默认最多注入 3 条 evidence，总预算建议 1200 到 2000 chars。
  - 每条 evidence 保留 source path/line，方便后续 `memory_get` 或引用。

- 避免重复工具调用：
  - 更新 memory prompt guidance：如果当前 prompt 中已经有 `## Current Memory Context`，模型可以直接使用；只有证据不足或需要原文时再调用 `memory_search` / `memory_get`。
  - `memory_search` 工具仍保留，作为 fallback 和显式深挖入口。
  - assemble-time recall 失败时静默降级，不阻塞主对话。

## Test Plan

- Layout tests：
  - 启用 `plugins.slots.contextEngine = "memory-core"` 后，system prompt 中稳定 memory schema 仍在 cache boundary 前。
  - `short project state summary` 出现在 cache boundary 后。
  - `currentUserPromptPrefix` 被放在当前 user prompt 前。
  - 注入内容不写回 session transcript。

- Recall placement tests：
  - state query 会注入 graph state summary。
  - why query 会注入 blocker / approval / stage 对应 event evidence。
  - timeline query 会注入按时间排序的 top events。
  - list_relation query 会注入 graph edge / workflow state。
  - 无 memory intent 的普通问题不注入，避免 prompt 膨胀。

- Prompt cache tests：
  - stable system prompt 和 memory schema 在相同配置下保持稳定。
  - 动态 summary/evidence 位于 cache boundary 后，不污染 stable prefix。
  - 相同 query 和相同 store 状态下 evidence ordering deterministic。

- Regression tests：
  - 现有 `memory_search` 工具仍可用。
  - Graph pending projection 在 assemble recall 前会先 drain，保证读取的是最新 V2 graph。
  - assemble recall 出错时回退到原始 messages/prompt。
  - legacy context engine 默认行为不变。

## Assumptions

- 这个能力先作为 `memory-core` context engine 启用，不立刻替换默认 `legacy`。
- 不实现独立 extractive compressor；Graph Index 的结构化投影就是 semantic compression。
- 系统级提升来自两个点：Graph structured state 减少 raw prompt tokens，以及 top evidence 被放到当前 query 附近。
- 真正要证明提升，应做 ablation：
  - baseline：只靠显式 `memory_search`
  - graph only：Graph Index V2 + tool result
  - layout：Graph Index V2 + assemble-time head summary + tail evidence
