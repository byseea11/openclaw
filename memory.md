# 企业级长程协作 Memory 系统：数据集、技术依据与落地方案

## 1. 这个项目应该先讲成什么

建议把课题二收敛成一句话：

`基于 OpenClaw 的企业长程协作 Memory Engine：把飞书办公中的群聊、会议、文档、任务、日程和工具结果统一成可检索、可更新、可压缩、可引用的事件式记忆。`

这句话里有三个重点：

1. `基于 OpenClaw`
   - OpenClaw 是运行时和 agent 框架。
   - 飞书妙搭可以作为用户入口和展示入口。
   - 你的核心工作不是重新做一个聊天机器人，而是在 OpenClaw 的 memory/context 层做增强。

2. `企业长程协作`
   - 不是普通聊天记忆。
   - 重点是跨部门、跨会话、跨文档、跨工具状态的连续协作。
   - 典型问题是“谁负责、什么时候改了、为什么改、现在最新状态是什么、证据来自哪里”。

3. `Memory Engine`
   - 不只是一个向量库。
   - 它至少要包含数据定义、记忆抽取、检索、冲突更新、上下文压缩、证据重排、工具结果写回和评测。

所以这个项目最终可以写成：

`面向企业办公场景的 OpenClaw query-aware memory context engine`

---

## 2. 企业级跨长程协作到底有什么问题

企业协作里的“失忆”不是简单忘记上一句话，而是信息在长时间、多工具、多角色、多版本里断掉。

### 2.1 信息分散

一个项目的真实上下文通常分散在：

- 飞书群聊
- 私聊
- 会议纪要
- 文档正文
- 文档评论
- 任务
- 日程
- 审批
- 外部工具查询结果

普通 agent 如果只看当前对话 session，就会漏掉会议纪要、文档评论、任务状态和历史工具结果。

### 2.2 最近窗口不等于长期记忆

OpenClaw 里的 session transcript 能保存当前会话历史，但默认的上下文构造仍然会受 token budget 限制。只保留最近若干轮可以避免上下文爆炸，却不能保证召回当前问题真正需要的旧证据。

企业问题经常是：

`用户今天问的问题，需要召回两周前会议里的决定、上周群聊里的变更、昨天任务系统里的负责人。`

这不是 recent-window 能稳定解决的。

### 2.3 时间更新和旧信息污染

企业记忆最难的是状态会变：

- 原计划 4 月 20 日上线，后来延期到 4 月 25 日。
- 原负责人是张三，后来转给李四。
- 风险上周还是 open，本周已经 resolved。
- PRD v1 的需求被 PRD v2 覆盖。

如果 memory 只是保存所有 chunk，模型很容易把旧信息当成最新信息。

所以企业记忆必须显式表达：

- `valid_from`
- `valid_until`
- `status`
- `supersedes`
- `superseded_by`
- `source_time`
- `source_ref`

### 2.4 责任链断层

企业协作问答经常不是问事实，而是问责任链：

- 谁负责这个风险？
- 谁上次承诺了截止时间？
- 哪个部门还没确认？
- 下一步应该找谁？
- 这个决策是谁在什么时候定的？

因此数据结构里必须保留 `actor`、`participants`、`department`、`role`、`assignee`、`watchers`、`decision_owner`。

### 2.5 工具状态不可复用

企业 agent 会频繁调用工具：

- 查飞书日程
- 查任务
- 搜文档
- 写评论
- 发提醒
- 创建待办

如果工具结果没有进入记忆，下一轮 agent 就会出现：

- 重复调用工具
- 忘记刚查过的会议
- 工具参数补全错误
- 无法连续执行任务

这正好对应 ToolSandbox 强调的 stateful tool execution 和 implicit state dependencies。

### 2.6 长上下文不是万能

把全部历史塞进上下文有三个问题：

- token 成本高
- latency 高
- 关键信息放在中间时模型不一定能用好

`Lost in the Middle` 说明模型对长上下文中间位置的信息利用较弱。`LongLLMLingua` 说明长上下文需要 question-aware compression 和重排。  

所以企业 memory engine 不能只做“召回更多”，还要做“召回正确、压缩正确、放置正确”。

### 2.7 证据可审计和权限边界

企业场景里，答案最好能说明：

- 来源是哪条消息、哪个文档、哪次会议
- 时间是什么
- 是谁说的
- 是否来自用户有权限访问的空间
- 是否是最新有效信息

这也是为什么数据结构里不能只有 `text`，必须有 `source_type`、`source_id`、`visibility`、`source_ref`、`confidence`。

---

## 3. 对应技术依据，以及和本项目的关系

这里不要把论文和文档写成“我可能会用到”。应该按下面方式写：

`这个技术依据解决了什么问题 -> 它和我的项目哪一部分相关 -> 我具体利用它的哪一部分。`

### 3.1 OpenClaw Memory / Context Engine

依据：

