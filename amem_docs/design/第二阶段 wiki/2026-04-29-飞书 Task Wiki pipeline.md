# 飞书 Task Wiki：基于 Session Wiki 与可验证 Event 的项目记忆系统

## 0. 核心目标

本系统面向飞书企业协作场景，目标是围绕具体 `task_id` 持续沉淀项目记忆，形成可检索、可更新、可追溯、可遗忘的任务 Wiki。

在日常协作中，一个任务相关的信息可能分散在多个群聊、会话线程、文档、会议纪要、任务评论、审批记录或多维表格中。传统 RAG 通常是在查询时临时检索原始消息，再让模型重新总结。这种方式的问题是：每次查询都像从零开始，历史讨论、决策依据、异议、风险、约束和行动项很难形成长期积累。

本系统采用 LLM Wiki 思路，但将 **Event 抽取层** 与 **Wiki 维护层** 明确分开：

```text
Event 抽取层：
从 session file 中抽取由原文 quote 直接支撑的最小可验证协作事实。

Wiki 维护层：
消费已验证的 session_event，将其组织成 session_wiki.md、Memory Block、index.md 和 task_wiki.md。
```

系统不是直接让 LLM 总结群聊或文档，而是先把协作内容转化为 verified session_events，再由 Wiki 层把这些 events 聚合成结构化的 Memory Blocks，并最终汇总为 Task Wiki。

整体链路如下：

```text
飞书协作内容
  → task_id 绑定
  → session file 摄入
  → Evidence Span 构造
  → candidate_event 抽取
  → verification
  → session_event 存储
  → session_wiki.md 生成 / 更新
  → Memory Block 生成 / 更新
  → index.md 更新
  → task_wiki.md 汇总更新
  → 可选 topic views 更新
  → 检索 / 巡检 / 遗忘
```

一句话概括：

```text
event 负责可信，Memory Block 负责组织，index 负责定位，task_wiki 负责当前状态。
```

---

# 1. 核心对象定义

## 1.1 Task

Task 是项目记忆的核心组织单位。

它可以是：

```text
- 一个项目任务
- 一个需求
- 一个问题单
- 一个缺陷修复
- 一个审批事项
- 一个里程碑目标
```

系统不再以个人、普通 thread 或单个文档作为主要记忆对象，而是以 `task_id` 作为后续处理的主键。

---

## 1.2 Session File

在当前 V1 语义中，`Session File` 更准确地说是 **source session**：它是围绕某个 task、某个绑定 source 的稳定记忆容器，而不是“每次 ingest 新建一个全新 session”。

它同时承担两种角色：

```text
1. source：事实来源容器
2. ingest unit carrier：承载后续多次 ingest 的稳定容器
```

因此，本系统不再单独区分 Raw Source 和 Session File；但要区分：

```text
source session：稳定来源容器
ingest：该 source session 上的一次新增摄入和抽取
```

Session File 可以来自：

```text
- 某个 chat
- 某个 thread
- 某篇飞书文档
- 某次会议纪要
- 某个任务评论窗口
- 某条审批记录
- 某条多维表格记录
```

它不是完整群聊或完整文档的无差别镜像，而是经过 task 绑定后形成的稳定 source session。

在 V1 中，id 语义拆成两层：

```text
source_session_id = task_id + source_scope
ingest_version = 该 source session 下的第 N 次摄入
```

示例：

```text
task_id: FEISHU-231
source_session_id: FEISHU-231__thread_abc
ingest_version: 3
source_type: chat_thread
```

---

## 1.3 Evidence Span

Evidence Span 是从 session file 中筛选出的候选证据包。

它不是完整 session，而是为 event 抽取组织出来的局部上下文。

一个 Evidence Span 包含概念上的三层：

```text
1. Core
2. Context
3. Current State Context
```

含义如下：

```text
Core：
唯一可以触发新 event 的原文片段。

Context：
只用于解释指代和补全语义，不能单独生成 event。

Current State Context：
当前 Wiki 状态摘要，只用于理解已有口径，不能作为证据。
```

关键约束：

```text
Core 负责触发 event。
Context 只负责消歧。
Current State Context 不能作为证据。
```

但在当前 Layer 2 V1 的正式实现约束中，只把 `Core + Context` 作为输入 contract；`Current State Context` 暂不进入第二层主实现。

在工程实现上，当前 V1 进一步把 Core 拆成两类：

```text
trigger_entries：
真正允许触发 candidate_event 的本次新增内容。

support_entries：
只用于补充 thread/comment 的 root 和必要近邻语义，
不能单独触发正式 event。
```

---

## 1.4 candidate_event

candidate_event 是从 Evidence Span 的 Core 中抽取出来的候选事件。

它还没有通过 verification，因此不能直接进入 Wiki，也不能作为正式事实使用。

它的作用是：

```text
把一段自然语言拆成一个或多个最小事实断言，等待验证。
```

V1 中，candidate_event 的物理输出文件是：

```text
candidate_events.jsonl
```

其中保存尚未成为正式 session_event 的候选项，可以因为字段缺失、指代未完全解析、claim 支撑不足等原因被标记为：

```text
candidate / needs_review / rejected
```

---

## 1.5 session_event

session_event 是通过 verification 后正式落盘的事件。

它是系统中的正式事实单位。

定义如下：

```text
session_event = 从某个 session file 的 Core 中抽取出的、由原文 quote 直接支撑的、通过 verification 的最小协作事实。
```

session_event 不表示 Wiki 更新操作。

它不直接表示：

```text
- 新增 Wiki item
- 更新 Wiki 字段
- 删除旧结论
- 修改当前状态
```

