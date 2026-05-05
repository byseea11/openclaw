# 2026-05-01 Layer 2 Event 输入输出说明

这份文档专门描述 **Feishu Task Wiki 第二阶段 Layer 2 event** 的输入输出。

这里继续沿用和第一阶段一致的写法，分成四部分：

- **预期输入 / 预期输出**
  - 对齐 `2026-04-29-飞书 Task Wiki pipeline.md`
  - 对齐 `2026-04-29-event设计.md`
- **当前最终输入 / 当前最终输出**
  - 对齐现在已经落到代码里的真实接口与文件结构
- **真实 `lark-cli` 样本测试**
  - 使用真实飞书消息验证当前 Layer 2 的行为
- **一致性判断 / 当前缺口**
  - 明确哪些已经符合设计，哪些还需要继续收口

当前 Layer 2 主要实现代码在：

- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/extractor.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/llm-client.js`
- runtime 接入点：
  - `extensions/feishu-task-wiki/openclaw-lark/src/messaging/inbound/handler.js`
  - `extensions/feishu-task-wiki/openclaw-lark/src/messaging/inbound/comment-handler.js`

---

## 1. 预期输入

第二阶段 Layer 2 的目标不是再猜 task，也不是生成 wiki，而是：

```text
只要一个新的 source 已经绑定到某个 canonical task，
就把它作为一个稳定 source session 的新增 ingest 进入系统，
然后完成：

source session
  → Evidence Span
  → candidate_event
  → verification
  → verified session_event
