# Builder Agent 设计方案

## 1. 文档目标

这份文档描述一个专门用于**构造飞书企业协作数据集**的 Builder Agent。

目标不是直接手写一份 fake dataset，而是让 agent：

1. 先生成符合企业真实协作逻辑的世界设定与事实真相
2. 再把这些事实分散到多个飞书 surface
3. 调用 `lark-cli` 真正在飞书里创建群、消息、文档、任务、会议等对象
4. 把文档、任务、日历中的关键信息同步回对话
5. 最后从飞书回收真实对象，生成：
   - Feishu channel ingress dataset
   - canonical eval dataset
   - oracle truth / gold dataset

这份方案服务于 `amem_docs/design/2026-04-24-plan.md` 中的目标：

- 支撑跨会话、跨文档、跨工具、跨工作状态的连续协作记忆
- 重点验证“飞书项目决策与上下文记忆”
- 验证系统能否恢复：
  - 当前状态
  - 负责人
  - 为什么会变成这样
  - 下一步该做什么

---

## 2. 第一版的边界

这里先明确第一版要验证的不是“飞书所有对象类型都直接进入 OpenClaw”，而是：

- **Feishu 作为 OpenClaw 的一个 channel**
- **OpenClaw 第一版主链消费的是对话型输入**

也就是说，第一版真正进入 OpenClaw 主数据集的是：

- 主群消息
- thread 回复
- system message
- 转发消息
- 卡片消息中的文本信息

而这些对象：

- 文档
- 任务
- 日历

在第一版里仍然会创建，也仍然是企业协作场景的一部分，但它们**不作为独立 object ingestion 主链进入 OpenClaw**，而是要通过：

- 群聊同步
- thread 补充
- 会议结论回帖
- 任务状态播报

这样的方式进入对话流。

所以第一版更准确的目标是：

```text
真实飞书对象
  -> 文档/任务/日历产生事实
  -> 人在群聊 / thread 中同步这些事实
  -> OpenClaw 通过 Feishu channel 接收这些消息事件
  -> Graph / Memory 再从对话中恢复状态与关系
```

这也是为什么第一版最重要的不是“把所有对象直接接进 OpenClaw”，而是“确保关键事实最终进入对话”。

---

## 3. 为什么不能只写 Story Spec

单纯的 story spec 有两个问题：

1. 它容易变成线性剧情
   - 一条消息接一条消息
   - 每个事实只出现一次
   - 没有真实企业里常见的信息埋藏、更新延迟、口径不一致

2. 它无法自然支持你要验证的核心难点
   - 同一事实散落在多个 surface
   - 不同角色对同一事实有不同表述
   - 某些信息是旧的，但没有被显式撤回
   - 有些关键信息只出现在 thread / task comment / 文档角落 / meeting note

所以这里不能只生成“故事”，而是要生成一个**企业协作仿真计划**。

---

## 4. Builder Agent 的核心职责

Builder Agent 不是单一职责的 message generator，而是一个四层编排器：

1. 生成企业世界与组织关系
2. 生成 ground truth timeline
3. 生成多 surface evidence plan
4. 生成“对象事实 -> 对话同步”的 materialization plan
5. 调用 `lark-cli` 在飞书里 materialize，并回读真实对象

一句话概括：

```text
world spec
  -> truth timeline
  -> surface evidence plan
  -> conversation sync plan
  -> execution plan
  -> lark-cli materialization
  -> channel-ingress / canonical / oracle outputs
```

---

## 5. 四层输入设计

## 4.1 World Spec

这一层定义企业环境本身，不直接生成具体消息。

它描述：

- 公司背景
- 部门结构
- 上下级关系
- 角色职责
- 项目目标
- 协作习惯
- 权限与流程约束
- 典型冲突来源

这层的意义是让后续内容“像一个公司”，不是像一段被写死的 prompt 样例。

建议字段：

- `workspace_name`
- `business_context`
- `departments`
- `employees`
- `roles`
- `reporting_lines`
- `project_catalog`
- `approval_policy`
- `communication_norms`
- `risk_patterns`

示例冲突：

- 产品想提前上线
- 研发担心技术债与排期
- 运维限制灰度时间窗
- 安全/法务审批滞后
- 财务/采购流程慢于项目推进
- 文档与群聊的结论不同步

## 4.2 Truth Timeline

这一层定义真实世界到底发生了什么，是隐藏给评测系统的“真相”。

它记录：

- 真正的 owner
- 真正的 blocker
- 真正的 stage
- 真正的 approval status
- 真正的 next action
- 哪些事实后来被修正
- 哪些 earlier evidence 已经失效