这些都是 Wiki 层消费 session_event 后做的事情。

V1 中，session_event 的物理输出文件是：

```text
session_events.jsonl
```

它只保存 `verified` 的正式事件，供第三层 Wiki 消费。

session_event 只回答一个问题：

```text
这段 Core 原文中明确表达了什么可验证事实？
```

---

## 1.6 session_wiki.md

`session_wiki.md` 是系统中的基础 Wiki Page。

每个 session file 对应一个 `session_wiki.md`。

它类似 Paper Wiki 中的 paper page：一个来源文件被摄入后，会生成一个对应的一手记忆页。

`session_wiki.md` 记录：

```text
- 这个 session 讨论了什么
- 这个 session 产生了哪些 session_event
- 这个 session 对 task 贡献了哪些结论、理由、异议、约束、行动项和时间点
- 这个 session 中哪些问题仍待后续处理
```

它是一手记忆页，证据边界清晰，更新路径稳定。

---

## 1.7 Memory Block

一个 session 中可能讨论多件事情。

例如，同一段群聊可能先讨论发布时间，再讨论销售承诺风险，随后又讨论接口文档行动项。这些内容虽然都属于同一个 task，但不应该混在一个大总结里。

因此，`session_wiki.md` 内部需要拆成多个 Memory Block。

```text
session_wiki.md = 多个 Memory Block 的集合
Memory Block = 一组围绕同一问题 / 主题 / 决策轴 / 执行事项的 session_event 聚合
```

示例：

```text
Memory Block A：发布时间口径
Memory Block B：销售承诺风险
Memory Block C：接口文档行动项
Memory Block D：方案范围裁剪
```

Memory Block 是 `index.md` 的核心索引粒度。

---

## 1.8 KI Slot

KI Slot 是 Memory Block 内部的结构化栏目。

它用于把同一个问题/主题下的不同类型记忆组织清楚。

第一版可以使用 8 个 slot：

```text
1. conclusion slot：结论 / 当前口径 / 决定
2. rationale slot：理由 / 依据
3. objection slot：异议 / 担忧 / 反对意见
4. constraint slot：约束 / 边界 / 禁止项
5. commitment slot：行动承诺
6. status slot：状态事实
7. time slot：时间点 / 截止日期 / 里程碑
8. scope slot：范围 / 阶段 / 适用对象
```

注意：

```text
不是每个 Memory Block 都必须填满 8 个 slot。
只填本 block 中有证据支撑的 slot。
没有证据的 slot 可以省略或留空。
```

---

## 1.9 index.md

`index.md` 是 task 级别的目录和导航层。

它不维护跨 session 的 event index，也不复制所有 event 摘要。

它的核心粒度是 Memory Block，而不是整个 session_wiki.md。

也就是说，index 不只是回答：

```text
这个 task 有哪些 session？
```

而是回答：

```text
这个 task 下有哪些可复用的记忆单元？
这些 Memory Block 分别属于哪个 session？
它们对应什么 topic、阶段、状态、行动项或风险？
```

检索路径是：

```text
index.md → Memory Block → session_wiki.md → event_ref → session_events.jsonl → evidence_quote → session.md
```

---

## 1.10 task_wiki.md

`task_wiki.md` 是围绕 `task_id` 生成和维护的任务当前状态总览。

它不是原文总结，也不是 event 列表。

它是：

```text
基于多个 session_wiki.md / Memory Blocks 汇总生成的任务当前状态视图。
```

Task Wiki 不直接承载全部细节，而是引用相关 Memory Block 和 session_wiki.md。

---

## 1.11 Topic View，可选

Topic View 是可选的二级综合页。

当某个主题跨越多个 session，且在 task 中变得足够重要时，可以生成一个 topic view。

例如：

```text
views/release_plan.md
views/external_communication.md
views/risk_and_blockers.md
```

Topic View 不是基础存储层。

基础存储层仍然是：

```text
sessions/*/session_wiki.md
```

Topic View 应从多个 Memory Block 综合而来，而不是直接从原始 session file 或 event 生成。

---

# 2. 目录结构建议

一个 task 可以对应一个本地 Wiki 目录。

建议结构如下：

```text
task_memory/
  FEISHU-231/
    task.yaml
    index.md
    log.md
    task_wiki.md

    sessions/
      2026-04-27_thread_abc/
        session.md
        metadata.yaml
        evidence_spans.jsonl
        candidate_events.jsonl
        session_events.jsonl
        session_wiki.md

      2026-04-28_doc_xyz/
        session.md
        metadata.yaml
        evidence_spans.jsonl
        candidate_events.jsonl
        session_events.jsonl
        session_wiki.md

    views/                    # 可选：二级综合视图，不是主存储
      release_plan.md
      external_communication.md
      risk_and_blockers.md

    lint/
      open_conflicts.md
      stale_claims.md
      orphan_events.md
      unresolved_objections.md
      overdue_commitments.md
```

这里不再设计 `event_index.jsonl`。

原因是：

```text
1. session_event 物理上归属于 sessions/{source_session_id}/session_events.jsonl
2. event_id 全局唯一
3. 每个 session file 都有自己的 session_wiki.md
4. index.md 主要索引 Memory Block，并保留其所属 session
5. task_wiki.md 基于多个 Memory Block 汇总
6. views/*.md 只是可选的二级主题综合视图
```

各文件职责：

