# Layer 2 immediate extraction 实现说明

本文只解释 Layer 2 当前真实运行语义。

本文描述的是已经落在 `extensions/feishu-task-wiki/openclaw-lark` 的实现，不描述已舍弃的批量抽取方案。

`memory-core` 不承接 Task Wiki 的 event extraction 逻辑；Task Wiki 自己在 Layer 2 完成 ingest、candidate extraction、validation 和 verification。

## 主要代码面

- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/extractor.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-wiki/projector.js`

## 当前主流程

```text
message ingress
-> maybeIngestTaskSourceSession(...)
-> append source session
-> pending_ingests.jsonl / evidence_spans.jsonl
-> extractCandidateEventsWithLLM(...)
-> validateCandidateEvent(...)
-> candidate_events.jsonl
-> verification_jobs.jsonl
-> runVerificationJobs(...)
-> session_events.jsonl
-> updateTaskWikiFromVerifiedEvents(...)
-> session_wiki / task_index / task_wiki
```

`maybeIngestTaskSourceSession(...)` 是当前 Layer 2 的 ingest 入口。它会写 source session、记录 per-ingest ledger 和 evidence envelope，然后立即对当前 ingest 调用 LLM candidate extractor。

`candidate_events.jsonl` 表示“模型从当前 ingest 证据里抽到了什么，以及程序化校验结果是什么”。

`session_events.jsonl` 表示“哪些 candidate 经过 verification 后进入 verified ledger”，这是 Layer 3 projector 的正式事实输入。

## Pending 与 Evidence

`pending_ingests.jsonl` 是 per-ingest ledger，不是批量队列。

它记录每条进入 source session 的消息是否产生 candidate、是否等待 verification、最终是否 verified / rejected / needs_review / processed_no_event。

`evidence_spans.jsonl` 是 per-ingest evidence envelope，不是另一种上下文。

它记录当前 ingest 的证据包，包括：

- `trigger_entries`：当前触发消息。
- `context_entries`：用于解释代词、时间、修正、否定和前后文的邻近消息。
- `support_entries`：thread root、comment root 或上位背景等辅助证据。
- `core_entries`：当前实现里通常与 trigger 高度重合，表示最可能承载新事实的证据。

## Extractor

当前 extractor 的正式执行点在 `maybeIngestTaskSourceSession(...)` 内。

`extractCandidateEventsWithLLM(...)` 的输入是当前 ingest 的 evidence envelope，而不是完整任务历史。

一次抽取可以产出 0 到 N 个 candidate events，因为一条企业消息可能同时表达 owner、deadline、blocker、status 或 dependency 变化。

这里的 `N` 仍受 atomicity 约束：每个 candidate event 必须是一个可验证的原子事实，不能把多个无关结论揉成一个 event。

## Validate / Verify

Layer 2 不是“抽取一步到位”，而是三段式：

```text
extractCandidateEventsWithLLM(...)
-> validateCandidateEvent(...)
-> runVerificationJobs(...)
-> verifyCandidateEvent(...)
```

`validateCandidateEvent(...)` 是 programmatic gate，负责 schema、typed fields、evidence quote、atomicity 和基础可验证性检查。它决定 candidate 是否能进入 verification。

`verifyCandidateEvent(...)` 是语义确认层，基于 evidence 判断 candidate 是否真的成立，并产出 `verified`、`needs_review` 或 `rejected`。

因此 `candidate_events.jsonl` 和 `session_events.jsonl` 必须分层：前者是候选层，后者是 verified ledger。

## Context 如何确定

`context_entries` 不是 LLM 临时想出来的。

当前先由 ingest 侧根据 source type 程序化构造：

- `thread`：当前消息进 trigger，thread root 进 support，之前消息进 context。
- `comment`：当前消息进 trigger，comment root 进 support，之前消息和 reply chain 进 context。
- `chat`：当前消息进 trigger，最近少量 prior entries 进 context。

随后 extractor 只消费这个 evidence envelope；它不能把未进入 observed data 的 planned text 当证据。

## 与 Layer 3 的边界

Layer 3 只消费 `session_events.jsonl` 里的 verified events。

如果某条 candidate 没通过 validation 或 verification，它可以留在 audit 层，但不能投影到 `session_wiki_state`、`task_index_state` 或 `task_wiki_state`。

## 与 memory-core 的边界

`memory-core` 不知道这些文件：

- `pending_ingests.jsonl`
- `evidence_spans.jsonl`
- `candidate_events.jsonl`
- `session_events.jsonl`

这些都是 `openclaw-lark` Task Wiki plugin 内部的 Layer 2 运行语义。

## 实现验证依据

- `maybeIngestTaskSourceSession(...)` 可写入 source session、pending ledger、evidence span 和 candidate events。
- `runVerificationJobs(...)` 可从 verification jobs 推进到 `session_events.jsonl`。
- `updateTaskWikiFromVerifiedEvents(...)` 可继续消费 verified events，不改 Layer 3 contract。