这层不能直接暴露给用户侧 evidence，否则就失去了验证跨来源重建真相的价值。

建议字段：

- `truth_id`
- `subject_ref`
- `occurred_at`
- `truth_type`
- `before`
- `after`
- `confidence`
- `supersedes_truth_id`
- `notes`

支持的 truth 类型建议至少覆盖：

- `owner_changed`
- `stage_changed`
- `approval_status_updated`
- `blocked`
- `unblocked`
- `next_action_set`
- `decision_made`
- `deadline_changed`
- `scope_changed`

## 5.3 Surface Evidence Plan

这一层决定同一个 truth 会以什么方式出现在飞书里。

核心原则：

- 同一个 truth 不只出现一次
- 不同 surface 允许表达不完整
- 有些 surface 故意滞后
- 有些 surface 保留过时说法
- 有些 evidence 只透露一半信息

支持的 surface：

- 群聊主群消息
- 线程回复
- P2P 消息
- 任务正文
- 任务 comment
- 文档正文
- 文档后续修订
- 会议日程
- 会议纪要
- 多维表格记录
- 审批状态 / 审批卡片

但第一版需要再额外区分两件事：

- **事实出现在哪个 source object 上**
- **这些事实最后是否被同步进对话**

因为真正进入 OpenClaw 第一版主链的是后者。

所以对于文档、任务、日历类 surface，Builder Agent 不能只创建对象，还必须补一条或多条同步消息，例如：

- 文档更新后，在主群同步“当前版本结论”
- 任务 blocker 更新后，在 thread 里说明 blocker
- 会议结束后，在群里贴会议结论

建议字段：

- `surface_event_id`
- `truth_refs`
- `surface_type`
- `channel_ref`
- `speaker_ref`
- `audience`
- `timestamp`
- `visibility`
- `fidelity`
- `staleness`
- `contradiction_kind`
- `payload_plan`

其中最重要的几个机制是：

- `fidelity`
  - 这条 surface 是否完整表达真相
- `staleness`
  - 这条 surface 是否已经落后于 truth
- `contradiction_kind`
  - 这条 surface 和真实状态的偏差类型

推荐支持的 contradiction 类型：

- `outdated_deadline`
- `outdated_owner`
- `partial_reason`
- `missing_dependency`
- `optimistic_status`
- `ambiguous_reference`
- `departmental_bias`

## 5.4 Conversation Sync Plan

在第一版里，需要在 surface plan 和 execution plan 之间新增一层：

- `conversation_sync_plan`

它的职责是显式规定：

- 哪些文档事实要被发回群聊
- 哪些任务变化要被补进 thread
- 哪些会议结论要在主群同步
- 哪些旧口径不能立刻撤回，必须保留不一致

建议字段：

- `sync_event_id`
- `source_surface_type`
- `source_object_ref`
- `target_chat_ref`
- `target_thread_ref`
- `speaker_ref`
- `sync_intent`
- `payload_plan`
- `staleness_mode`

建议支持的 `sync_intent`：

- `announce_decision`
- `report_blocker`
- `report_owner_change`
- `report_deadline_change`
- `summarize_meeting`
- `quote_doc_update`
- `quote_task_status`

这一层是第一版里最关键的新约束：

- 文档/任务/日历不再假设“OpenClaw 会直接吃对象”
- 而是要求 agent 把关键事实同步回对话

## 5.5 Execution Plan

这一层是交给 `lark-cli` 的可执行动作序列。

Builder Agent 在这里不再做“业务推理”，而只做“飞书对象落地”。

动作类型建议：

- `create_chat`
- `add_chat_members`
- `send_message`
- `reply_in_thread`
- `create_doc`
- `update_doc`
- `create_tasklist`
- `create_task`
- `update_task`
- `comment_task`
- `create_calendar_event`
- `update_calendar_event`
- `sync_doc_summary_to_chat`
- `sync_task_status_to_chat`
- `sync_meeting_summary_to_chat`
- `fetch_chat_messages`
- `fetch_thread_messages`
- `fetch_doc`
- `fetch_task`
- `fetch_calendar_event`

审批在第一版单独处理：

- 如果已有审批模板和权限，允许纳入 execution plan
- 如果当前环境缺少可创建审批实例的稳定路径，则第一版先把审批当作：
  - 群卡片 / interactive 消息
  - 文档记录
  - 任务阻塞状态
  的组合模拟

---

## 6. 为什么要故意制造“不一致”

因为你要验证的不是简单抽取，而是：

- 跨来源事实整合
- 时序更新
- 旧信息淘汰
- 关系恢复
- 当前状态判断

所以 Builder Agent 必须显式制造以下现象：

1. 多源重复
   - 同一决定在群聊、任务、文档里都出现