```text
task.yaml:
任务元信息。

index.md:
任务级目录，指向 session_wiki.md 中的 Memory Block，并按 topic / stage / status 聚合。

log.md:
只增日志，记录摄入、更新、巡检、遗忘操作。

task_wiki.md:
面向用户阅读的任务当前状态总览，由多个 Memory Block 汇总生成。

sessions/*/session.md:
当前 source session 的热工作视图，不是永远展开的全量原文页。

sessions/*/metadata.yaml:
该 session 的来源、时间范围、参与人、source hash、绑定 task 等元数据。

sessions/*/evidence_spans.jsonl:
从 session.md 中筛出的 Evidence Span。

sessions/*/candidate_events.jsonl:
该 session 中尚未成为正式 session_event 的候选事件，包含 `candidate / needs_review / rejected` 等状态。

sessions/*/session_events.jsonl:
该 session 中通过 verification 的正式 session_event。event_id 全局唯一。

sessions/*/pending_ingests.jsonl:
该 source session 的原始 ingest ledger。无 event 的 ingest 也保留在这里，
但状态会写成 `processed_no_event`，不会进入 verifier queue。

sessions/*/session_wiki.md:
该 session 对 task 的一手记忆页，是基础 Wiki Page。

views/*.md:
可选的跨 session 主题综合页。当某个主题涉及多个 session 且需要长期跟踪时才创建。

lint/*.md:
巡检结果和待处理问题。
```

---

# 3. 任务绑定和信息归类

## 3.1 目标

确定每条信息是否属于某个任务，并确保后续处理都围绕正确的 `task_id` 展开。

如果信息无法绑定到任何 `task_id`，则不进入记忆处理链路。

---

## 3.2 绑定方式

绑定方式包括：

```text
1. 显式绑定
   - 文档创建时选择所属 task
   - thread 开启时选择所属 task
   - 任务卡片下的评论天然继承 task_id

2. 继承绑定
   - thread 继承父消息的 task_id
   - 文档评论继承文档的 task_id
   - 会议纪要继承会议关联任务的 task_id

3. 上下文绑定
   - 消息中出现任务编号、需求编号、项目名
   - 消息所在群或频道与某个 task 有明确关联
   - 文档标题、父目录或模板中包含 task 线索
```

处理规则：

```text
未绑定 task_id 的信息 → 不处理
已绑定 task_id 的信息 → 形成 session file
```

---

# 4. Session File 摄入

## 4.1 目标

将已绑定 `task_id` 的协作内容整理进一个稳定的 source session，并在这个 session 上持续追加 ingest。

Session File 是事实来源容器；每次 ingest 才是后续 event 抽取的直接处理单位。

---

## 4.2 Session File 不是完整原始流

系统不会把完整群聊、完整 thread 或完整文档无差别写入记忆系统。

Session File 应该是：

```text
围绕某个 task、某个绑定 source 的稳定 source session 容器。
```

它可以通过以下方式形成：

```text
- 按 chat 形成 source session
- 按 thread 形成 source session
- 按文档形成 source session
- 按会议纪要形成 source session
- 按任务评论窗口形成 source session
```

后续新内容进入时，不是新建无关 session，而是在对应 source session 下追加新的 ingest_version。

---

## 4.3 Session File 元数据

每个 session file 至少包含：

```text
- source_session_id
- ingest_version
- task_id
- source_type
- source_id
- source_title
- time_range
- participants
- ingest_time
- source_url
- source_hash / version
```

其中：

```text
source_session_id = task_id + source_scope
ingest_version = 该 source session 下递增的摄入版本
```

---

# 5. Event 抽取层

## 5.1 Event 的核心定义

Event 是从 Core 原文中抽取出的、由一个或多个 quote 直接支撑的最小协作事实断言。

关键词：

```text
1. 从 Core 原文中抽取
2. quote 直接支撑
3. 最小协作事实断言
```

event 不能是“模型觉得应该是这样”，而必须能回答：

```text
这条 claim 的哪一部分来自哪句原文？
```

---

## 5.2 Evidence Span

一个 Evidence Span 包含概念上的三层：

```text
1. Core
2. Context
3. Current State Context
```

规则：

```text
Core：唯一可以触发新 event。
Context：只用于解释指代，不得单独生成 event。
Current State Context：只能帮助理解当前状态，不能作为证据。
```

当前 Layer 2 V1 的正式输入 contract 只使用：

```text
Core + Context
```

`Current State Context` 暂不进入第二层主实现。

V1 的 source-specific Core 规则直接写死为：

```text
chat：
本次 ingest 新进入的 task 相关消息集合。

thread：
root message + 本次新增 reply。

comment：
root comment + 本次新增 reply/comment。

doc：
本次变更片段或当前锚定片段。
```

补充约束：

```text
chat 和 thread 都可以绑定到同一个 task，
但它们是不同 source session，不互相覆盖。
```

---

## 5.3 candidate_event 抽取原则

每条 candidate_event 必须尽量满足：

```text
1. 必须由 Core 触发
2. 必须有 evidence_quote
3. evidence_quote 必须来自 Core
4. claim 只能表达一个事实
5. claim 不能超出 evidence_quote 与必要 Context quote 的支持范围
6. Context 只能用于消歧，不能单独生成 event
7. Current State Context 不能作为证据
8. 原文没有的信息不能补
```

如果无法满足这些原则，则该 candidate_event 应被标记为 `candidate`、`needs_review` 或 `rejected`。

---

## 5.4 Event 类型

第一版 event 使用 8 类。

这 8 类不是 Wiki 模块，而是可验证事实类型。

```text
1. conclusion_event：结论 / 口径 / 决定
2. rationale_event：理由 / 依据
3. objection_event：异议 / 担忧 / 反对意见
4. constraint_event：约束 / 边界 / 禁止项
5. commitment_event：承诺 / 行动项
6. status_event：状态事实
7. time_event：时间点 / 截止日期 / 里程碑
8. scope_event：范围 / 阶段 / 适用对象
```

