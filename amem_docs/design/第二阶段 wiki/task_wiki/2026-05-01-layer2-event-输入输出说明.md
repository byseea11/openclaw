# 2026-05-01 Layer 2 Event 输入输出说明

这份文档描述 Feishu Task Wiki 第二阶段 Layer 2 event 的当前真实输入输出。

当前实现口径固定为 immediate extraction：

```text
maybeIngestTaskSourceSession(...)
-> append source session
-> pending_ingests.jsonl / evidence_spans.jsonl
-> extractCandidateEventsWithLLM(...)
-> validateCandidateEvent(...)
-> candidate_events.jsonl
-> verification_jobs.jsonl
-> runVerificationJobs(...)
-> session_events.jsonl
```

当前 Layer 2 主要实现代码在：

- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/extractor.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/llm-client.js`

runtime 接入点：

- `extensions/feishu-task-wiki/openclaw-lark/src/messaging/inbound/handler.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/messaging/inbound/comment-handler.js`

## 1. 当前输入

Layer 2 接收一个已通过 Layer 1 task binding 的 source-aware ingest context。

```ts
type CurrentLayer2Input = {
  accountId: string
  taskBinding: {
    task: {
      taskId: string
      taskKey: string
      taskTitle: string
    }
    binding: {
      taskId: string
      sourceType: "chat" | "thread" | "comment" | "doc"
      sourceId: string
      chatId?: string | null
      threadId?: string | null
      rootId?: string | null
    }
    sourceScope: string
    reason: string
  }

  sourceType: "chat" | "thread" | "comment" | "doc"
  sourceId: string
  chatId?: string | null
  threadId?: string | null
  rootId?: string | null

  messageId?: string | null
  senderId?: string | null
  senderName?: string | null
  content: string
  createTime?: string | null

  rootContent?: string | null
  replyChainContext?: string | null
  sourceLocator?: string | null
  cfg?: unknown
}
```

## 2. 当前 source session 语义

当前实现使用两层 id：

```text
source_session_id = task_id + "::" + source_scope
ingest_id = source_session_id + "::" + ingest_version
```

一个绑定 source 对应一个稳定 source session。

新消息不是新建平行 session，而是追加为一次 ingest。

## 3. 当前输出

`maybeIngestTaskSourceSession(...)` 的返回值形态：

```ts
type CurrentLayer2Result = {
  skipped: boolean
  reason?: string

  taskId?: string
  sourceSessionId?: string
  ingestId?: string
  ingestVersion?: number
  sessionDir?: string

  candidateEventCount?: number
  verificationJobsQueued?: number
  coreEntryCount?: number
  contextEntryCount?: number
}
```

## 4. 当前文件输出

当前会在 `stateDir/feishu-task-wiki/tasks/<task>/sessions/<session>/` 下维护：

```text
session-stream.json
session.md
metadata.yaml
pending_ingests.jsonl
evidence_spans.jsonl
candidate_events.jsonl
session_events.jsonl
verification_jobs.jsonl
```

文件语义：

- `session-stream.json`：记录 source scope 和 latest ingest version。
- `session.md`：累计式热工作视图。
- `metadata.yaml`：session 元数据快照。
- `pending_ingests.jsonl`：per-ingest ledger，记录本次 ingest 的状态与抽取结果。
- `evidence_spans.jsonl`：per-ingest evidence envelope，记录本次抽取用到的 trigger/context/support/core。
- `candidate_events.jsonl`：候选层，记录 LLM 抽取结果与 programmatic validation。
- `verification_jobs.jsonl`：verification 队列。
- `session_events.jsonl`：verified ledger，Layer 3 的正式事实输入。

## 5. Evidence 组织

`evidence_spans` 是外层证据容器，`context_entries` 只是其中一个字段。

- `trigger_entries`：当前新增消息，是本次 event 的触发来源。
- `core_entries`：最可能承载新事实的主证据集合。
- `context_entries`：解释代词、时间、否定、修正和前后文逻辑的邻近消息。
- `support_entries`：root、thread root、comment root 或上位背景。

## 6. Extract / Validate / Verify

```text
extractCandidateEventsWithLLM(...)
-> validateCandidateEvent(...)
-> runVerificationJobs(...)
-> verifyCandidateEvent(...)
```

`extractCandidateEventsWithLLM(...)` 负责从当前 evidence envelope 中提出 0 到 N 个 candidate events。

`validateCandidateEvent(...)` 负责 schema、typed fields、quote 对齐、atomicity 和基础可验证性。

`verifyCandidateEvent(...)` 负责语义确认，决定 candidate 是否进入 `session_events.jsonl`。

## 7. 当前一致性判断

已经符合当前实现：

- Layer 1 已负责 task binding，Layer 2 不重新猜 task。
- Layer 2 对每次 ingest 立即运行 LLM candidate extraction。
- candidate layer 和 verified layer 分文件。
- Layer 3 只消费 verified events。

仍需在评测里重点观察：

- candidate event 是否足够 atomic。
- quote 是否真实来自 observed source message。
- context 是否只用于消歧，没有越权生成 event。
- verified event 是否能正确投影到 task wiki current state。
