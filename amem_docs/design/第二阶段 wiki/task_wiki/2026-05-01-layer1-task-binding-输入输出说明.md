# 2026-05-01 Task Binding 输入输出说明

这份文档专门描述 **Feishu Task Wiki 第一阶段 `task binding`** 的输入输出。

这里分成两部分写：

- **预期输入 / 预期输出**
  - 对齐 `2026-04-29-飞书 Task Wiki pipeline.md` 的设计目标
- **当前最终输入 / 当前最终输出**
  - 对齐现在已经落到代码里的真实接口与持久化结构

当前实现代码主要在：

- `extensions/feishu-task-wiki/openclaw-lark/src/task-banding/task-binding.ts`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-banding/task-binding-store.js`
- `extensions/feishu-task-wiki/openclaw-lark/src/task-banding/task-routing.ts`
- runtime 接入点：
  - `extensions/feishu-task-wiki/openclaw-lark/src/channel/event-handlers.js`
  - `extensions/feishu-task-wiki/openclaw-lark/src/messaging/inbound/dispatch-context.js`

---

## 1. 预期输入

第一阶段 `task binding` 的目标不是抽 event，也不是生成 wiki，而是：

```text
给一段新的 Feishu source 输入，判断它属于哪个 canonical task；
如果能确定 task，就把这个 source 绑定到该 task；
如果暂时不能确定 task，就保持 conversation 路径，不要误绑。
```

### 1.1 预期最小输入对象

设计上，第一阶段应该接收一个 **source-aware inbound context**：

```ts
type ExpectedTaskBindingInput = {
  account_id: string
  source_type: "thread" | "chat" | "doc" | "comment"
  source_id: string

  chat_id?: string | null
  thread_id?: string | null
  root_id?: string | null

  root_message_text: string
  reply_texts?: string[]
  chat_title?: string | null
  doc_title?: string | null

  allow_initialize?: boolean
}
```

### 1.2 这些字段各自的用途

- `account_id`
  - 区分不同飞书账号 / tenant 下的绑定空间
- `source_type`
  - 当前 source 的类型
- `source_id`
  - 当前 source 的稳定标识
- `chat_id / thread_id / root_id`
  - 用于 source binding 查找和 backfill
- `root_message_text`
  - 用于第一次初始化时识别 `taskKey`
- `reply_texts`
  - 辅助补充任务语义
- `chat_title / doc_title`
  - 辅助补充任务语义
- `allow_initialize`
  - 是否允许这次输入触发首次 task 初始化

### 1.3 预期识别规则

设计上，这一阶段应该遵守：

1. 优先识别显式 `taskKey`
2. 只有识别到 `taskKey` 才允许初始化 task
3. 一个 source 的后续消息优先复用已有 binding
4. 同 `taskKey` 的不同 source 应归到同一个 canonical task
5. chat 先绑定后，后续长出 thread/root 时，要补 thread/root binding

当前 V1 默认锚点是任务号/任务名中的显式编号，例如：

- `FEISHU-231`
- `飞书-231`

---

## 2. 预期输出

### 2.1 预期主输出

设计上，第一阶段应该输出两层对象：

1. `task`
2. `binding`

也就是：

```ts
type ExpectedTaskBindingResult = {
  task: CanonicalTask
  binding: TaskSourceBinding
  reason:
    | "initialized"
    | "task_key"
    | "thread_id"
    | "root_id"
    | "chat_id"
    | "source_id"
    | "thread_backfill"
    | "root_backfill"
}
```

### 2.2 预期输出语义

- `task`
  - canonical task 主对象
  - 例如 `task:FEISHU-231`
- `binding`
  - 当前 source 到该 task 的绑定对象
- `reason`
  - 说明这次命中或创建的原因

### 2.3 预期副产物

第一阶段还应提供 routing 可直接消费的派生结果：

```ts
type ExpectedRuntimeDerivedOutput = {
  source_scope: string
  task_session_key: string | null
  task_queue_key: string
}
```

其中：

- `source_scope`
  - `thread:...` / `chat:...` / `doc:...`
- `task_session_key`
  - `agent:<agent_id>:feishu-task:<task_id>:<source_scope>`
- `task_queue_key`
  - `<account_id>:task:<task_id>:<source_scope>`

---

## 3. 当前最终输入

当前代码里，真正的初始化输入类型在：

- `extensions/feishu-task-wiki/openclaw-lark/src/task-banding/task-binding.ts`

具体是：

```ts
type TaskInitializationContext = {
  accountId: string
  sourceType: "thread" | "chat" | "doc" | "comment"
  sourceId: string
  chatId?: string | null
  threadId?: string | null
  rootId?: string | null
  rootMessageText: string
  replyTexts?: string[]
  chatTitle?: string | null
  docTitle?: string | null
  createdAt?: number
}
```

运行时 lookup 输入类型是：

```ts
type TaskBindingLookupInput = {
  accountId: string
  sourceType?: "thread" | "chat" | "doc" | "comment"
  sourceId?: string | null
  chatId?: string | null
  threadId?: string | null
  rootId?: string | null
  taskKey?: string | null
}
```

### 3.1 当前 runtime 实际传入的字段

在 `event-handlers.js` 和 `dispatch-context.js` 中，现在传入的是：

```ts
{
  accountId,
  agentId?,
  sourceType,
  sourceId,
  chatId,
  threadId,
  rootId,
  rootMessageText,
  allowInitialize
}
```

注意当前 V1 的实际行为：

- `allowInitialize=true`
  - 允许首次初始化 task
- `allowInitialize=false`
  - 只查 binding，不新建 task

### 3.2 当前 taskKey 识别输入

当前 `taskKey` 识别会读取：

- `rootMessageText`
- `replyTexts`
- `chatTitle`
- `docTitle`

当前默认支持的显式模式是：

- `FEISHU-231`
- `飞书-231`

如果没有识别到 `taskKey`：

- 当前实现会直接返回 `null`
- runtime 保持原 conversation session

---

## 4. 当前最终输出

当前 runtime 对外的统一输出函数是：

- `resolveTaskBindingForInbound(...)`

它的当前最终输出结构是：

```ts
type CurrentResolvedInboundTaskBinding = {
  task: {
    accountId: string
    taskId: string
    taskKey: string
    taskTitle: string
    taskSummary: string
    taskKeywords: string[]
    taskStatus: "active" | "inactive"
    createdAt: number
    updatedAt: number
  }
  binding: {
    accountId: string
    taskId: string
    sourceType: "thread" | "chat" | "doc" | "comment"
    sourceId: string
    chatId: string | null
    threadId: string | null
    rootId: string | null
    bindingStatus: "active" | "inactive"
    createdAt: number
    updatedAt: number
  }
  reason:
    | "initialized"
    | "task_key"
    | "thread_id"
    | "root_id"
    | "chat_id"
    | "source_id"
    | "thread_backfill"
    | "root_backfill"
  sourceScope: string
  taskSessionKey: string | null
  taskQueueKey: string
} | null
```

### 4.1 当前 `task` 的真实含义

当前 `task` 是 canonical 主对象，主要字段含义如下：

- `taskId`
  - canonical task 主键
  - 当前直接使用 `task:<taskKey>` 形式
  - 例如：`task:FEISHU-231`
- `taskKey`
  - 从显式任务号抽出来的规范化 key
  - 例如：`FEISHU-231`
- `taskTitle`
  - 当前用 root message 第一语句压缩得到
- `taskSummary`
  - 当前用 root message / chat title / reply 生成
- `taskKeywords`
  - 当前从输入文本中抽高频词

### 4.2 当前 `binding` 的真实含义

当前 `binding` 表示：

```text
这个 source（chat / thread / root / doc / comment）被映射到了哪个 task
```

它的关键点是：

- chat binding 和 thread binding 是两条独立记录
- thread/root 后续出现时，不会覆盖旧 chat binding
- 同一个 task 可以有多条 bindings

### 4.3 当前 `reason` 的真实含义

- `initialized`
  - 首次识别到 taskKey，并创建了 canonical task + binding
- `task_key`
  - 当前 source 没有已有 binding，但识别到 taskKey，并命中了已有 canonical task
- `thread_id`
  - 通过已有 `thread_id` 绑定命中
- `root_id`
  - 通过已有 `root_id` 绑定命中
- `chat_id`
  - 通过已有 `chat_id` 绑定命中
- `source_id`
  - 通过已有 `source_id` 绑定命中
- `thread_backfill`
  - chat 已绑定，当前新出现 `thread_id`，因此补建了一条 thread binding
- `root_backfill`
  - chat 已绑定，当前新出现 `root_id`，因此补建了一条 root binding

### 4.4 当前 runtime 派生输出

当前还会一起返回：

- `sourceScope`
- `taskSessionKey`
- `taskQueueKey`

示例：

```json
{
  "sourceScope": "thread:omt_231",
  "taskSessionKey": "agent:main:feishu-task:task:FEISHU-231:thread:omt_231",
  "taskQueueKey": "acct:task:task:FEISHU-231:thread:omt_231"
}
```

---

## 5. 当前持久化输入输出

### 5.1 当前持久化文件路径

当前第一阶段的 store 文件路径是：

```text
<OPENCLAW_STATE_DIR>/feishu-task-wiki/task-bindings.json
```

### 5.2 当前持久化输出结构

当前落盘结构已经改成：

```json
{
  "tasks": [
    {
      "accountId": "acct",
      "taskId": "task:FEISHU-231",
      "taskKey": "FEISHU-231",
      "taskTitle": "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5…",
      "taskSummary": "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      "taskKeywords": ["创建任务", "发布准备启动", "FEISHU-231"],
      "taskStatus": "active",
      "createdAt": 1777615332831,
      "updatedAt": 1777615332832
    }
  ],
  "bindings": [
    {
      "accountId": "acct",
      "taskId": "task:FEISHU-231",
      "sourceType": "chat",
      "sourceId": "chat:oc_a",
      "chatId": "oc_a",
      "threadId": null,
      "rootId": null,
      "bindingStatus": "active",
      "createdAt": 1777615332831,
      "updatedAt": 1777615332831
    },
    {
      "accountId": "acct",
      "taskId": "task:FEISHU-231",
      "sourceType": "thread",
      "sourceId": "thread:omt_231",
      "chatId": "oc_a",
      "threadId": "omt_231",
      "rootId": "om_root_231",
      "bindingStatus": "active",
      "createdAt": 1777615332831,
      "updatedAt": 1777615332831
    }
  ]
}
```

### 5.3 这份持久化结构当前表达的意思

它现在表达的是：

- `tasks`
  - canonical task 主表
- `bindings`
  - source 到 task 的映射表

也就是说：

```text
一个 task 可以对应多个 source bindings
一个 source binding 只对应一个 task
```

---

## 6. 当前 V1 已经固定的规则

### 6.1 当前必须成立

- 没有显式 `taskKey` 时，不初始化 task
- `taskId` 直接使用 canonical task key
- 不同 chat 只要识别到同一个 `taskKey`，就映射到同一个 task
- chat 先绑定后，后续长出 thread/root 时，保留 chat binding，并新增 thread/root binding

### 6.2 当前还没有做的事

这一阶段目前**没有**做：

- 自由语义推断 task
- event 抽取
- session file 物化
- `session_wiki.md / index.md / task_wiki.md` 生成

所以当前这一层的职责仍然很纯粹：

```text
确定 canonical task
确定 source -> task 绑定
给 runtime 提供 task-scoped session / queue key
```

---

## 7. 推荐后续使用方式

后续第二阶段 event 抽取接入时，应该直接消费：

1. `task`
2. `binding`
3. `sourceScope`

这里要明确第二层的正确语义：

```text
第二层消费的是 source session + ingest，
不是“每次新建一个全新的 session”。
```

推荐依赖顺序如下：

```text
task binding
  -> source session
  -> ingest
  -> evidence span
  -> candidate_events.jsonl
  -> session_events.jsonl
```

也就是说，后续不要再从原始 chat/thread 直接猜 task，而是直接使用第一阶段已经稳定落下来的：

- `task.taskId`
- `binding.sourceId`
- `binding.threadId/rootId/chatId`

这也是为什么这一步需要先把输入输出写清楚。