---

## 5.5 Event 类型说明与验证规则

### conclusion_event：结论 / 口径 / 决定

抽取明确表达“怎么定”“按什么来”“当前结论是什么”的事实。

典型原文：

```text
那就先按方案 B 来。
本期不做自定义节点。
这个先按 5 月 5 日推进。
```

验证规则：

```text
- quote 中必须出现明确结论词：定了、按...来、采用、不做、先走、确认、结论是
- claim 不能添加 quote 中没有的强度
- 个人建议不抽 conclusion_event
```

---

### rationale_event：理由 / 依据

抽取某个选择、判断、担忧、约束背后的原因。

典型原文：

```text
方案 A 成本太高。
因为迁移窗口还没锁定。
客户现在主要卡在审批配置复杂。
```

验证规则：

```text
- quote 必须表达原因、依据或背景
- claim 只能保留原因本身
- reason_for 可以来自 Context 消歧，但不能凭空补
```

---

### objection_event：异议 / 担忧 / 反对意见

抽取有人提出的不同意见、风险担忧、反对意见或保留态度。

典型原文：

```text
我担心方案 B 后面扩展性不够。
这个时间销售可能会拿去承诺客户。
我不同意这期砍掉审批配置。
```

验证规则：

```text
- quote 必须包含担忧、反对、不同意、风险提醒等语气
- 普通提问不抽 objection_event
- objector 必须来自说话人或 quote 明确指向
- 不能把模型推测的风险写进 objection
```

---

### constraint_event：约束 / 边界 / 禁止项

抽取不能做什么、必须满足什么、对外口径限制或规则边界。

典型原文：

```text
不要对外说死。
不能承诺 5 号一定上线。
这个接口不能破坏现有兼容性。
所有客户定制需求都必须先进需求池。
```

验证规则：

```text
- quote 必须表达限制、禁止、必须、边界、约束
- target 可以用 Context 解析
- claim 中的约束强度不能超过 quote
- “不要对外说死”不能抽成“禁止对外沟通该事项”
```

---

### commitment_event：承诺 / 行动项

抽取谁要做什么，最好有时间。

典型原文：

```text
李四周五前补齐接口文档。
我来同步销售。
研发这周给出排期。
```

验证规则：

```text
- quote 必须能识别 owner + action
- deadline 没出现就填 null，不能脑补
- “后面看看”不算 commitment
- owner 不明确时降级为 candidate 或不抽
```

---

### status_event：状态事实

抽取某件事完成了、未完成、阻塞、待确认、已确认等状态。

典型原文：

```text
接口文档我补好了。
这个风险还没解。
迁移窗口还没锁定。
审批还没过。
```

验证规则：

```text
- quote 必须表达明确状态
- target 必须能从 Core 或 Context 解析
- 不要把情绪判断抽成状态
```

---

### time_event：时间点 / 截止日期 / 里程碑

抽取确认、暂定、修改、顺延某个时间。

典型原文：

```text
截止日期是 5 号。
目标发布时间暂定 5 月 5 日。
从 5 号顺延到 10 号。
下周三评审。
```

验证规则：

```text
- quote 必须包含时间表达
- time_target 必须明确
- 孤立时间如果 Context 不能解析对象，则不抽
- 必须保留原文强度：暂定、确认、不确定、顺延
```

---

### scope_event：范围 / 适用对象 / 阶段

抽取适用范围、阶段、对象、包含项或排除项。

典型原文：

```text
本期只做模板化配置，不做自定义节点。
这个规则只适用于 P0 客户问题。
先在华东区试点。
MVP 阶段不支持多审批人。
```

验证规则：

```text
- quote 必须表达范围、阶段、适用对象或排除项
- included / excluded 必须能在 quote 中找到
- 不要把决策原因混进 scope
```

---

## 5.6 通用 event schema

所有 event 都必须有这些字段：

```json
{
  "event_id": "evt_xxx",
  "task_id": "FEISHU-231",
  "session_id": "2026-04-27_thread_abc",
  "event_type": "conclusion_event",
  "claim": "本期先采用方案 B",
  "core_entry_id": "msg_123",
  "evidence_quote": "那就先按方案 B 来",
  "context_quotes": [
    {
      "entry_id": "msg_120",
      "quote": "方案 A 成本太高",
      "role": "disambiguation"
    }
  ],
  "participants": ["张三", "李四"],
  "event_time": "2026-04-29T10:20:00+08:00",
  "source": {
    "source_type": "chat_thread",
    "source_id": "thread_xxx",
    "url": "https://..."
  },
  "verification": {
    "core_quote_found": true,
    "claim_supported_by_quote": true,
    "context_only_generation": false,
    "single_atomic_claim": true,
    "required_fields_complete": true,
    "no_unsupported_inference": true,
    "verdict": "verified"
  }
}
```

关键字段：

```text
evidence_quote：必须来自 Core。
context_quotes：只能用于消歧，不能单独支撑新 event。
```

---

# 6. Verification：从 candidate_event 到 session_event

Verification 不是事后给 event 打一个主观置信度，而是用规则决定 candidate_event 是否可以成为正式 session_event。

## 6.1 Location Verification

验证 `evidence_quote` 是否真的来自 Core。

规则：

```text
1. evidence_quote 必须是 Core entry 的子串，或经过轻微归一化后可匹配
2. 必须记录 core_entry_id
3. 如果 quote 在多个 Core entry 中出现，必须可唯一定位
4. quote 不能来自 Context
5. quote 不能来自 Current State Context
```

这一层应尽量程序化完成。

---

## 6.2 Schema Verification

验证不同 event 类型是否满足各自必填字段。