```

### 1.1 预期最小输入对象

设计上，第二阶段应该接收一个 **已绑定 task 的 source-aware ingest context**：

```ts
type ExpectedLayer2Input = {
  account_id: string

  task_id: string
  task_binding: {
    task_id: string
    task_key: string
    source_scope: string
    reason: string
  }

  source_type: "chat" | "thread" | "comment" | "doc"
  source_id: string

  chat_id?: string | null
  thread_id?: string | null
  root_id?: string | null

  message_id?: string | null
  sender_id?: string | null
  sender_name?: string | null
  content: string
  create_time?: string | null

  root_content?: string | null
  reply_chain_context?: string | null
  source_locator?: string | null
}
```

### 1.2 这些字段各自的用途

- `task_id`
  - 指明第二层挂接到哪个 canonical task
- `task_binding`
  - 提供第一阶段已经确定好的绑定结果
- `source_type / source_id`
  - 指定这次新增内容属于哪个 source session
- `chat_id / thread_id / root_id`
  - 用于 session metadata、Core 构造和后续追溯
- `content`
  - 当前这次 ingest 的新增原文
- `root_content`
  - `thread/comment` 场景下补 root，保证 Core 不是只有 reply
- `reply_chain_context`
  - `comment` 场景下做少量消歧
- `source_locator`
  - 留给后续文档、评论、会议纪要等 source 的外部定位信息

### 1.3 预期 Layer 2 核心语义

设计上，这一层应该遵守：

1. 第一阶段已经定好 task，第二阶段不重新猜 task
2. 一个绑定 source 对应一个稳定 `source session`
3. 新内容不是新建平行 session，而是追加成一次 ingest
4. `chat / thread / comment / doc` 都可以成为合法 source session
5. `thread/comment` 的 Core 必须稳定包含 `root + 本次新增内容`
6. `Core` 触发 event，`Context` 只做消歧
7. `candidate_event` 和 `session_event` 必须分文件

---

## 2. 预期输出

### 2.1 预期主输出

设计上，第二阶段单次 ingest 应该输出：

```ts
type ExpectedLayer2Result = {
  skipped: boolean
  reason?: string

  task_id?: string
  source_session_id?: string
  ingest_id?: string
  ingest_version?: number

  candidate_event_count?: number
  verification_jobs_queued?: number
  core_entry_count?: number
  context_entry_count?: number
}
```

### 2.2 预期副产物

第二阶段结束后，应该在该 `source_session_id` 下稳定维护这些文件：

```text
session.md
metadata.yaml
pending_ingests.jsonl
evidence_spans.jsonl
candidate_events.jsonl
session_events.jsonl
verification_jobs.jsonl
```

### 2.3 这些输出各自的语义

- `session.md`
  - 当前 source session 的热工作视图
- `metadata.yaml`
  - 当前 session 的元数据快照
- `pending_ingests.jsonl`
  - 每次新增 ingest 的 ledger
- `evidence_spans.jsonl`
  - 每次 ingest 对应的 `trigger_entries + support_entries + context_entries`
- `candidate_events.jsonl`
  - 候选层，允许 `pending_verification / needs_review / rejected`
- `session_events.jsonl`
  - 只保存 `verified` 的正式 session_event
- `verification_jobs.jsonl`
  - verifier 的异步任务队列

---

## 3. 当前最终输入

当前代码里，第二阶段真正的主入口是：

- `maybeIngestTaskSourceSession(...)`

它的真实输入比设计最小对象更贴近 runtime：

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

### 3.1 当前 runtime 实际传入的字段

`message` 入口：

- `handler.js`
  - 会传入 `taskBinding`
  - 会传入当前 `content`
  - thread reply 场景下会额外传 `rootContent`

`comment` 入口：

- `comment-handler.js`
  - 会传入 `taskBinding`
  - 会传入当前 comment `content`
  - reply/comment thread 场景下会传 `rootContent`
  - 也会传 `replyChainContext`

### 3.2 当前 source session 语义

当前实现已经明确使用两层 id：

```text
source_session_id = task_id + "::" + source_scope
ingest_id = source_session_id + "::" + ingest_version
```

示例：

```text
task_id: task:FEISHU-231
source_scope: chat:oc_5a7d802471bd789a3afc994a18eec9f7
source_session_id: task:FEISHU-231::chat:oc_5a7d802471bd789a3afc994a18eec9f7
ingest_id: task:FEISHU-231::chat:oc_5a7d802471bd789a3afc994a18eec9f7::3
```

---

## 4. 当前最终输出

当前 `maybeIngestTaskSourceSession(...)` 的真实返回值是：

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

### 4.1 当前文件输出

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

其中：

- `session-stream.json`
  - 记录 `source_scope` 和 `latest_ingest_version`
- `session.md`
  - 已经是累计式热工作视图，不是单次 ingest 快照，也不是永久展开的全量原文页

### 4.2 当前 trigger / support / Context 规则

当前实现已经按 source type 分开：

- `chat`
  - `trigger_entries = 当前新增消息`
  - `support_entries = []`
  - `Context = 该 chat session 中更早的少量消息`
- `thread`
  - `trigger_entries = 当前 reply`
  - `support_entries = root message`
  - `Context = 同 thread 更早的 reply`
- `comment`
  - `trigger_entries = 当前 comment/reply`
  - `support_entries = root comment`
  - `Context = reply chain + 更早少量上下文`

并且当前 V1 已经做到：

```text
Current State Context 不进入第二层主线输入 contract
```

换句话说，当前第二层正式输入已经是：

```text
trigger_entries
+ support_entries
+ context_entries
```

其中：

- `trigger_entries`
  - 才允许正式触发 candidate event
- `support_entries`
  - 只补足 thread/comment 中 root 带来的语义背景
- `Context`
  - 只做额外消歧，不能单独触发 event

---

## 5. 真实 `lark-cli` 样本测试

### 5.1 测试时间

这次核对使用的是 **2026-05-01** 本地执行的真实 `lark-cli` 拉取结果。

### 5.2 实际使用的真实飞书数据

我使用了真实群聊：

```text
chat_id = oc_5a7d802471bd789a3afc994a18eec9f7
```

其中实际 root message 是：

```text
【cjy】创建任务 FEISHU-231：Q2 发布准备启动，目标发布时间暂定 5 月 5 日，请研发和运维一起评估。
```

同群 follow-up 样本：

```text
【wcy】研发评估完成，FEISHU-231 代码改动不大，但需要先确认灰度方案。
【xzy】我建议先不要在主群里把 5 月 5 日说死，运维 checklist 还没齐。
```

同 root 下 thread reply 样本：

```text
【Thread/wcy】研发侧补充：当前真正 blocker 不是代码，而是数据迁移窗口未确认。
【Thread/xzy】是的，而且回滚脚本还没有最终验收，所以 5 月 5 日只是乐观日期。
```

### 5.3 实际 Layer 2 结果

真实跑出来的绑定与 Layer 2 结果如下：

#### chat root 初始化

```json
{
  "taskId": "task:FEISHU-231",
  "taskKey": "FEISHU-231",
  "sourceScope": "chat:oc_5a7d802471bd789a3afc994a18eec9f7",
  "reason": "initialized"
}
```

#### chat source session

```json
{
  "sourceSessionId": "task:FEISHU-231::chat:oc_5a7d802471bd789a3afc994a18eec9f7",
  "latest_ingest_version": 3
}
```

并且：

- 第 1 次 ingest
  - `trigger_entries = [root message]`
  - `support_entries = []`
  - `context = []`
  - 抽出 2 条 candidate
  - 最终 2 条 `verified session_event`
- 第 2 / 3 次 ingest
  - `trigger_entries = [当前新增消息]`
  - `support_entries = []`
  - `context = [更早主群消息]`
  - 当前样本下没有抽出 candidate event
  - ingest 最终应停在 `processed_no_event`

#### thread source session

thread 首次进入时：

```json
{
  "taskId": "task:FEISHU-231",
  "sourceScope": "thread:omt_1a88154f474fdbe1",
  "reason": "thread_backfill"
}
```

后续同 thread 再进入时：

```json
{
  "taskId": "task:FEISHU-231",
  "sourceScope": "thread:omt_1a88154f474fdbe1",
  "reason": "thread_id"
}
```

thread source session：

```json
{
  "sourceSessionId": "task:FEISHU-231::thread:omt_1a88154f474fdbe1",
  "latest_ingest_version": 2
}
```

并且每次 thread ingest 的 `Core` 都已经稳定包含：

```json
[
  "om_x100b51ed96ab98acc4d4b4289681f8e",
  "当前 thread reply 的 message_id"
]
```

这说明：

```text
thread reply 进入时，reply 已经进入 trigger_entries，
root 已经进入 support_entries，
两者共同构成可理解的 Core 语义范围
```

### 5.4 实际产物摘要

真实样本跑出的 chat session 文件里，已经出现：

- `session.md`
- `metadata.yaml`
- `pending_ingests.jsonl`
- `evidence_spans.jsonl`
- `candidate_events.jsonl`
- `session_events.jsonl`
- `verification_jobs.jsonl`

其中 chat session 的正式 `session_events.jsonl` 样本是：

```text
conclusion_event
time_event
```

thread session 的正式 `session_events.jsonl` 样本是：

```text
status_event
...
```

并且当前实现已经额外满足：

- 没有 candidate 的 ingest 不会再进入 `pending_verification`
- 后续 thread reply ingest 不会重复把 root-derived `conclusion_event / time_event` 再写进 `session_events.jsonl`
- `session.md` 会在保留 root、近期内容、被事件引用内容的前提下做热视图 compaction

---

## 6. 一致性判断

### 6.1 当前已经和设计稿一致的点

下面这些点，当前实现已经和我们前面的 md 语义一致：

1. **第二层不重新猜 task**
   - 全部依赖第一阶段的 `task binding`
2. **source session 是稳定容器**
   - 同一个 chat / thread 复用同一个 `source_session_id`
3. **ingest 是追加**
   - 新内容进入时只递增 `ingest_version`
4. **chat 和 thread 可以绑定到同一个 task**
   - 但它们是两个不同 `source session`
5. **thread reply 的 Core 已经带 root**
   - 这点和修订后的设计完全一致
6. **候选层和正式层已经拆开**
   - `candidate_events.jsonl`
   - `session_events.jsonl`
7. **第三层可以直接只消费 `session_events.jsonl`**
   - 当前 contract 已经满足
8. **无 event ingest 不进入 verifier**
   - 当前已经改成 `processed_no_event`
9. **thread root-derived 正式事件已做去重**
   - reply ingest 不会重复写 root 上的 `conclusion/time`
10. **session.md 已是热工作视图**
   - 不再无限膨胀成全量原文页

### 6.2 当前和设计稿还不完全一致的点

当前实现离“完全满足第二层最终语义”还差几处：

1. **当前 live 验证只覆盖了 `chat + thread`**
   - `comment` 的代码路径已经接入第二层
   - 但这次真实 `lark-cli` 样本验证还没有覆盖到真实 comment source

2. **compaction 策略目前还是固定窗口参数**
   - 当前默认保留：
     - root
     - 最近 `N=20` 条 ingest
     - 最近 `M=10` 条 `processed_no_event`
     - 被 candidate/session event 引用的 entry
   - 这个策略已经可用，但后续还可以继续根据真实群流量调参

3. **`session-stream.json` 当前还是实现辅助文件**
   - 它现在负责记录：
     - `source_scope`
     - `latest_ingest_version`
   - 当前实现依赖它来维护稳定 source session 的递增 ingest 视图
   - 但它是否应该继续保留为长期正式契约，后续还需要再定

4. **`candidate_events.jsonl` 的人工 review / retry 流程还没有闭环**
   - 现在第二层已经能稳定分出：
     - `candidate_events.jsonl`
     - `session_events.jsonl`
   - 但对 `needs_review / rejected` 的后续人工处理、复核、重试写回流程还没有继续实现
   - 这不会阻塞第三层读取 `session_events.jsonl`
   - 但仍然属于第二层后续需要补完的验证和运营链路

---

## 7. 当前可直接作为第三层输入的内容

在当前实现下，第三层 Wiki 最应该直接消费的是：

```text
session_events.jsonl
```

并且可以依赖这些元信息：

- `task_id`
- `source_session_id`
- `ingest_version`
- `event_type`
- `core_entry_id`
- `evidence_quote`
- `verification.verdict = verified`

换句话说，当前第二层已经具备了第三层需要的正式事实输入层，只是还需要进一步收紧：

- comment live 样本验证
- compaction 固定窗口策略调优
- `session-stream.json` 是否继续保留为正式长期契约
- `candidate_events.jsonl` 的人工 review / retry 流程