2. 旧说法残留
   - 主群还在说 5 号上线，但任务已经改成 8 号

3. 口径不一致
   - 产品说“基本可以上线”
   - 运维说“只能灰度”
   - 安全说“审批未完不能发布”

4. 信息埋藏
   - blocker 的真正原因只出现在 thread reply 或 task comment

5. 更新延迟
   - 文档更新落后于会议结论

6. 局部真相
   - 某个文档只知道审批通过，不知道运维 blocker

如果没有这些现象，就很难证明 graph index / memory engine 的价值。

---

## 7. 飞书侧需要准备什么

Builder Agent 在真正执行前，需要先检查飞书环境是否具备最小资源。

## 6.1 最小资源集合

建议第一版至少创建：

- 1 个项目主群
- 1 个侧边协作群
- 1 条主线程
- 1 篇项目决策文档
- 1 篇运维/上线 checklist 文档
- 1 个 tasklist
- 2 到 5 个任务
- 1 个会议或日历事件

如果审批能力成熟，再扩展：

- 1 条真实审批实例

## 6.2 人员与身份

Builder Agent 需要能够拿到或约定这些对象：

- 员工列表
- open_id
- 部门归属
- 上下级关系
- 是否能被加入群
- 是否可被指派任务

如果当前租户里没有足够多的真实用户，可以先采用“单用户 + 多个 bot/虚拟角色映射”的过渡方案，但需要在文档中显式标记：

- 这是临时仿真，不是真正多用户租户

## 6.3 权限前置检查

Builder Agent 在执行前要先检查：

- IM 创建群与发消息权限
- 文档创建/更新权限
- 任务创建/修改权限
- 日历创建权限
- 是否具备审批相关 scope

如果某类资源缺权限：

- 不要直接失败
- 要写入 capability report
- 并自动选择降级方案

例如：

- 无审批实例创建能力
  - 降级为 interactive message + task blocker 模拟
- 无会议纪要能力
  - 降级为日历 + 文档纪要

---

但需要强调：

- 这些对象不是第一版 OpenClaw 主输入本身
- 它们的关键事实必须再通过消息同步进入主群或 thread

所以第一版最小可验证输入仍然是：

- 主群消息
- thread 回复
- 侧边群消息

## 8. Builder Agent 的输出

Builder Agent 最终应输出 3 层正式产物，以及 1 份运行报告。

## 8.1 Channel Ingress Dataset

第一版最重要的 raw 产物不再表述成“所有飞书对象的统一 ingress”，而是：

- `feishu_channel_events.jsonl`
- `feishu_channel_contexts.jsonl`

它们对齐的是 OpenClaw Feishu channel 真实最早两层：

- `extensions/feishu/src/event-types.ts` 的 `FeishuMessageEvent`
- `extensions/feishu/src/types.ts` 的 `FeishuMessageContext`

这两份数据集只覆盖对话型输入。

## 8.2 Raw Mirror

目标：

- 保存从 `lark-cli` 回收的最原始对象
- 保留 live id
- 给后续转换 `FeishuMessageEvent` / `FeishuMessageContext` 使用

建议路径：

- `raw/feishu_raw_events.jsonl`

建议字段：

- `raw_event_id`
- `source_platform`
- `source_kind`
- `message_id`
- `chat_id`
- `chat_type`
- `thread_id`
- `root_id`
- `parent_id`
- `message_type`
- `sender_open_id`
- `create_time`
- `mentions_json`
- `content_raw`
- `source_locator_json`

注意：

- 这层可以包含 docs/task/calendar
- 但它不是第一版 OpenClaw channel 主输入

## 8.3 Canonical Dataset

目标：

- 供 graph index / eval / query 使用
- 是 raw 层之上的统一办公事件层

建议路径：

- `canonical/office_events.jsonl`

字段可以延续你当前 `eval/office_dataset` 的风格，例如：

- `event_id`
- `snapshot_id`
- `workspace_id`
- `sender_name`
- `content_text`
- `doc_refs`
- `task_refs`
- `approval_refs`
- `entity_refs`
- `relations`
- `raw_event_ref`

## 8.4 Oracle / Gold Layer

目标：

- 记录 ground truth
- 给 scorer 和人工分析使用

建议路径：

- `oracle/truth_timeline.json`
- `oracle/query_set.json`

其中 `query_set.json` 需要显式包含：

- 问题
- 问题类型
- gold answer
- gold evidence
- supporting truth refs

## 8.5 Build Report

目标：

- 解释这次飞书落地是否完整成功
- 哪些资源真实创建了
- 哪些地方做了降级

建议路径：

- `build/build_report.json`

字段建议包括：