例如：

```text
conclusion_event:
- claim
- conclusion
- evidence_quote
- target

rationale_event:
- claim
- reason
- evidence_quote

objection_event:
- claim
- objection
- objector
- target
- evidence_quote

commitment_event:
- claim
- owner
- action
- evidence_quote

time_event:
- claim
- time_target
- time_value
- certainty
- evidence_quote
```

如果必填字段缺失，就标记为：

```text
candidate / needs_review / rejected
```

不要让模型硬补字段。

---

## 6.3 Claim Support Verification

验证 claim 是否真的被 `evidence_quote` 与必要 `context_quotes` 支撑。

它不是问“这个总结对不对”，而是问：

```text
给定 quote，claim 里的每个关键信息是否都有证据？
```

输出可以是：

```json
{
  "verdict": "supported | partially_supported | unsupported",
  "unsupported_parts": ["长期采用", "团队一致决定"],
  "reason": "quote 只说先按方案 B 来，没有长期采用或一致决定"
}
```

---

## 6.4 Atomicity Verification

验证一条 event 是否只表达一个事实。

不合格示例：

```text
因为方案 A 成本高，所以本期采用方案 B，并由李四周五前补文档。
```

它至少应该拆成三条 event：

```text
1. rationale_event：方案 A 成本高
2. conclusion_event：本期采用方案 B
3. commitment_event：李四周五前补文档
```

---

## 6.5 Verification 结果

verification 结果分为三类：

```text
verified：
证据直接支撑，可以写入 session_events.jsonl，成为 session_event。

needs_review：
信息有价值，但 target / owner / relation 等字段不完整，需要后续确认。

rejected：
证据不足、过度推断、context-only、非原子，不能进入正式记忆。
```

---

## 6.6 Verification 原则

```text
Evidence-first：先找 quote，再生成 claim。
Core-triggered：只有 Core 能触发 event，Context 只消歧。
Claim minimality：一条 event 只表达一个事实。
Modality preservation：保留原文强度，例如“暂定”不能写成“确认”。
No slot hallucination：字段缺失就填 null，不补。
Typed verification：不同 event 类型使用不同校验规则。
```

---

# 7. session_event 存储

## 7.1 存储位置

每个 session 保存两层事件产物：

```text
sessions/{source_session_id}/candidate_events.jsonl
sessions/{source_session_id}/session_events.jsonl
```

其中：

```text
candidate_events.jsonl：
保存候选层，包含 candidate / needs_review / rejected。

session_events.jsonl：
只保存 verified 的正式 session_event。
```

不需要额外维护 `event_index.jsonl`。

原因是：

```text
1. event_id 全局唯一，可以直接引用
2. session_event 的完整内容保存在所属 source session 的 session_events.jsonl 中
3. session_wiki.md 直接记录 event_refs
4. index.md 只需要索引 Memory Block，而不是索引全部 event
5. task_wiki.md 由 Memory Block 汇总，不直接依赖 event_index
```

---

## 7.2 event_ref

`session_wiki.md` 或 Memory Block 引用 event 时，应保存 `event_id` 和 `event_path`。

示例：

```json
{
  "event_id": "evt_01HXYZ...",
  "event_path": "sessions/FEISHU-231__thread_abc/3/session_events.jsonl",
  "claim": "5 月 5 日不能作为确定的对外承诺日期"
}
```

---

# 8. session_wiki.md 与 Memory Block

## 8.1 session_wiki.md 的定位

`session_wiki.md` 是该 session 的一手 Wiki 页面。

它不是简单复述原始消息，也不是跨 session 的最终总结，而是把该 session 中的 verified events 按语义组织起来。

---

## 8.2 Memory Block 的定位

Memory Block 是 `session_wiki.md` 内部最重要的组织单元。

一个 Memory Block 表示该 session 中围绕同一个问题、主题、决策轴或执行事项形成的一段局部记忆。

```text
session_wiki.md
  → Memory Block 1
  → Memory Block 2
  → Memory Block 3
```

---

## 8.3 Memory Block 生成规则

session_event 写入 `session_events.jsonl` 后，需要在生成 session_wiki.md 时按语义进行分组。

分组依据可以包括：

```text
- topic_key：主题，例如 发布时间、对外口径、方案选择
- target：事件作用对象，例如 方案 B、5 月 5 日、接口文档
- decision_axis：决策轴，例如 是否采用方案 B、是否对外承诺日期
- owner/action：行动项对象
- time_target：时间对象，例如 截止日期、发布时间
- source proximity：原文中相邻的一组消息
```

每组相关 session_event 形成一个 Memory Block。

一个 session_event 原则上应归入一个主要 Memory Block，但在必要时可以被多个 block 引用。

---

## 8.4 session_wiki.md 建议结构

```text
# Session Wiki: 2026-04-27_thread_abc

## Metadata
- Task: FEISHU-231
- Source Type: chat_thread
- Time Range: 2026-04-27 10:00-10:40
- Participants: 张三、李四、王五

## Session Summary
这次讨论主要涉及 FEISHU-231 的发布时间口径、销售承诺风险和接口文档行动项。

## Memory Blocks

### Block 1: 发布时间口径

#### Summary
内部暂按 5 月 5 日推进，但对外口径调整为预计 5 月上旬。

#### Conclusion
- 内部暂按 5 月 5 日推进。
- 对外口径为预计 5 月上旬。

#### Rationale
- 迁移窗口尚未锁定。

#### Constraint
- 不要对外说死具体日期。

#### Time
- 内部目标发布时间：5 月 5 日。
- 对外口径：5 月上旬。

#### Evidence References
- evt_001 → sessions/FEISHU-231__thread_abc/3/session_events.jsonl
- evt_002 → sessions/FEISHU-231__thread_abc/3/session_events.jsonl

---

### Block 2: 销售承诺风险

#### Summary
有人担心销售将 5 月 5 日直接承诺给客户。

#### Objection / Risk
- 销售可能将 5 月 5 日直接承诺给客户。

#### Constraint
- 对外不能承诺具体日期。

#### Evidence References
- evt_003 → sessions/FEISHU-231__thread_abc/3/session_events.jsonl

---

### Block 3: 接口文档行动项

#### Summary
需要补齐接口文档，并同步销售统一口径。

#### Commitment
- 李四负责补齐接口文档。
- 需要同步销售统一外部口径。

#### Status
- 待处理。

#### Evidence References
- evt_004 → sessions/FEISHU-231__thread_abc/3/session_events.jsonl
```

