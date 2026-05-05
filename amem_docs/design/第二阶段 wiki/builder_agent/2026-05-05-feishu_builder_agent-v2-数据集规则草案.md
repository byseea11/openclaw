# 2026-05-05 `feishu_builder_agent` V2 数据集规则草案

## 1. 文档目的

这份文档的目标，是给 `feishu_builder_agent` 的下一阶段升级先定义一套**数据集规则草案**。

当前代码已经是纯 V2 Builder，默认落盘到：

- `amem_docs/ds/feishu_im_dataset_v2`

当前默认主产物已经包括：

- `input/case_seed.json`
- `input/case_world.json`
- `input/characters.json`
- `input/conversation_plan.json`
- `input/utterance_plan.jsonl`
- `data/realized_messages.jsonl`
- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`
- `checks/conversation_complexity_report.json`
- `checks/dataset_validation_report.json`
- `execution_plan.json`
- `execution_result.json`
- `lark_fetch_records.jsonl`
- `openclaw_message_ingress.jsonl`

但当前它仍然更接近：

> 一个已经具备 V2 对象分层、但还没有完成批量评测与复杂度校准收口的 Task Wiki 数据集构建器

而下一步要继续推进到：

> 一个能稳定批量生成复杂、多轮、多 source、并直接服务 Task Wiki 方法评测的多代理动态仿真器

所以在继续改代码之前，先要把：

- 什么样的 case 才算合格
- 什么样的对话才算“多轮”
- 什么样的复杂度才能体现 Task Wiki 的优势
- `locomo` 应该怎样被参考

这些问题先写成规则。

---

## 2. V2 的目标变化

当前 Builder 的已完成目标是：

- 构造一条最小可运行的飞书 IM 数据链路
- 让 OpenClaw 能吃到真实 / 半真实的 ingress 数据

接下来继续推进的目标是：

1. 生成**更像真实企业协作**的 case
2. 生成**多轮、跨 source、跨时间**的讨论
3. 生成能触发：
   - `task binding`
   - `session_event`
   - `current state`
   - `supersession / invalidation`
   - `lint`
   - `forgetting`
   的复杂样本
4. 让数据强度足以和普通 summarization / 普通 RAG / 简单规则抽取拉开差距

一句话说：

> V2 不再只是“能跑”，而是“能有效证明方法优势”。

---

## 3. 设计原则

V2 Builder 的规则先固定 6 条原则。

### 3.1 先定义世界，再生成对话

不能再让 `case_spec` 直接决定 story 和消息。

V2 要先定义：

- 组织背景
- 角色阵营
- 冲突轴
- 外部压力
- 隐藏约束
- 可能反转点

再在这个世界里生成对话。

也就是说，生成顺序要从：

```text
case_spec -> story -> timeline -> messages
```

升级成：

```text
case_seed -> case_world -> characters -> conversation_plan -> messages
```

### 3.2 多轮不是“消息更多”，而是“状态会演化”

V2 不是简单把消息数量从 6 条加到 20 条。

真正的“多轮”必须体现：

- topic 被反复讨论
- 立场之间出现博弈
- 当前结论被后续修正
- 某些事实只在后续补充里出现
- 某些信息在主群和 thread 中口径不一致

### 3.3 必须服务于 Task Wiki 的三层目标

V2 数据不是泛用聊天数据，而是专门服务于：

1. Layer 1 task binding
2. Layer 2 typed `session_event`
3. Layer 3 `session_wiki / index / task_wiki`

因此它必须故意包含：

- 可绑定 task 的显式锚点
- 足够丰富的 8 类事件
- 足够多的 current state 演化

### 3.4 事件和对话都要可追溯

数据生成不能只追求“像人聊天”，还要保证：

- 每条关键事件都能回到某条具体消息
- 后续 `candidate_event` 和 `session_event` 的证据能稳定落地
- 对话中的关键信息不要只存在于隐含语气中

### 3.5 允许 LLM 驱动，但必须程序约束

V2 可以让 LLM 做：

- case world 生成
- 角色设定
- conversation plan 草稿
- utterance realization

但必须由程序约束：

- 复杂度下限
- topic 覆盖
- source 分布
- event family 覆盖
- 时间演化

也就是说：

> 不是“LLM 随便生成”，而是“LLM 在规则内生成”。

### 3.6 参考 `locomo`，但不直接照搬

`locomo` 对我们最大的价值，不是它的原文，而是：

- 长时程 conversation
- multi-session 结构
- persona 驱动
- 事件因果链
- 跨 session 记忆压力

V2 应该借这些设计原则，但输出必须是我们自己的：

- 企业协作 domain
- 飞书 IM 结构
- Task Wiki 目标导向 schema

---

## 4. V2 数据集对象层级

V2 建议把 Builder 的数据对象拆成 5 层。

### 4.1 `case_seed`

最小输入，只负责定义 case 的方向。

最小字段建议：

- `case_id`
- `task_id`
- `domain`
- `company_type`
- `main_goal`
- `difficulty`
- `seed`
- `complexity_profile`

### 4.2 `case_world`

由 LLM + 程序约束共同生成。

这是 V2 的新核心对象。

建议包含：

- `task_id`
- `task_title`
- `business_context`
- `organizational_context`
- `external_pressure`
- `stakeholder_groups`
- `conflict_axes`
- `hidden_constraints`
- `likely_reversal_points`
- `success_criteria`

它回答的问题是：

> 这个 case 为什么会复杂，复杂在哪里。

### 4.3 `characters`

角色不再只是 roster，而是要有足够强的协作行为差异。

每个角色建议至少包含：

- `person_id`
- `name`
- `department`
- `role`
- `responsibility`
- `stance`
- `risk_preference`
- `communication_style`
- `conflict_bias`
- `information_access_level`
- `default_channels`

### 4.4 `conversation_plan`

这是 V2 最大的新增对象。

它不直接是消息，而是一个**多轮讨论计划**。

建议包含：

- `sessions`
- `topics`
- `topic_state_transitions`
- `source_layout`
- `turn_plan`
- `required_event_coverage`

也就是先决定：

- 有几次 session
- 每次讨论什么
- 哪些 topic 在主群，哪些进 thread
- 哪些 topic 会被修正
- 哪些 topic 会产生 objection / commitment / status update

### 4.5 `utterance_plan / realized_messages`

最后一层才是消息文本。

每条消息建议显式保留：

- `message_role`
- `source_type`
- `topic_key`
- `turn_purpose`
- `supports_event_types`
- `references_previous_turns`
- `content_text`

---

## 5. 多轮复杂度规则草案

这里给出一版可以直接程序化校验的“多轮”规则。

### 5.1 会话层下限

每个 case 至少满足：

- `session_count >= 3`
- `source_session_count >= 3`
- `message_count >= 18`

其中 `source_session_count` 至少包括：

- 1 个主群 chat session
- 1 个 thread session
- 1 个后续补充 source

后续补充 source 可以是：

- 第二个 thread
- comment
- doc comment
- 同群后续口径更新

### 5.2 topic 层下限

每个 case 至少包含：

- `topic_count >= 3`

并且 topic 类型不能都一样，至少应覆盖：

- 时间 / 发布口径类 topic
- 风险 / objection 类 topic
- 执行 / commitment / 状态类 topic

### 5.3 topic 交错规则

至少要有：

- `cross_topic_interruptions >= 2`

意思是：

- topic A 出现
- topic B 插入
- topic A 之后再次出现

而不是 topic A 完整说完，再说 topic B。

### 5.4 状态演化规则

至少要有：

- `state_transition_count >= 4`

允许的状态演化包括：

- 初始目标 -> 风险暴露
- 风险暴露 -> 口径收紧
- 口径收紧 -> 新承诺
- 旧时间点 -> 新时间点
- 开放 objection -> 已解决
- 草案范围 -> 收缩范围

### 5.5 修正规则

至少要有：

- `supersession_count >= 1`
- `cross_source_revision_count >= 1`

这意味着：

- 至少有一个 topic 的当前态被后续消息更新
- 至少有一次“后续 source 改写前一个 source 的口径”

例如：

- thread 里先说 5 月 5 日
- 主群后续改成“不要把 5 月 5 日当已确认日期”

### 5.6 thread 深度规则

至少要有：

- `thread_reply_depth >= 3`

因为如果 thread 只有 1 条 reply，Layer 2 / 3 的 root + reply 演化压力还是偏弱。

---

## 6. 事件覆盖规则草案

V2 的 case 不要求每条都覆盖 8 类事件，但不能过窄。

### 6.1 事件家族下限

每个 case 至少覆盖：

- `event_family_coverage >= 5`

推荐目标：

- `event_family_coverage >= 6`

### 6.2 必须出现的事件类型

每个中高复杂度 case，建议至少出现：

- `conclusion_event`
- `objection_event`
- `constraint_event`
- `status_event`
- `time_event`

因为这 5 类最能稳定拉开和普通摘要的差距。

### 6.3 建议出现的事件类型

推荐至少出现其中 1~2 类：

- `commitment_event`
- `rationale_event`
- `scope_event`

### 6.4 topic 演化规则

至少有一个 topic 满足：

- 有 `conclusion_event`
- 后续有 `time_event` 或 `status_event` 修正

至少有一个 topic 满足：

- 有 `objection_event` 或 `constraint_event`
- 后续有 `status_event` 或 `commitment_event`

---

## 7. Source 分布规则草案

V2 要显式控制 source，而不是只让所有消息都堆在一个 thread 里。

### 7.1 基础 source 组合

每个 case 至少应包括：

- `chat`
- `thread`

高复杂度 case 推荐包括：

- `chat`
- `thread`
- 第二个 `thread`
- `comment` 或 `doc/comment`

### 7.2 source 职责分工

建议默认分工：

- `chat`
  - 用于主口径、跨 topic 协调、后续修正
- `thread`
  - 用于展开某个具体 blocker / 风险 / 时间点
- `comment/doc`
  - 用于补充正式说明、外部约束、行动项确认

### 7.3 source 间不一致

至少有一个 case 应包含：

- 主群说法与 thread 说法不完全一致

因为这类样本最能验证：

- task binding 归并
- current state 收敛
- supersession
- lint

---

## 8. 角色与博弈规则草案

V2 不能只有“不同人轮流说同一个结论”，必须有立场差异。

### 8.1 角色数量

建议：

- `character_count >= 6`

至少包括：

- 推动型角色
- 风险型角色
- 约束型角色
- 裁决型角色

### 8.2 角色分工

建议每个 case 至少包含这 4 类角色：

1. `driver`
   - 推动目标尽快落地
2. `blocker`
   - 提出 blocker / objection
3. `constraint_owner`
   - 提出不能绕过的规则
4. `resolver`
   - 做权衡、修正 current state

### 8.3 信息不对称

至少要有：

- 某些角色知道隐藏依赖
- 某些角色只知道外部压力
- 某些角色只对正式口径负责

这样对话里才会有：

- 补充
- 反驳
- 修正
- 再确认

---

## 9. 评测压力规则草案

V2 的 case 不是只为了“看起来真实”，而是要故意施加记忆压力。

### 9.1 必须具备的压力类型

建议每个 case 至少命中其中 3 类：

1. **时间压力**
   - 多个日期口径
   - 日期被修正
2. **角色压力**
   - 不同部门目标不一致
3. **source 压力**
   - 主群 / thread / comment 分散
4. **状态压力**
   - 旧结论被新结论覆盖
5. **追溯压力**
   - 关键信息分散在多条消息
6. **失效压力**
   - 某条旧信息失效后 current state 要收缩

### 9.2 用于验证第三层能力的 case

至少应该专门构造一批 case，用于验证：

- `supersession`
- `invalidation`
- `revoke`
- `lint`
- `current state` 收敛

否则第三层虽然能跑，但证明不出价值。

---

## 10. 与 `locomo` 的关系

### 10.1 可以借的部分

V2 可以参考 `locomo` 的：

- multi-session conversation 结构
- persona 驱动生成方式
- event / summary 分层
- temporal span 控制
- complexity knob 设计

例如可以参考这些文件：

- `locomo/data/locomo10.json`
- `locomo/data/msc_personas_all.json`
- `locomo/generative_agents/generate_conversations.py`

### 10.2 不建议直接照搬的部分

V2 不建议直接把 `locomo` 的原始对话拿来当主数据源，原因包括：

- 许可证是 `CC BY-NC 4.0`
- domain 偏个人生活对话
- 大量样本是双人对话，不是企业多角色协作
- 任务目标更偏 long-term memory QA，不是 Task Wiki

### 10.3 推荐做法

推荐把 `locomo` 当成：

- 复杂度参考系
- 生成机制参考系
- persona / session / event 分层参考系

而不是直接当成：

- 默认训练数据
- 默认演示数据
- Builder 主链的直接输入

---

## 11. Builder V2 的最小新增对象

如果按这份规则继续推进，我建议 V2 最少新增这 3 个文件对象：

### 11.1 `case_world.json`

定义：

- 组织背景
- 冲突轴
- 外部压力
- 隐藏约束
- 成功标准

### 11.2 `conversation_plan.json`

定义：

- session 规划
- topic 分布
- source 布局
- turn 顺序
- 必须发生的状态演化

### 11.3 `conversation_complexity_report.json`

定义：

- session_count
- message_count
- topic_count
- thread_reply_depth
- supersession_count
- cross_source_revision_count
- event_family_coverage
- state_transition_count
- lint_pressure_score

这个对象的作用是：

> 自动判断这条 case 是否“足够复杂”，能不能拿来证明方法优势。

---

## 12. 一句话总结

V2 Builder 的核心，不是把消息数量简单变多，而是要把 case 生成升级成：

> **LLM 驱动的 case world + 多轮 conversation plan + 程序约束的复杂度校验**

并且让数据显式具备：

- 多轮
- 多 source
- 多 topic
- 状态演化
- current state 修正
- 可追溯证据链

只有这样，后续 Task Wiki 三层方法的优势才会被稳定地展示出来。