- [OpenClaw Memory Overview](https://docs.openclaw.ai/concepts/memory)
- [OpenClaw Context Engine](https://docs.openclaw.ai/concepts/context-engine)
- [OpenClaw Context](https://docs.openclaw.ai/concepts/context)
- [OpenClaw Feishu Channel](https://docs.openclaw.ai/channels/feishu)

相关部分是什么：

OpenClaw 明确区分 `context` 和 `memory`：

- `context` 是每次模型调用时实际发送给模型的内容。
- `memory` 是保存在磁盘或 memory backend 里的长期信息。
- memory plugin 提供检索能力。
- context engine 决定每轮哪些消息、记忆和工具结果应该进入模型上下文。

OpenClaw 的 context engine 有几个关键生命周期：

- `ingest`: 新消息进入 session 时索引或存储。
- `assemble`: 每次模型调用前构造上下文。
- `compact`: 上下文满时做摘要或压缩。
- `afterTurn`: 每轮结束后更新索引或状态。

可以利用的部分是什么：

你的项目应该把核心能力放在 `ContextEngine`，而不是只写一个外部 RAG 脚本。

推荐对应关系：

1. `ingest`
   - 接收飞书消息、文档评论、任务变更、工具结果。
   - 转成统一的 `RawOfficeEvent`。

2. `afterTurn`
   - 把本轮用户输入、模型回答、工具调用结果写成 `MemoryEvidence`。
   - 记录哪些记忆被召回、是否被使用、是否需要晋升。

3. `assemble`
   - 根据当前 query 做 query-aware retrieval。
   - 做时间冲突过滤。
   - 做 extractive compression。
   - 做 head-tail evidence reordering。
   - 返回 `systemPromptAddition` 或重排后的 messages。

4. `compact`
   - 不只是摘要旧聊天，而是把旧聊天拆成事件式记忆，再保留最近 live context。

为什么它重要：

OpenClaw 已经有 memory_search、memory_get、Markdown memory、SQLite/hybrid search 和 Feishu channel。你的创新不应该是“接入记忆”，而应该是：

`让 OpenClaw 在企业长程协作场景下更会选择、压缩、更新和放置记忆。`

### 3.2 飞书/Lark 消息与办公对象结构

依据：

- [飞书获取会话历史消息](https://open.feishu.cn/document/server-docs/im-v1/message/list)
- [飞书接收消息事件](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)
- [飞书发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)
- [OpenClaw Feishu Channel: supported messages and Drive comments](https://docs.openclaw.ai/channels/feishu)

相关部分是什么：

飞书消息不是只有文本。真实消息至少包含：

- 消息 ID
- 根消息 ID
- 父消息 ID
- 消息类型
- 创建时间
- 更新时间
- 是否撤回
- 是否编辑
- 所属会话
- 发送者
- 消息正文
- mentions
- thread/reply 关系

OpenClaw 的 Feishu channel 还说明它可以接收文本、富文本、图片、文件、音频、视频、贴纸，并且 Drive comment 事件会带评论文本、发送者、文档元信息和评论线程上下文。

可以利用的部分是什么：

这说明你的 mock 数据集不能只写：

```json
{"text": "项目延期到 4 月 25 日"}
```

而要保留真实办公协作需要的最小结构：

```json
{
  "event_id": "chat_20260410_1432_001",
  "source_type": "feishu_chat",
  "source_id": "oc_mock_project_group",
  "source_name": "星桥CRM上线项目群",
  "thread_id": "thread_launch_risk",
  "parent_id": null,
  "timestamp": "2026-04-10T14:32:00+08:00",
  "updated_at": null,
  "deleted": false,
  "actor": {
    "id": "u_legal_wangmin",
    "name": "王敏",
    "department": "法务部",
    "role": "法务负责人"
  },
  "content_type": "text",
  "content": "数据出境条款还没确认，不能按 4 月 20 日上线，建议延期到 4 月 25 日。",
  "mentions": ["u_pm_lixiao"],
  "attachments": [],
  "visibility": ["产品部", "研发部", "法务部"]
}
```

为什么它重要：

企业 memory 的答案需要回到来源。没有 `source_id`、`timestamp`、`actor`、`thread_id`，你就无法回答：

- 这是谁说的？
- 是哪个群里说的？
- 是回复哪条消息？
- 这个信息是不是后来被编辑或撤回？
- 用户是否有权限看到？

所以这些不是“为了好看加字段”，而是企业记忆可追溯、可更新、可审计的基础。

### 3.3 LongMemEval

依据：

- [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://proceedings.iclr.cc/paper_files/paper/2025/hash/d813d324dbf0598bbdc9c8e79740ed01-Abstract-Conference.html)

相关部分是什么：

LongMemEval 把长期记忆能力拆成五类：

1. `information extraction`
2. `multi-session reasoning`
3. `temporal reasoning`
4. `knowledge updates`
5. `abstention`

它还把 memory system 拆成三阶段：

1. `indexing`
2. `retrieval`
3. `reading`

并提出几个直接相关的优化：

- session decomposition
- fact-augmented key expansion
- time-aware query expansion

可以利用的部分是什么：

你的企业数据集和评测应该直接复用这个能力分类，但改成办公语言：

1. `information extraction`
   - 从会议、群聊、任务中抽取负责人、时间、风险、结论。

2. `multi-session reasoning`
   - 需要跨多个会议和聊天 session 才能回答。

3. `temporal reasoning`
   - 判断最新 deadline、变更顺序、风险状态。

4. `knowledge updates`
   - 新信息覆盖旧信息，比如延期、换负责人、风险关闭。

5. `abstention`
   - 记忆里没有证据时不能乱答。

在系统上，对应你的三个模块：

- `indexing`: Office event -> MemoryEvidence
- `retrieval`: query-aware selector
- `reading`: compressor + evidence reordering + final answer

为什么它重要：

LongMemEval 可以帮你避免一个问题：只展示几个 demo 问答但没有标准评测。  
你可以明确说自建评测集参考 LongMemEval 的能力划分，并额外加入企业协作特有的 `responsibility tracking` 和 `tool result reuse`。

### 3.4 LoCoMo

依据：

- [Evaluating Very Long-Term Conversational Memory of LLM Agents, ACL 2024](https://aclanthology.org/2024.acl-long.747/)
- [LoCoMo project page](https://snap-research.github.io/locomo/)

相关部分是什么：

LoCoMo 关注 very long-term dialogue memory。它的数据包含多 session 长对话，并基于 persona 和 temporal event graph 构造对话。它的评测包括：

- question answering
- event summarization
- multi-modal dialogue generation

它证明了一个关键事实：

`长上下文 LLM 和 RAG 有帮助，但在长程时间和因果一致性上仍然明显不足。`

可以利用的部分是什么：

你的飞书 mock 数据集可以借鉴 LoCoMo 的构造方式：

1. 先定义项目真值图：
   - 人员
   - 部门
   - 事件
   - 决策
   - 时间线
   - 因果关系
   - 冲突更新

2. 再把真值图渲染成办公数据：
   - 群聊
   - 会议纪要
   - 文档
   - 任务
   - 日程
   - 评论线程

3. 最后从真值图生成 gold answer 和 gold evidence。

为什么它重要：

如果你直接让模型生成一堆聊天记录，数据会很像但不可评测。  
如果你先有 event graph，再生成办公记录，你就能知道每个问题的正确答案和证据在哪里。

### 3.5 ToolSandbox

依据：

- [ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM Tool Use Capabilities](https://machinelearning.apple.com/research/toolsandbox-stateful-conversational-llm-benchmark)

相关部分是什么：

ToolSandbox 关注 stateful tool execution、implicit state dependencies、on-policy conversational evaluation。它强调真实工具任务不是一次性 REST API 调用，而是多轮状态会变化、工具之间有隐含依赖。

可以利用的部分是什么：

你的企业 memory engine 需要专门设计 `ToolResultMemory`：

```json
{
  "tool_call_id": "tool_calendar_20260413_001",
  "tool_name": "feishu_calendar.search_events",
  "arguments": {
    "date_range": "2026-04-13..2026-04-19",
    "keyword": "星桥CRM"
  },
  "result_summary": "本周有 2 个项目评审会议：4 月 15 日上线评审，4 月 17 日法务复核。",
  "result_entities": ["星桥CRM", "上线评审", "法务复核"],
  "source_turn": "session_demo_001:turn_05",
  "timestamp": "2026-04-13T10:20:00+08:00",
  "status": "success"
}
```

然后后续用户问：

`基于刚才查到的会议，帮我写提醒。`

系统不应该重新猜，而应该从 tool result memory 召回刚才的结果。

为什么它重要：

飞书办公 agent 的价值很大一部分来自工具调用。如果工具结果不进入记忆，多轮任务就会断。

### 3.6 Tau2-Bench

依据：

- [tau2-bench: Evaluating Conversational Agents in a Dual-Control Environment](https://huggingface.co/papers/2506.07982)

相关部分是什么：

Tau2-Bench 强调 dual-control environment：不只是 agent 用工具，用户也会改变共享世界状态。真实企业办公也是这样：

- 用户可能手动改了任务截止时间。
- 同事可能在文档评论里补充了新结论。
- 负责人可能在群里更新状态。
- agent 也可能创建任务、发提醒、写评论。

可以利用的部分是什么：

你的 Demo 和评测里应该包含“共享状态被用户或外部事件改变”的 case：

```text
旧状态：上线时间 2026-04-20。
外部事件：运营在群里说因为合规风险延期到 2026-04-25。
用户问题：现在上线时间是哪天？
```

评测时不只看回答，还看系统是否正确使用最新共享状态。

为什么它重要：

这能把你的项目从“记忆问答”提升到“企业协作状态管理”。

### 3.7 LongLLMLingua

依据：

- [LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via Prompt Compression](https://www.microsoft.com/en-us/research/publication/longllmlingua-accelerating-and-enhancing-llms-in-long-context-scenarios-via-prompt-compression/)
- [LongLLMLingua project](https://llmlingua.com/longllmlingua.html)

相关部分是什么：

LongLLMLingua 关注 long-context 场景下的 prompt compression。它的关键思想是：

- 长上下文会带来成本、延迟和效果问题。
- 压缩不能和问题无关。
- 应该做 question-aware compression。
- 文档或证据的排序会影响最终效果。

可以利用的部分是什么：

你的 compressor 不应该做普通摘要，而应该做：

```text
query-aware extractive compression
```

也就是：

- 当前 query 问负责人，就保留负责人、部门、任务、截止时间。
- 当前 query 问上线日期，就保留旧日期、新日期、变更原因、时间戳。
- 当前 query 问 blocker，就保留风险、状态、owner、source。

为什么它重要：

你的实验里 prompt tokens 从 46288 降到 10099，QA F1 从 0.157 到 0.294，最适合用 LongLLMLingua 解释。

### 3.8 Lost in the Middle

依据：

- [Lost in the Middle: How Language Models Use Long Contexts](https://aclanthology.org/2024.tacl-1.9/)

相关部分是什么：

这篇证明模型对长上下文中间位置的信息利用不好。关键信息放在开头或结尾，通常比放在中间更容易被模型使用。

可以利用的部分是什么：

你的 evidence placement 可以设计成：

1. `head`
   - 放短的任务状态摘要。
   - 放最新有效事实。

2. `middle`
   - 放必要的最近 live context。
   - 不堆大量低相关历史。

3. `tail`
   - 放和当前问题最相关的 1 到 3 条证据。
   - 尽量靠近 user prompt。

为什么它重要：

这能解释为什么你不仅做 retrieval，还做 head-tail evidence reordering。

### 3.9 GraphRAG / LightRAG

依据：

- [GraphRAG: Improving Global Search via Dynamic Community Selection](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/)
- [LightRAG: Simple and Fast Retrieval-Augmented Generation](https://huggingface.co/papers/2410.05779)

相关部分是什么：

企业协作不是扁平文本检索。很多问题需要跨实体和关系：

- 人和任务的关系
- 任务和风险的关系
- 风险和上线时间的关系
- 文档版本和决策的关系
- 部门和负责人关系

可以利用的部分是什么：

第一版不一定要做完整 GraphRAG，但数据结构要为关系检索留口子：

- `entities`
- `relations`
- `participants`
- `project_id`
- `task_id`
- `decision_id`
- `supersedes`
- `depends_on`

为什么它重要：

如果第一版数据结构没有这些字段，后面想升级成图检索会很痛苦。

### 3.10 SCBench / KV-cache-aware context layout

依据：

- [SCBench: A KV Cache-Centric Analysis of Long-Context Methods](https://proceedings.iclr.cc/paper_files/paper/2025/hash/a540b17fb2295c736d5afd6c507acf66-Abstract-Conference.html)

相关部分是什么：

SCBench 从 KV cache 生命周期看 long-context 方法，包括 KV generation、compression、retrieval、loading。它说明长上下文系统不只要关心检索，还要关心上下文如何被反复复用。

可以利用的部分是什么：

如果你使用 API 模型，不要声称自己直接控制模型内部 KV tensor。更稳的说法是：

`KV-cache-aware / prompt-cache-aware context organization`

具体做法：

- 稳定系统 prompt、工具说明、memory schema 放 prefix。
- 动态 evidence 放 cache boundary 后面。
- evidence 排序 deterministic。
- 每条 evidence 用稳定 key 标识。

为什么它重要：

这能让“卡帕西的 KV”变成可实现、可评测的工程点，而不是一个模糊概念。

---

## 4. 数据集应该是什么格式

建议采用三层数据格式：

1. `RawOfficeEvent`
   - 模拟飞书真实办公事件。
   - 尽量贴近消息、文档、任务、日程、评论和工具结果的原始结构。

2. `MemoryEvidence`
   - 从 RawOfficeEvent 抽取出的可检索、可更新、可引用记忆单元。
   - 这是 memory engine 的核心存储对象。

3. `EvalCase`
   - 用来评测检索和回答。
   - 包含问题、答案、gold evidence、能力类型和拒答标注。

不要只做一层 `messages.json`。  
一层数据只能演示聊天，不能支撑企业级记忆评测。

---

## 5. RawOfficeEvent：真实数据结构必须包含什么

RawOfficeEvent 的目标是：

`最大程度保留飞书办公对象的原始语义，保证后面可以追溯、更新、权限过滤和评测。`

### 5.1 必须包含的基础字段

```json
{
  "event_id": "chat_20260410_1432_001",
  "source_type": "feishu_chat",
  "source_id": "oc_mock_project_group",
  "source_name": "星桥CRM上线项目群",
  "timestamp": "2026-04-10T14:32:00+08:00",
  "actor": {
    "id": "u_legal_wangmin",
    "name": "王敏",
    "department": "法务部",
    "role": "法务负责人"
  },
  "content_type": "text",
  "content": "数据出境条款还没确认，不能按 4 月 20 日上线，建议延期到 4 月 25 日。"
}
```

这些字段是必须的：

1. `event_id`
   - 用于唯一定位事件。
   - 对应飞书里的 `message_id`、doc comment id、task id、calendar event id。
   - 没有它就无法做 evidence citation 和 gold evidence 标注。

2. `source_type`
   - 区分来源类型。
   - 例如 `feishu_chat`、`feishu_doc`、`feishu_doc_comment`、`feishu_task`、`feishu_calendar`、`tool_result`。
   - 不同来源的可信度、更新规则和压缩策略不同。

3. `source_id`
   - 对应飞书群 ID、文档 token、任务 ID、日程 ID。
   - 用于权限、回溯和同一来源聚合。

4. `source_name`
   - 给模型和用户看的来源名。
   - 例如项目群名、会议名、文档标题。

5. `timestamp`
   - 长程记忆必须有时间。
   - 用于 temporal reasoning、knowledge update、最新状态判断。

6. `actor`
   - 企业问题经常问“谁说的、谁负责、谁确认的”。
   - 最少要有 id、name。
   - 建议加 department、role。

7. `content_type`
   - 飞书支持 text、post、image、file、audio、media、sticker、interactive 等。
   - Demo 第一版可以只用 text/markdown/json，但 schema 要保留类型。

8. `content`
   - 原始文本或可读内容。
   - 后续抽取 MemoryEvidence 的基础。

### 5.2 必须包含的线程和会话字段

```json
{
  "thread_id": "thread_launch_risk",
  "root_id": "chat_20260410_1400_000",
  "parent_id": "chat_20260410_1410_001",
  "session_id": "project_week2_legal_review",
  "project_id": "proj_starbridge_crm"
}
```

原因：

1. `thread_id / root_id / parent_id`
   - 飞书消息天然有回复关系。
   - 文档评论也有 comment thread。
   - 没有线程关系，agent 很难理解某句话是在回复什么。

2. `session_id`
   - 对应一次会议、一天群聊、一个文档评论线程、一次工具交互。
   - LongMemEval 和 LoCoMo 都说明多 session 是长期记忆评测的核心。

3. `project_id`
   - 企业记忆通常按项目隔离。
   - 没有 project_id，跨项目检索会污染上下文。

### 5.3 必须包含的更新状态字段

```json
{
  "created_at": "2026-04-10T14:32:00+08:00",
  "updated_at": null,
  "deleted": false,
  "version": 1
}
```

原因：

飞书消息可能被编辑或撤回，文档也有版本变化。企业记忆必须知道一个信息是否仍然有效。

这些字段用于：

- 过滤被撤回信息
- 识别编辑后的新内容
- 判断文档版本
- 做知识更新评测

### 5.4 必须包含的权限字段

```json
{
  "visibility": ["产品部", "研发部", "法务部"],
  "tenant_id": "tenant_mock",
  "access_policy": "project_members"
}
```

原因：

企业 memory 不能把所有信息都暴露给所有用户。即使 Demo 用 mock 数据，也要在 schema 里体现权限边界。

第一版可以不实现复杂权限系统，但至少要做到：

- 每条事件有 `visibility`
- 检索时可以按用户部门或项目成员过滤
- 评测报告说明权限是 schema-level 支持

### 5.5 不同办公对象的最小 raw schema

#### A. 群聊消息

```json
{
  "event_id": "msg_001",
  "source_type": "feishu_chat",
  "source_id": "oc_project_group",
  "source_name": "星桥CRM上线项目群",
  "thread_id": "thread_risk",
  "parent_id": null,
  "timestamp": "2026-04-10T14:32:00+08:00",
  "actor": {"id": "u_001", "name": "王敏", "department": "法务部"},
  "content_type": "text",
  "content": "数据出境条款未确认，建议延期上线。",
  "mentions": ["u_pm_lixiao"],
  "visibility": ["项目组"]
}
```

#### B. 会议纪要

```json
{
  "event_id": "meeting_legal_20260409",
  "source_type": "feishu_meeting_note",
  "source_id": "doc_meeting_legal_20260409",
  "source_name": "4月9日法务评审纪要",
  "timestamp": "2026-04-09T16:00:00+08:00",
  "actor": {"id": "u_legal_wangmin", "name": "王敏", "department": "法务部"},
  "participants": ["王敏", "李晓", "陈锐"],
  "content_type": "markdown",
  "content": "结论：数据出境条款未确认前不建议上线。待办：王敏 4 月 16 日前完成合规确认。",
  "visibility": ["项目组", "法务部"]
}
```

#### C. 文档

```json
{
  "event_id": "doc_prd_v2",
  "source_type": "feishu_doc",
  "source_id": "doc_prd_starbridge",
  "source_name": "星桥CRM PRD v2",
  "timestamp": "2026-04-11T11:00:00+08:00",
  "actor": {"id": "u_pm_lixiao", "name": "李晓", "department": "产品部"},
  "content_type": "markdown",
  "content": "v2 变更：上线范围缩小，企业微信同步能力延后到二期。",
  "version": 2,
  "visibility": ["项目组"]
}
```

#### D. 文档评论

```json
{
  "event_id": "comment_001",
  "source_type": "feishu_doc_comment",
  "source_id": "doc_prd_starbridge",
  "source_name": "星桥CRM PRD v2 评论",
  "thread_id": "comment_thread_scope",
  "timestamp": "2026-04-11T13:20:00+08:00",
  "actor": {"id": "u_rd_chenrui", "name": "陈锐", "department": "研发部"},
  "content_type": "text",
  "content": "接口排期不支持本期做企业微信同步，建议延后。",
  "visibility": ["项目组"]
}
```

#### E. 任务

```json
{
  "event_id": "task_legal_confirm",
  "source_type": "feishu_task",
  "source_id": "task_legal_confirm",
  "source_name": "完成数据出境条款确认",
  "timestamp": "2026-04-10T15:00:00+08:00",
  "actor": {"id": "u_pm_lixiao", "name": "李晓", "department": "产品部"},
  "assignee": {"id": "u_legal_wangmin", "name": "王敏", "department": "法务部"},
  "due_at": "2026-04-16T18:00:00+08:00",
  "status": "open",
  "content_type": "task",
  "content": "王敏负责在 4 月 16 日前完成数据出境条款确认。",
  "visibility": ["项目组", "法务部"]
}
```

#### F. 日程

```json
{
  "event_id": "calendar_launch_review_20260415",
  "source_type": "feishu_calendar",
  "source_id": "cal_launch_review_20260415",
  "source_name": "星桥CRM上线评审",
  "timestamp": "2026-04-13T10:20:00+08:00",
  "start_at": "2026-04-15T10:00:00+08:00",
  "end_at": "2026-04-15T11:00:00+08:00",
  "participants": ["李晓", "陈锐", "王敏", "周岚"],
  "content_type": "calendar_event",
  "content": "星桥CRM上线评审，确认上线范围、法务风险和运营准备。",
  "visibility": ["项目组"]
}
```

#### G. 工具结果

```json
{
  "event_id": "tool_calendar_search_001",
  "source_type": "tool_result",
  "source_id": "tool_call_001",
  "source_name": "feishu_calendar.search_events",
  "timestamp": "2026-04-13T10:20:00+08:00",
  "actor": {"id": "agent_openclaw", "name": "OpenClaw Agent"},
  "tool_name": "feishu_calendar.search_events",
  "tool_args": {
    "keyword": "星桥CRM",
    "date_range": "2026-04-13..2026-04-19"
  },
  "tool_status": "success",
  "content_type": "tool_result",
  "content": "本周有 2 个项目评审会议：4 月 15 日上线评审，4 月 17 日法务复核。",
  "visibility": ["项目组"]
}
```

---

## 6. RawOfficeEvent 必须扩展什么

真实 API 字段只能说明“发生了什么”。  
但 memory engine 还需要知道“这个事件在记忆系统里怎么用”。

所以必须扩展这些字段：

### 6.1 `memory_intent`

```json
{
  "memory_intent": ["decision", "risk", "deadline_update"]
}
```

原因：

模型问“当前 blocker”时，风险类记忆应该优先；问“谁负责”时，任务和 owner 记忆应该优先。

第一版可以用规则或 LLM 抽取：

- `decision`
- `risk`
- `task`
- `deadline`
- `owner`
- `preference`
- `tool_result`
- `status_update`

### 6.2 `entities`

```json
{
  "entities": ["星桥CRM", "数据出境条款", "上线时间", "王敏"]
}
```

原因：

企业问题经常围绕实体展开。  
没有 entities，检索只能靠全文相似度，容易漏召回。

### 6.3 `relations`

```json
{
  "relations": [
    {
      "subject": "王敏",
      "predicate": "负责",
      "object": "数据出境条款确认"
    },
    {
      "subject": "数据出境条款未确认",
      "predicate": "导致",
      "object": "上线延期"
    }
  ]
}
```

原因：

跨部门协作的问题常常是关系问题，而不是文本相似问题。

例如：

`因为哪个风险导致上线延期？`

需要知道 `risk -> causes -> delay`。

### 6.4 `validity`

```json
{
  "validity": {
    "status": "active",
    "valid_from": "2026-04-10",
    "valid_until": null,
    "supersedes": ["mem_launch_date_20260420"],
    "superseded_by": []
  }
}
```

原因：

企业记忆必须处理更新和冲突。  
没有 validity，旧 deadline、新 deadline、旧负责人、新负责人会一起被召回，模型很容易答错。

### 6.5 `evidence_quality`

```json
{
  "evidence_quality": {
    "confidence": 0.88,
    "importance": 0.92,
    "freshness": 0.95,
    "source_authority": 0.9
  }
}
```

原因：

同一句话来自不同来源，权重不同：

- 法务负责人在会议纪要里的结论，权重高。
- 群聊里某个人的猜测，权重低。
- 任务系统里的 assignee，通常比聊天里的“你来跟一下”更结构化。

### 6.6 `retrieval_keys`

```json
{
  "retrieval_keys": [
    "星桥CRM 上线时间",
    "数据出境条款 风险",
    "法务 王敏 4月16日",
    "上线延期 4月25日"
  ]
}
```

原因：

LongMemEval 里的 fact-augmented key expansion 可以迁移到这里。  
检索时不只查原文，还查这些面向问题的 key。

### 6.7 `source_ref`

```json
{
  "source_ref": {
    "event_id": "chat_20260410_1432_001",
    "source_type": "feishu_chat",
    "source_name": "星桥CRM上线项目群",
    "timestamp": "2026-04-10T14:32:00+08:00",
    "actor_name": "王敏"
  }
}
```

原因：

最终回答要能给证据：

`来源：4 月 10 日 14:32，星桥CRM上线项目群，法务王敏。`

没有 source_ref，Demo 就只能“看起来会答”，不够企业级。

---

## 7. MemoryEvidence：记忆系统真正应该存什么

RawOfficeEvent 是原始事件，MemoryEvidence 是可检索记忆。

推荐 schema：

```json
{
  "memory_id": "mem_risk_legal_cross_border_001",
  "project_id": "proj_starbridge_crm",
  "memory_type": "risk_update",
  "proposition": "星桥CRM项目因数据出境条款未确认，建议上线时间从 2026-04-20 延期到 2026-04-25。",
  "summary": "法务风险导致上线延期到 4 月 25 日。",
  "entities": ["星桥CRM", "数据出境条款", "上线时间"],
  "participants": ["王敏", "李晓"],
  "departments": ["法务部", "产品部"],
  "relations": [
    {
      "subject": "数据出境条款未确认",
      "predicate": "causes",
      "object": "上线延期"
    }
  ],
  "time": {
    "event_time": "2026-04-10T14:32:00+08:00",
    "valid_from": "2026-04-10",
    "valid_until": null
  },
  "status": "active",
  "supersedes": ["mem_launch_date_20260420"],
  "source_refs": [
    {
      "event_id": "chat_20260410_1432_001",
      "source_type": "feishu_chat",
      "source_name": "星桥CRM上线项目群",
      "timestamp": "2026-04-10T14:32:00+08:00",
      "actor_name": "王敏"
    }
  ],
  "retrieval_keys": [
    "星桥CRM 上线延期",
    "数据出境条款 法务风险",
    "上线时间 4月25日"
  ],
  "importance": 0.92,
  "confidence": 0.88,
  "visibility": ["项目组", "法务部"]
}
```

为什么 MemoryEvidence 不能只存 chunk：

1. chunk 不知道新旧状态。
2. chunk 不知道负责人和部门。
3. chunk 不知道自己是不是决策、风险、任务还是工具结果。
4. chunk 不知道证据来源和权限。
5. chunk 很难支持多跳推理和关系推理。

企业级 memory 应该是：

`raw event + extracted proposition + metadata + validity + source reference`

---

## 8. EvalCase：评测数据必须怎么写

EvalCase 用来回答：

`你的系统是不是真的比 OpenClaw baseline 更会记忆？`

推荐 schema：

```json
{
  "case_id": "qa_temporal_001",
  "project_id": "proj_starbridge_crm",
  "query": "星桥CRM项目现在的上线时间是哪天？之前改过吗？",
  "ability": "knowledge_update_temporal_reasoning",
  "gold_answer": "最新上线时间是 2026-04-25，原计划是 2026-04-20，因数据出境条款未确认而延期。",
  "gold_memory_ids": [
    "mem_launch_date_20260420",
    "mem_risk_legal_cross_border_001"
  ],
  "must_mention": ["2026-04-25", "2026-04-20", "数据出境条款"],
  "must_not_mention": ["2026-04-20 是最新上线时间"],
  "should_abstain": false,
  "answer_type": "short_answer_with_evidence"
}
```

评测类型建议：

1. `information_extraction`
   - 单条或少数证据即可回答。

2. `multi_session_reasoning`
   - 必须跨会议、群聊、文档或任务。

3. `temporal_reasoning`
   - 必须比较时间顺序。

4. `knowledge_update`
   - 必须识别新信息覆盖旧信息。

5. `abstention`
   - 没有证据时拒答。

6. `responsibility_tracking`
   - 必须找到 owner、assignee、department。

7. `tool_result_reuse`
   - 必须复用历史工具结果。

8. `cross_source_synthesis`
   - 必须整合多个来源。

推荐指标：

- `Recall@k`
- `MRR`
- `Evidence Precision`
- `Answer F1`
- `Exact Match`
- `Temporal Accuracy`
- `Update Accuracy`
- `Abstention Accuracy`
- `Prompt Tokens`
- `Latency`
- `Tool Result Reuse Rate`
- `Wrong Tool Argument Rate`

---

## 9. 你的原始想法是否能解决这些问题

结论：能解决核心问题，但要补一层数据定义和一层时间冲突处理。

### 9.1 MCP 工具调用集成

能解决：

- 工具状态不可复用
- 参数补全依赖历史
- 多轮任务执行断层

在 OpenClaw 上的正确落点：

`Tool Result Memory`

不是重新接 MCP，而是把 MCP / 飞书 CLI 工具结果结构化写回记忆。

推荐写法：

`接入基于 MCP 的工具调用结果记忆化能力，将工具选择、参数、返回摘要、关键实体、执行状态和来源 turn 写入企业记忆索引，支持后续多轮任务中的结果复用和参数补全。`

你的已有结果：

`在 ToolSandbox 多轮工具调用子集上，整体 similarity 由 0.7498 提升至 0.7672。`

### 9.2 query-aware history selector

能解决：

- 最近窗口召回不足
- 多 session 问答
- 跨文档、跨群聊证据选择
- long-term memory recall

在 OpenClaw 上的正确落点：

`ContextEngine.assemble()`

推荐流程：

```text
current query
 -> query expansion
 -> candidate retrieval from session/doc/task/tool memory
 -> temporal/status filtering
 -> reranking
 -> top evidence
```

你的已有结果：

`Recall@k 由 0.10 提升至 0.45，MRR 由 0.0625 提升至 0.3833。`

### 9.3 extractive compressor

能解决：

- prompt 过长
- 冗余历史干扰
- 成本和延迟
- 回答时找不到重点

在 OpenClaw 上的正确落点：

`ContextEngine.assemble()` 中的 prompt-time compression。

注意：

- 不要改写原始 transcript。
- 不要把压缩结果当永久事实。
- 压缩结果只服务当前 query。

你的已有结果：

`压缩方案将问答 F1 由 0.157 提升至 0.294，平均 prompt tokens 由 46288 降至 10099。`

### 9.4 head-tail evidence reordering

能解决：

- Lost in the Middle
- 证据放在中间模型不利用
- 长上下文 attention 偏置

在 OpenClaw 上的正确落点：

`systemPromptAddition + tail evidence near current user prompt`

推荐上下文组织：

```text
stable system prompt
stable memory schema
cache boundary
short project state summary
recent live context
top-1/top-3 evidence near current query
current user prompt
```

### 9.5 还缺什么

你之前的想法还缺两个模块：

1. `Office Memory Schema`
   - 定义企业记忆到底是什么。
   - 对应 RawOfficeEvent、MemoryEvidence、EvalCase。

2. `Temporal Conflict Resolver`
   - 处理旧信息和新信息冲突。
   - 根据时间、来源权威性、status、supersedes 判断最新有效事实。

补上这两个模块，你的方案就完整了。

---

## 10. 最推荐的系统架构

```text
Feishu / Miaoda / Mock Office Data
        |
        v
RawOfficeEvent Ingestor
        |
        v
Event-centric Memory Extractor
        |
        v
Enterprise Memory Store
  - keyword index
  - vector index
  - entity/time index
  - source/evidence index
        |
        v
Query-aware Context Engine
  - query expansion
  - retrieval
  - temporal conflict resolution
  - extractive compression
  - head-tail reordering
        |
        v
OpenClaw Agent
        |
        v
Tool Result Writeback / Memory Update
```

---

## 11. 最小 Demo 应该长什么样

Demo 不需要真实企业数据，但必须像真实企业协作。

建议用一个项目：

`星桥 CRM 上线项目`

准备数据：

```text
demo_data/feishu_mock/
  raw_events.jsonl
  memory_evidence.jsonl
  eval_cases.jsonl
  docs/
    prd_v1.md
    prd_v2.md
    risk_register.md
    weekly_report.md
  meetings/
    kickoff_2026-04-02.md
    legal_review_2026-04-09.md
    launch_review_2026-04-12.md
  tasks/
    tasks_2026-04-13.json
  calendar/
    calendar_2026-04.json
```

Demo 问题：

1. `上周法务提到的最大上线风险是什么？谁负责？`
2. `星桥CRM项目现在的上线时间是哪天？之前改过吗？`
3. `目前影响上线的 blocker 有哪些？按负责人分组。`
4. `研发上次承诺的接口完成时间是什么时候？`
5. `基于刚才查到的会议安排，帮我写一条提醒。`
6. `如果记忆里没有客户续约金额，应该怎么回答？`

对比组：

1. `OpenClaw baseline`
   - 原始 session transcript + memory_search。

2. `+ query-aware selector`
   - 主动召回相关证据。

3. `+ compressor`
   - 压缩证据。

4. `+ reordering + tool result memory`
   - 证据放置优化，工具结果可复用。

---

## 12. 没有真实飞书办公数据怎么办

可以用合成数据，但必须是可评测的合成数据。

不要这样做：

`让大模型随便生成一堆群聊。`

应该这样做：

1. 先写项目真值图
   - 项目
   - 人员
   - 部门
   - 任务
   - 风险
   - 决策
   - 时间线
   - 冲突更新

2. 再渲染成飞书风格 raw events
   - 群聊
   - 会议纪要
   - 文档
   - 任务
   - 日程
   - 评论

3. 再抽取 MemoryEvidence
   - proposition
   - entities
   - relations
   - validity
   - source_refs

4. 最后生成 EvalCase
   - query
   - gold answer
   - gold evidence
   - ability type

这样数据虽然是 mock 的，但评测是真实的。

比赛报告里可以写：

`由于真实企业飞书数据涉及隐私和权限，本项目构造了一套脱敏的飞书风格企业协作数据集。该数据集先定义项目真值图，再渲染为群聊、会议纪要、文档、任务、日程和文档评论等办公事件，最后生成带 gold evidence 的评测用例。`

---

## 13. 最终你应该怎么表述创新点

不要写：

`我做了一个 memory RAG。`

建议写：

`本文面向企业长程协作中信息分散、状态更新、责任链断层和工具结果不可复用的问题，基于 OpenClaw 设计并实现企业级 Memory Engine。系统定义 RawOfficeEvent、MemoryEvidence 和 EvalCase 三层数据结构，将飞书风格办公数据转化为事件式记忆，并在 ContextEngine 中实现 query-aware retrieval、temporal conflict resolution、extractive compression、head-tail evidence reordering 和 tool result memory，从而提升长程协作任务中的历史召回、时间推理、工具复用和上下文效率。`

---

## 14. 第一版最务实的落地顺序

1. 写 `memory.md`
   - 明确数据定义、技术依据、系统架构。

2. 建 `demo_data/feishu_mock/`
   - 至少 1 个项目。
   - 150 条 raw events。
   - 80 条 memory evidence。
   - 40 个 eval cases。

3. 做本地 memory engine
   - ingestion
   - retrieval
   - compression
   - reordering

4. 接 OpenClaw
   - 第一版可以通过 tool 或 script 接。
   - 第二版再做 context engine plugin。

5. 跑评测
   - baseline vs method。
   - 输出 Recall@k、MRR、F1、tokens、tool reuse。

6. 做 Demo
   - CLI demo 是最低要求。
   - 妙搭 Agent 可以作为展示入口。

---

## 15. 参考资料

- OpenClaw Memory Overview  
  [https://docs.openclaw.ai/concepts/memory](https://docs.openclaw.ai/concepts/memory)

- OpenClaw Context Engine  
  [https://docs.openclaw.ai/concepts/context-engine](https://docs.openclaw.ai/concepts/context-engine)

- OpenClaw Context  
  [https://docs.openclaw.ai/concepts/context](https://docs.openclaw.ai/concepts/context)

- OpenClaw Feishu Channel  
  [https://docs.openclaw.ai/channels/feishu](https://docs.openclaw.ai/channels/feishu)

- 飞书获取会话历史消息  
  [https://open.feishu.cn/document/server-docs/im-v1/message/list](https://open.feishu.cn/document/server-docs/im-v1/message/list)

- 飞书接收消息事件  
  [https://open.feishu.cn/document/server-docs/im-v1/message/events/receive](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)

- 飞书发送消息  
  [https://open.feishu.cn/document/server-docs/im-v1/message/create](https://open.feishu.cn/document/server-docs/im-v1/message/create)

- LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory  
  [https://proceedings.iclr.cc/paper_files/paper/2025/hash/d813d324dbf0598bbdc9c8e79740ed01-Abstract-Conference.html](https://proceedings.iclr.cc/paper_files/paper/2025/hash/d813d324dbf0598bbdc9c8e79740ed01-Abstract-Conference.html)

- Evaluating Very Long-Term Conversational Memory of LLM Agents  
  [https://aclanthology.org/2024.acl-long.747/](https://aclanthology.org/2024.acl-long.747/)

- ToolSandbox  
  [https://machinelearning.apple.com/research/toolsandbox-stateful-conversational-llm-benchmark](https://machinelearning.apple.com/research/toolsandbox-stateful-conversational-llm-benchmark)

- tau2-bench  
  [https://huggingface.co/papers/2506.07982](https://huggingface.co/papers/2506.07982)

- LongLLMLingua  
  [https://www.microsoft.com/en-us/research/publication/longllmlingua-accelerating-and-enhancing-llms-in-long-context-scenarios-via-prompt-compression/](https://www.microsoft.com/en-us/research/publication/longllmlingua-accelerating-and-enhancing-llms-in-long-context-scenarios-via-prompt-compression/)

- Lost in the Middle  
  [https://aclanthology.org/2024.tacl-1.9/](https://aclanthology.org/2024.tacl-1.9/)

- GraphRAG  
  [https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/)

- LightRAG  
  [https://huggingface.co/papers/2410.05779](https://huggingface.co/papers/2410.05779)

- SCBench  
  [https://proceedings.iclr.cc/paper_files/paper/2025/hash/a540b17fb2295c736d5afd6c507acf66-Abstract-Conference.html](https://proceedings.iclr.cc/paper_files/paper/2025/hash/a540b17fb2295c736d5afd6c507acf66-Abstract-Conference.html)