---

# 9. index.md

## 9.1 index.md 的定位

`index.md` 是 task 的导航页。

它不是完整事实存储，也不是 event 列表。

它采用两层结构：

```text
第一层：Wiki Page Index
记录这个 task 下有哪些 Wiki 页面，例如 task_wiki.md、各个 session_wiki.md，以及可选 views。

第二层：Memory Block Index
在每个 Wiki 页面下面列出该页面包含哪些 Memory Blocks，并用一句话说明每个 Memory Block 讨论什么。
```

index 的核心粒度是 Memory Block。

---

## 9.2 index.md 示例结构

```text
# FEISHU-231 Index

## Task Overview
- Task: FEISHU-231
- Current Task Wiki: [[task_wiki.md]]

## Wiki Page Index

### [[task_wiki.md]]
任务当前状态总览。

### [[sessions/2026-04-27_thread_abc/session_wiki.md]]
4 月 27 日群聊讨论，涉及发布时间、对外口径、销售风险。

- [[sessions/2026-04-27_thread_abc/session_wiki.md#block-1-发布时间口径]]
  - Topic: 发布时间
  - Status: active
  - Summary: 内部暂按 5 月 5 日推进，对外口径为预计 5 月上旬。

- [[sessions/2026-04-27_thread_abc/session_wiki.md#block-2-销售承诺风险]]
  - Topic: 风险与阻塞
  - Status: open
  - Summary: 销售可能将 5 月 5 日直接承诺给客户。

### [[sessions/2026-04-28_doc_xyz/session_wiki.md]]
4 月 28 日方案文档讨论，涉及方案选择和范围裁剪。

- [[sessions/2026-04-28_doc_xyz/session_wiki.md#block-1-方案选择]]
  - Topic: 方案选择
  - Status: active
  - Summary: 本期采用方案 B，暂不做方案 A。

## Topic Routes

### 发布时间
- [[sessions/2026-04-27_thread_abc/session_wiki.md#block-1-发布时间口径]]
- [[sessions/2026-04-30_meeting_release/session_wiki.md#block-2-发布时间调整]]

### 风险与阻塞
- [[sessions/2026-04-27_thread_abc/session_wiki.md#block-2-销售承诺风险]]
- [[sessions/2026-04-29_task_comment/session_wiki.md#block-1-迁移窗口风险]]

### 行动项
- [[sessions/2026-04-27_thread_abc/session_wiki.md#block-3-接口文档行动项]]
```

index 中每个 Memory Block 只需要保留轻量信息：

```text
- block link
- topic
- status
- slots
- 一句话摘要
```

完整证据、event 列表和长摘要应保留在 `session_wiki.md`、`candidate_events.jsonl / session_events.jsonl` 和 `session.md` 中。

---

# 10. task_wiki.md

## 10.1 task_wiki.md 的定位

`task_wiki.md` 是任务当前状态总览。

它不直接承载所有细节，而是从 index.md 中挑选当前最重要的 Memory Blocks，并综合这些 block 的结论、风险、行动项和时间线。

它也不负责保存历史快照。历史追溯回到 `session_wiki.md` 中的 Memory Block：
同一个 KI Slot 内最新有效项展示为 `Current`，旧项、被 supersede 项、失效项或来源失效项展示为 `History`，
并继续保留 `Event Ref`、`Entry Ref` 和 quote。

它应包含：

```text
1. 当前摘要
2. 当前结论
3. 关键决策
4. 决策依据
5. 异议与风险
6. 规则与约束
7. 行动项
8. 时间线
9. 相关 Session Wiki / Memory Block
10. 可选 Topic Views
```

Task Wiki 中的每个结论都应该能链接到相关 Memory Block，再由 Memory Block 回到 session_wiki.md，并最终回溯到 session_event。

---

# 11. 检索流程

## 11.1 目标

当用户在群聊或任务上下文中提出问题时，系统能够快速判断历史上是否已有相关讨论，并返回合适的记忆卡片。

推荐检索路径：

```text
Query
  → identify task
  → read index.md
  → select wiki page
  → select memory block
  → read KI slots
  → fetch event_refs if needed
  → return card
```

更细的证据链路是：

```text
Query
  → index.md
  → Memory Block
  → session_wiki.md
  → Event Reference
  → session_events.jsonl
  → evidence_quote
  → session.md
```

---

## 11.2 检索结果类型

### Direct Hit

如果用户问题能直接命中某个 Memory Block，则返回该 block 的卡片。

例如用户问：

```text
5 号这个时间能不能对外承诺？
```

系统可以命中：

```text
- 发布时间口径 block
- 销售承诺风险 block
- 对外沟通约束 block
```

返回内容可以包括：

```text
- 当前结论
- 相关约束
- 之前的异议或风险
- 证据引用
```

---