- `workspace_name`
- `build_started_at`
- `build_finished_at`
- `capability_report`
- `created_resources`
- `fetched_resources`
- `degraded_steps`
- `failed_steps`
- `dataset_paths`

---

## 9. Builder Agent 的执行流程

推荐流程：

1. 输入世界约束
   - 读取企业场景目标
   - 读取资源边界与权限

2. 生成 `world_spec`
   - 组织、角色、流程、冲突模式

3. 生成 `truth_timeline`
   - 定义真实决策与状态变化

4. 生成 `surface_evidence_plan`
   - 把 truth 分散到多个 surface
   - 显式注入不一致、延迟、埋藏证据

5. 生成 `conversation_sync_plan`
   - 明确哪些对象事实要同步进主群 / thread

6. 生成 `execution_plan`
   - 映射为 `lark-cli` 动作

7. 物化到飞书
   - 建群
   - 发消息
   - 回 thread
   - 建 doc
   - 更 doc
   - 建 task
   - comment task
   - 建 calendar event
   - 把对象结论同步进对话

8. 从飞书回读
   - 获取真实对象
   - 记录真实 ID 和时间

9. 产出多层数据集
   - channel-ingress
   - raw
   - canonical
   - oracle

10. 生成 build report

---

## 10. Agent 和 Lark CLI 的分工

Builder Agent 与 `lark-cli` 的分工必须清晰。

## 9.1 Agent 负责什么

- 生成世界设定
- 生成 truth
- 设计冲突与不一致
- 决定哪些信息放在哪些 surface
- 决定哪些对象事实必须同步进对话
- 决定执行顺序
- 决定降级策略
- 生成 query / gold

## 9.2 `lark-cli` 负责什么

- 在飞书中创建资源
- 更新资源
- 把对象结论发回聊天
- 读取资源
- 返回真实对象字段
- 提供真实 ID / URL / 时间戳

一句话概括：

- Agent 负责“编排企业协作真相和哪些事实要进入对话”
- `lark-cli` 负责“把它变成真实飞书对象与真实对话”

---

## 10. 第一版建议范围

为了降低复杂度，第一版不要追求全域全量。

建议第一版只覆盖：

- IM
  - 群消息
  - thread 回复
- Docs
  - 决策文档
  - 上线 checklist
- Tasks
  - tasklist
  - task
  - task comment
- Calendar
  - 会议或上线时间事件

审批第一版建议作为“弱真实”处理：

- 若可直接创建真实审批实例，则纳入
- 若当前飞书租户或 CLI 能力不稳定，则先：
  - 在群里发审批状态卡片/文本
  - 在任务和文档里记录审批状态
  - 把真实审批留到第二版

---

## 11. 与当前 `eval` 体系的关系

Builder Agent 不是要替代整个 `eval`，而是给它补一层更真实的数据源。

建议角色分工：

- `eval/office_dataset`
  - 保留
  - 但定位为 canonical / eval 层
- 新 builder 输出的 `raw/feishu_raw_events.jsonl`
  - 成为 raw layer
- builder 输出的 oracle truth
  - 成为新的 gold / scorer 输入

也就是说：

- `eval` 不删除
- 但不再把当前 `office_events.jsonl` 当 raw ingress truth

---

## 12. 下一步落地建议

建议按下面顺序实施：

1. 先固定 4 个 schema
   - `world_spec.json`
   - `truth_timeline.json`
   - `surface_evidence_plan.json`
   - `execution_plan.json`

2. 写一个 builder agent prompt / skill
   - 明确它可以使用 `lark-im` / `lark-doc` / `lark-task` / `lark-calendar`

3. 先做一个最小 snapshot
   - 1 个项目
   - 2 个群
   - 2 篇文档
   - 3 个任务
   - 1 个会议

4. 从飞书回读并生成：
   - raw mirror
   - canonical office events
   - oracle truth

5. 再把这份数据接入 graph index / recall / eval

---

## 13. 结论

要验证企业级长程协作 memory，不能只靠手写 story spec，也不能只靠当前 synthetic eval fixture。

更合理的方式是：

```text
企业世界设定
  -> 真实 truth timeline
  -> 多 surface 不一致 evidence plan
  -> lark-cli 在飞书中真实物化
  -> 回读真实对象
  -> 生成 raw / canonical / oracle 三层数据集
```

这套 Builder Agent 的价值在于：

1. 数据集更像真实企业协作
2. 字段更接近真实 Feishu -> OpenClaw 输入
3. 能显式构造你要验证的不一致、更新延迟、信息埋藏
4. 能真正测出 graph index / memory engine 在跨工具、跨文档、跨状态条件下是否有效