### Related Hit

如果没有找到完全对应的 Memory Block，但存在相关历史讨论，则返回“相关历史记忆”。

示例：

```text
没有找到完全对应的历史结论，但有相关对外口径约束可参考。
```

---

### No Hit

如果没有找到相关 Memory Block，则不要强行召回不相关历史。

系统可以返回：

```text
没有找到与该问题直接相关的历史记忆。该问题可以作为新的讨论进入 session/event pipeline。
```

---

# 12. 更新机制

系统采用增量更新，而不是每次全量重写。

当新的消息、文档内容或会议纪要进入系统时，流程是：

```text
new raw content
  → update or create source session
  → extract candidate_events
  → verify events
  → append to candidate_events.jsonl / session_events.jsonl
  → locate affected Memory Blocks
  → update session_wiki.md
  → update index.md
  → refresh task_wiki.md if needed
```

更新核心是：

```text
优先更新受影响的 Memory Block，而不是重写整个 Wiki。
```

当一个新 event 进入系统后，需要判断：

```text
1. 它属于哪个 session
2. 它影响哪个 session_wiki.md
3. 它应该进入哪个 Memory Block
4. 它应该填入哪个 KI Slot
5. 它是否改变该 Memory Block 的 summary 或 status
6. 它是否影响 session_wiki.md 的 session summary
7. 它是否影响 task_wiki.md 的当前状态
8. 它是否需要更新 index.md 中的摘要或状态
```

示例：

如果一个新 event 表明：

```text
目标发布时间从 5 月 5 日顺延到 5 月 10 日。
```

系统不应该删除旧 event，而应该：

```text
- 保留旧 event 作为历史事实
- 用新 event 更新相关 Memory Block 的当前状态
- 在 session_wiki.md 的同一 KI Slot 中把新项放入 Current，把旧项保留到 History
- 将旧结论标记为 superseded
- 在 task_wiki.md 中展示新的当前状态
- 通过 session_wiki.md 的 History 和 event evidence 链保留历史变化
```

---

# 13. 遗忘机制

遗忘用于处理来源被删除、消息被撤回、文档被删除、权限失效或 event 抽取错误等情况。

遗忘不应该默认物理删除所有信息。更稳妥的做法是先标记失效，再沿引用链更新 Wiki。

遗忘流程：

```text
source revoked / deleted
  → mark session as revoked
  → mark related events as source_revoked
  → find Memory Blocks referencing these events
  → remove or mark affected KI Slot items
  → update affected Memory Blocks
  → update session_wiki.md
  → update index.md
  → refresh task_wiki.md
  → append log.md
```

---

## 13.1 Source-level Forgetting

如果原始 session 被删除或撤回，则将该 session 标记为 revoked，并将相关 events 标记为 source_revoked。

如果某个 Memory Block 完全依赖这些失效 events，则该 block 应被 archived 或 invalidated。

---

## 13.2 Event-level Invalidation

如果某个 event 后续被发现抽取错误，或者 claim 并不被 quote 支撑，则将该 event 标记为 invalidated。

随后更新引用该 event 的 KI Slots 和 Memory Blocks。

---

## 13.3 Knowledge-level Supersession

如果新事实覆盖旧事实，例如截止日期从 5 号改到 10 号，这不是遗忘，也不是删除。

旧 event 仍然保留，新的 event 成为当前状态。

`task_wiki.md` 默认展示新状态，但历史仍可追溯。

---

# 14. 巡检机制：Lint

Lint 用于维护 Task Wiki 的长期健康度。

它不是抽取流程，而是周期性检查和修复流程。

巡检内容包括：

```text
1. 是否有 session_event 没有被对应 session_wiki.md 引用
2. 是否有 session_wiki.md 没有 Evidence References
6. 是否有 session 被删除但 event 仍在支撑 Wiki
7. 是否有 claim 强度超过 event
8. 是否有同一 topic 下的结论冲突
9. 是否有孤立 session_wiki.md 或孤立 Memory Block
10. 是否缺少必要交叉引用
```

巡检结果可以写入：

```text
lint/open_conflicts.md
lint/stale_claims.md
lint/orphan_events.md
lint/unresolved_objections.md
lint/overdue_commitments.md
```

---

# 15. log.md

`log.md` 是只增日志。

它记录：

```text
- session_wiki update
- index update
- task_wiki refresh
- topic view update
- lint
- forgetting
```

建议使用统一前缀，便于解析：

```text
## [2026-04-27] ingest | 2026-04-27_thread_abc
## [2026-04-27] extract | 14 candidate_events
## [2026-04-27] verify | 12 session_events verified
## [2026-04-27] update | sessions/2026-04-27_thread_abc/session_wiki.md
## [2026-04-28] refresh | task_wiki.md
## [2026-04-28] lint | 2 overdue commitments
## [2026-04-29] forget | revoked session 2026-04-20_doc_old
```

---

# 16. 系统操作总览

## 16.1 Extraction

```text
1. 确认 source 已绑定 task_id
2. 形成 source session
3. 在对应 source session 下追加新的 ingest_version
4. 筛选 Evidence Span
5. 区分 trigger_entries / support_entries / Context
6. 从 trigger_entries 抽取 candidate_event
7. 没有 candidate 的 ingest 直接记为 processed_no_event
8. 只有 ready_for_verification 的 candidate 才进入 verification
9. verified event 写入 session_events.jsonl，成为 session_event
```

---

## 16.2 Storage

```text
1. source session 作为稳定事实来源容器保存
2. 每次 ingest 以 ingest_version 追加保存到 pending_ingests.jsonl
3. candidate_event 写入 candidate_events.jsonl
4. verified session_event 写入 session_events.jsonl
5. session.md 作为热工作视图做 compaction，不承担全量归档职责
6. session_wiki.md 引用 session_event
7. index.md 索引 Memory Block
8. task_wiki.md 作为总览页可增量刷新
9. views/*.md 作为可选派生视图
```

---

## 16.3 Retrieval

```text
1. 根据 task_id 找到任务目录
2. 读取 index.md
3. 找到相关 Memory Block
4. 从 Memory Block 找到 Evidence References
5. 根据 event_id / event_path 找到 session_events.jsonl
6. 读取 evidence_quote
7. 必要时回到 session.md
```

---

## 16.4 Update

```text
1. 已有 source session 收到新 ingest
2. 抽取 candidate_event
3. verification 后生成 session_event
4. 分别写入 candidate_events.jsonl 和 session_events.jsonl
5. 生成或更新该 session 的 session_wiki.md
6. 在 session_wiki.md 中生成或更新 Memory Block
7. 更新 index.md 中的 Memory Block 索引
8. 按需刷新 task_wiki.md
9. 如已有 topic view，按需刷新 views/*.md
10. 追加 log.md
11. 可选触发 lint
```

---

## 16.5 Forgetting

```text
1. session 删除 → source-level forgetting
2. event 错误 → event-level invalidation
3. 新事实覆盖旧知识 → knowledge-level supersession
4. 旧内容不再展示 → view-level forgetting
```

---

# 17. 最终结构总结

本系统的核心结构是：

```text
session.md
保存该 source session 的热工作视图。它会保留 root、最近热 ingest、以及被 candidate/session event 引用过的 entry，但不会无限膨胀成全量页。

candidate_events.jsonl
保存候选层 event，包含未正式通过 verification 的项。

session_events.jsonl
保存 verified session_events。

session_wiki.md
保存该 session 的一手 Wiki 页面，内部包含多个 Memory Blocks。

Memory Block
围绕某个主题、问题、决策轴或执行事项聚合 events。

KI Slot
Memory Block 内部的结构化栏目，包括 conclusion、rationale、objection、constraint、commitment、status、time、scope。

index.md
task 级导航索引，采用 Wiki Page → Memory Block 的两层结构，核心索引粒度是 Memory Block。

task_wiki.md
基于多个 session_wiki 和 Memory Blocks 汇总出的任务当前状态视图。
```

最终证据链路是：

```text
task_wiki.md / index.md
  → session_wiki.md
  → Memory Block
  → KI Slot
  → event_ref
  → session_events.jsonl
  → evidence_quote
  → session.md
```

---

# 18. 一句话概括

这套系统的核心思想是：

```text
先把 task 相关协作内容编译成 verified session_events，
再让 Wiki 层把 events 聚合成 session_wiki.md 中的 Memory Blocks。
index.md 负责用 Wiki Page → Memory Block 的两层结构做快速路由，
task_wiki.md 负责呈现当前任务状态。
更新和遗忘都沿着 event_ref 反向影响 Memory Block、index 和 task_wiki。
```

换句话说：

```text
event 负责可信，Memory Block 负责组织，index 负责定位，task_wiki 负责当前状态。
```

# 19. 评估

怎么评估你的 Task Wiki 系统？
分四层评估。
第一是 event 抽取质量，看 claim support rate、atomicity pass rate 和字段完整率。
第二是 Memory Block 组织质量，看分组准确率和 slot 填充准确率。
第三是问答质量，看 hit rate、faithfulness、citation accuracy 和 unsupported claim rate。
第四是业务指标，看用户是否减少重复询问、是否更快找到历史决策、人工纠错率是否下降。

## 5.4 Event 类型

第一版 event 使用 8 类。

这 8 类不是 Wiki 模块，而是可验证事实类型。

```text
1. conclusion_event：结论 / 口径 / 决定
2. rationale_event：理由 / 依据
3. objection_event：异议 / 担忧 / 反对意见
4. constraint_event：约束 / 边界 / 禁止项
5. commitment_event：承诺 / 行动项
6. status_event：状态事实
7. time_event：时间点 / 截止日期 / 里程碑
8. scope_event：范围 / 阶段 / 适用对象
```

```text
1. 是否有 session_event 没有被对应 session_wiki.md 引用
2. 是否有 session_wiki.md 没有 Evidence References
3. 是否有旧结论被新 event 覆盖但还显示为 active
4. 是否有开放异议长期未解决
5. 是否有行动项过期
6. 是否有 session 被删除但 event 仍在支撑 Wiki
7. 是否有 claim 强度超过 quote
8. 是否有同一 topic 下的结论冲突
9. 是否有孤立 session_wiki.md 或孤立 Memory Block
10. 是否缺少必要交叉引用
```

## 6.6 Verification 原则

```text
Evidence-first：先找 quote，再生成 claim。
Core-triggered：只有 Core 能触发 event，Context 只消歧。
Claim minimality：一条 event 只表达一个事实。
Modality preservation：保留原文强度，例如“暂定”不能写成“确认”。
No slot hallucination：字段缺失就填 null，不补。
Typed verification：不同 event 类型使用不同校验规则。
```

# 已确认的 history 调整

1. Wiki 更新时不保存整页旧快照，而是在 `session_wiki.md` 的 KI Slot 内维护 `Current` / `History`。
2. 新增或更新后的当前项放在 `Current`，同一 KI 的旧项放在 `History`。
3. `task_wiki.md` 继续只展示当前状态；`index.md` 继续只负责定位 Memory Block。
4. 溯源链路是 `index.md → session_wiki.md#Memory Block → KI Slot History → Event Ref / Entry Ref / quote`。
