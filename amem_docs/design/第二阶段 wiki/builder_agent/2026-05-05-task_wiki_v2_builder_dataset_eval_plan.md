# Task Wiki V2 Builder 与数据集评测完整实现计划

## 0. 文档目的

本文档用于明确 `feishu_builder_agent` 在已经切到纯 V2 口径之后，后续还需要完成的核心工作。

V2 的目标不是简单做一个“长对话数据集”，也不是复刻 `τ²-bench`，而是构建一套可以同时支撑数据生成、数据验证和系统评测的企业协作记忆 benchmark。

最终目标是：

```text
1. 生成一批能跑 OpenClaw 的飞书协作数据
2. 验证这些数据本身是否合格
3. 用这些数据比较：
   - OpenClaw 原始处理方式
   - Task Wiki / Event + Memory Block + Current State 方式
```

因此，V2 需要同时完成两类改造：

```text
Builder 改造：
让系统不再只能生成一个固定 case，而是能批量生成多样、复杂、可复现的 case。

评测体系改造：
让生成的数据可以用于验证 Task Wiki 是否比 OpenClaw 原始处理方式更能维护正确、可追溯、当前有效的项目记忆。
```

---

## 1. 当前 V2 基线与剩余问题

当前代码已经具备完整的纯 V2 主链：

```text
case_spec
  -> case_seed
  -> case_world
  -> characters
  -> conversation_plan
  -> utterance_plan
  -> realized_messages
  -> gold
  -> checks
  -> execution_plan
  -> execute
  -> collect
  -> adapt
```

当前默认落盘目录已经是：

- `amem_docs/ds/feishu_im_dataset_v2`

当前真正还没有收完的，不再是“从 V1 升级到 V2”，而是：

```text
1. 批量 case 生成能力还没补完
2. locomo complexity calibrator 还没接入
3. baseline / Task Wiki scoring 还没形成完整批处理评测链
4. gold 的人工 review / 修订入口还没继续细化
```

---

## 2. V2 总体目标

V2 最终要形成如下闭环：

```text
case_seed
  → case_world
  → characters
  → conversation_plan
  → utterance_plan
  → realized_messages
  → openclaw_message_ingress
  → gold expected state
  → dataset validation
  → component scoring
  → system evaluation
```

一句话：

```text
V2 Builder 不只是“生成消息”，而是生成一套可评测的项目记忆 case。
```

每个 case 最终应该包含：

```text
cases/<case_id>/
  input/
    case_seed.json
    case_world.json
    characters.json
    conversation_plan.json
    utterance_plan.jsonl

  data/
    realized_messages.jsonl
    openclaw_message_ingress.jsonl

  gold/
    expected_events.jsonl
    expected_memory_blocks.json
    expected_current_state.json

  eval/
    eval_questions.json
    scoring_config.json

  checks/
    conversation_complexity_report.json
    dataset_validation_report.json
```

---

## 3. V2 的核心原则

### 3.1 LLM 负责多样性，规则负责可评测性

V2 不应该全部 LLM 化，也不应该继续纯规则模板化。

推荐边界：

```text
LLM 用在：
- case_world 生成
- characters 生成
- conversation_plan 草稿
- utterance realization
- gold draft 辅助生成

规则用在：
- schema validation
- complexity validation
- execution_plan 生成
- lark-cli 执行
- collect
- adapt
- evidence quote 校验
- scoring
```

核心原则：

```text
LLM 负责“内容多样性”。
规则负责“结构正确性、可复现性和可评测性”。
```

---

### 3.2 不要直接生成消息，要先生成计划

V2 不建议让 LLM 直接生成完整对话。

应该先生成：

```text
case_world
→ conversation_plan
→ utterance_plan
→ realized_messages
```

这样可以保证：

```text
1. 每个 case 的复杂度可控
2. 每条关键消息的作用可追溯
3. gold event 能稳定回到 message_id 和 evidence_quote
4. 后续可以做 dataset validation 和 scoring
```

---

### 3.3 评测对象不是 Raw RAG，而是 OpenClaw 原始处理方式

V2 的比较对象应该是：

```text
Baseline:
OpenClaw 原始处理方式

Your Method:
OpenClaw + Task Wiki / session_event / Memory Block / current state
```

不要把主要 baseline 写成 Raw RAG，否则会偏离项目实际价值。

---

### 3.4 τ-bench / τ²-bench 只参考思想，不直接复刻

当前阶段不需要完整实现 `τ²-bench`。

应该参考的思想只有两个：

```text
1. Final State Evaluation
   不只看文本输出，而要看最终系统状态是否正确。

2. Repeated Reliability
   同一类 case 可以多跑几次，看系统是否稳定识别正确 current state。
```

当前阶段不需要：

```text
- 完整 user simulator
- agent/user 双控工具环境
- Dec-POMDP 式动态环境
- 复杂 pass^k benchmark
```

这些可以等后续系统需要模拟持续互动、撤回、遗忘、用户主动修改环境时再考虑。

---

## 4. V2 数据对象设计

### 4.1 `case_seed.json`

#### 作用

`case_seed.json` 是最小输入，只负责定义 case 的方向，不负责写死故事和消息。

V1 的顺序是：

```text
case_spec → story → characters → timeline → execution_plan
```

V2 应该改成：

```text
case_seed → case_world → characters → conversation_plan → messages
```

#### 示例

```json
{
  "case_id": "case_release_001",
  "task_id": "FEISHU-231",
  "domain": "enterprise_product_launch",
  "company_type": "B2B SaaS",
  "main_goal": "确定一个功能上线前的对外发布口径",
  "difficulty": "medium",
  "seed": 20260504,
  "complexity_profile": {
    "session_count": 3,
    "source_types": ["chat", "thread", "comment"],
    "topic_count": 4,
    "must_include_supersession": true,
    "must_include_cross_source_revision": true,
    "event_family_target": 6
  }
}
```

#### 需要实现

```text
builder_v2/seed/
  seed_schema.py
  seed_generator.py
  seed_loader.py
```

#### 支持模式

```text
manual seed:
  用户手写 case_seed.json

batch seed:
  程序批量生成 N 个 case_seed
```

#### 验收标准

```text
- 同一个 seed 可复现同一个 case
- 不同 seed 能生成不同 case
- 支持 --num-cases
- 支持 --seed
- dataset_manifest.json 能记录全部 case
- 不再只能生成一个固定 case
```

---

### 4.2 `case_world.json`

#### 作用

`case_world.json` 定义 case 的复杂世界。

它回答的问题是：

```text
这个 case 为什么复杂，复杂在哪里？
```

它应该包含：

```text
组织背景
角色阵营
冲突轴
外部压力
隐藏约束
可能反转点
成功标准
```

#### 示例

```json
{
  "task_id": "FEISHU-231",
  "task_title": "审批配置能力上线前发布口径确认",
  "business_context": "客户正在等待审批配置能力上线，销售希望尽快给出明确日期。",
  "organizational_context": "产品、研发、QA、销售、客户成功、法务共同参与。",
  "external_pressure": [
    "P0 客户希望在 5 月初前拿到承诺",
    "销售团队希望把 5 月 5 日写入客户沟通邮件"
  ],
  "conflict_axes": [
    "内部目标日期 vs 对外承诺日期",
    "销售推进速度 vs 研发交付风险",
    "客户定制需求 vs MVP 范围控制"
  ],
  "hidden_constraints": [
    "迁移窗口尚未锁定",
    "QA 回归还剩两个高风险场景",
    "法务不允许对外承诺确定上线日"
  ],
  "likely_reversal_points": [
    "5 月 5 日从候选日期变成不可对外承诺日期",
    "本期范围从完整审批配置收缩为模板化配置"
  ],
  "success_criteria": [
    "形成当前对外口径",
    "明确哪些旧口径已经失效",
    "明确后续行动项 owner"
  ]
}
```

#### 生成方式

```text
LLM 负责：
- 生成业务背景
- 生成冲突轴
- 生成隐藏约束
- 生成反转点

规则负责：
- 检查字段完整
- 检查是否有冲突轴
- 检查是否有可触发 current state 修改的反转点
- 检查是否能支撑后续 event 类型
```

#### 验收标准

```text
- 每个 case_world 至少有 2 个 conflict_axes
- 至少 2 个 hidden_constraints
- 至少 1 个 likely_reversal_point
- success_criteria 能映射到 eval_questions
```

---

### 4.3 `characters.json`

#### 作用

V1 的角色更像 roster。

V2 的角色需要真正影响对话走向。

每个角色应该包含：

```text
person_id
name
department
role
responsibility
stance
risk_preference
communication_style
conflict_bias
information_access_level
default_channels
```

#### 示例

```json
{
  "person_id": "p_pm_001",
  "name": "陈岚",
  "department": "Product",
  "role": "PM",
  "responsibility": "推动功能按期上线，并协调对外口径",
  "stance": "倾向尽快给出内部目标日期，但不希望对外说死",
  "risk_preference": "medium",
  "communication_style": "直接、偏协调",
  "conflict_bias": "会在销售压力和研发风险之间折中",
  "information_access_level": "knows_business_pressure",
  "default_channels": ["main_chat", "release_thread"]
}
```

#### 角色类型必须覆盖

```text
driver
blocker
constraint_owner
resolver
executor
external_pressure_proxy
```

#### 验收标准

```text
- character_count >= 6
- 至少包含 driver / blocker / constraint_owner / resolver
- 至少一个角色知道 hidden constraint
- 至少一个角色只代表外部压力
- 至少一个角色负责最终裁决 current state
```

---

### 4.4 `conversation_plan.json`

#### 作用

`conversation_plan.json` 是 V2 最重要的新增对象。

它不直接是消息，而是多轮讨论计划。

它需要定义：

```text
哪些 session
哪些 topic
哪些 source
哪些状态变化
哪些事件类型
哪些消息承担证据作用
```

#### 示例

```json
{
  "sessions": [
    {
      "session_id": "s1_main_chat",
      "source_type": "chat",
      "purpose": "暴露上线日期和销售承诺风险",
      "topics": ["release_date", "sales_commitment_risk"],
      "turn_count": 8
    },
    {
      "session_id": "s2_release_thread",
      "source_type": "thread",
      "purpose": "展开迁移窗口和 QA 风险",
      "topics": ["migration_window", "qa_status", "release_date"],
      "turn_count": 7
    },
    {
      "session_id": "s3_followup_comment",
      "source_type": "comment",
      "purpose": "形成最终对外口径并确认行动项",
      "topics": ["external_policy", "doc_commitment"],
      "turn_count": 6
    }
  ],
  "topic_state_transitions": [
    {
      "topic_key": "release_date",
      "from": "5 月 5 日是内部目标日期",
      "to": "5 月 5 日不能对外承诺，只能说预计 5 月上旬",
      "transition_type": "supersession",
      "source_order": ["thread", "main_chat"]
    }
  ],
  "required_event_coverage": [
    "conclusion_event",
    "objection_event",
    "constraint_event",
    "status_event",
    "time_event",
    "commitment_event"
  ],
  "source_layout": {
    "main_chat": ["主口径", "跨 topic 协调", "后续修正"],
    "thread": ["具体 blocker", "风险展开"],
    "comment": ["正式确认", "行动项"]
  }
}
```

#### 生成方式

```text
LLM 负责：
- 生成 conversation_plan 草稿

规则负责：
- 检查 session_count
- 检查 source_session_count
- 检查 topic_count
- 检查 event coverage
- 检查 state_transition_count
- 检查是否包含 supersession / cross_source_revision
```

#### 验收标准

```text
- session_count >= 3
- source_session_count >= 3
- topic_count >= 3
- state_transition_count >= 4
- supersession_count >= 1
- cross_source_revision_count >= 1
- thread_reply_depth >= 3
- event_family_coverage >= 5
```

---

### 4.5 `utterance_plan.jsonl`

#### 作用

`utterance_plan.jsonl` 用于把 conversation plan 拆成可控 turn。

每条 turn 都要显式标注：

```text
turn_id
session_id
speaker_id
source_type
topic_key
turn_purpose
supports_event_types
must_include_facts
references_previous_turns
should_be_gold_evidence
```

#### 示例

```json
{
  "turn_id": "t_012",
  "session_id": "s2_release_thread",
  "speaker_id": "p_eng_001",
  "source_type": "thread",
  "topic_key": "migration_window",
  "turn_purpose": "state_update",
  "supports_event_types": ["status_event"],
  "must_include_facts": ["迁移窗口尚未锁定"],
  "references_previous_turns": ["t_004"],
  "should_be_gold_evidence": true
}
```

---

### 4.6 `realized_messages.jsonl`

#### 作用

`realized_messages.jsonl` 是最终自然语言消息。

它由 `utterance_plan.jsonl` 生成，但仍保留结构化追踪信息。

#### 示例

```json
{
  "message_id": "msg_012",
  "turn_id": "t_012",
  "session_id": "s2_release_thread",
  "speaker_id": "p_eng_001",
  "source_type": "thread",
  "topic_key": "migration_window",
  "content_text": "迁移窗口现在还没锁定，所以 5 月 5 日只能先作为内部目标，不能直接对外承诺。",
  "created_at": "2026-05-04T10:24:00+08:00"
}
```

#### 生成方式

```text
LLM 负责：
- 把 utterance_plan 改写成自然语言消息

规则负责：
- 检查 must_include_facts 是否出现
- 检查 evidence_quote 是否能命中原文
- 检查 message_id / turn_id / topic_key 是否完整
- 检查时序是否稳定
```

#### 验收标准

```text
- 每条 should_be_gold_evidence=true 的消息都能生成 expected_event
- evidence_quote 必须是 content_text 子串
- 不允许 gold 只存在于隐含语气
- 不允许关键事实只靠上下文推断
```

---

## 5. OpenClaw 输入链路

### 5.1 继续使用当前执行链

当前 execute / collect / adapt 规则链路已经是 V2 运行时的一部分，不建议全部重写。

推荐保留：

```text
execute:
  确定性把计划写入飞书

collect:
  拉取真实飞书消息

adapt:
  转成 OpenClaw ingress
```

V2 需要新增的是：

```text
realized_messages → execution_plan
```

而不是替换 execute / collect / adapt。

---

### 5.2 `openclaw_message_ingress.jsonl`

这是系统测试的真实输入。

它应该由 Builder / Adapter 生成，并直接喂给 OpenClaw。

作用：

```text
让 OpenClaw 原始处理方式和 Task Wiki 方式使用完全相同的输入。
```

注意：

```text
这个文件不是 gold。
它是待评测系统共同消费的输入。
```

---

## 6. Gold 与评测数据设计

### 6.1 需要新增的 gold 文件

```text
gold/
  expected_events.jsonl
  expected_memory_blocks.json
  expected_current_state.json

eval/
  eval_questions.json
```

---

### 6.2 `expected_events.jsonl`

#### 作用

用于评估 Layer 2：Event Extraction。

它定义：

```text
从输入消息中应该抽取出哪些 verified session_event。
```

#### 示例

```json
{
  "event_id": "gold_evt_001",
  "event_type": "time_event",
  "claim": "5 月 5 日只是内部目标日期",
  "evidence_message_id": "msg_012",
  "evidence_quote": "5 月 5 日只能先作为内部目标",
  "certainty": "tentative"
}
```

#### 用于评估

```text
- 是否抽到了关键事实
- claim 是否被 quote 支撑
- event type 是否正确
- 是否保持了原文强度
- 是否出现 unsupported inference
```

#### 推荐指标

```text
event_precision
event_recall
event_f1
event_type_accuracy
claim_support_rate
atomicity_pass_rate
unsupported_claim_rate
```

---

### 6.3 `expected_memory_blocks.json`

#### 作用

用于评估 Layer 3：Memory Block 组织能力。

它定义：

```text
哪些 event 应该被组织到哪些 Memory Block 里，
并进入哪些 KI slot。
```

#### 示例

```json
{
  "block_id": "release_date_policy",
  "topic_key": "release_date",
  "expected_slots": {
    "time": ["5 月 5 日只是内部目标日期"],
    "constraint": ["不能直接对外承诺 5 月 5 日"],
    "conclusion": ["对外只能说预计 5 月上旬"]
  },
  "evidence_event_ids": ["gold_evt_001", "gold_evt_002", "gold_evt_003"]
}
```

#### 推荐指标

```text
block_grouping_accuracy
slot_accuracy
memory_block_recall
wrong_slot_rate
orphan_event_rate
```

---

### 6.4 `expected_current_state.json`

#### 作用

这是最关键的 gold。

它定义：

```text
每个 topic 最终的当前状态是什么。
哪些 claim 是 active。
哪些 claim 已经 superseded。
哪些 claim 不能被展示为当前结论。
```

#### 示例

```json
{
  "topic_key": "release_date",
  "current_state": "不能对外承诺 5 月 5 日；对外只能说预计 5 月上旬",
  "active_claims": [
    "不能对外承诺 5 月 5 日",
    "对外只能说预计 5 月上旬"
  ],
  "superseded_claims": [
    "5 月 5 日是确定上线日期"
  ],
  "must_not_show_as_current": [
    "可以直接承诺客户 5 月 5 日"
  ],
  "supporting_event_ids": ["gold_evt_002", "gold_evt_003"],
  "superseded_event_ids": ["gold_evt_001"]
}
```

#### 为什么不需要 `gold_supersession_graph.json`

不需要单独做这个文件。

原因：

```text
session_event 本身只是可验证事实，
不表示 Wiki 更新操作，
也不直接表示“删除旧结论”或“修改当前状态”。
```

Supersession 是 Wiki / current-state 层的结果。

所以应该放在：

```text
expected_current_state.json
```

或 Memory Block 的状态字段里。

#### 推荐指标

```text
current_state_accuracy
stale_claim_error_rate
supersession_accuracy
invalidated_claim_error_rate
must_not_show_violation_rate
```

---

### 6.5 `eval_questions.json`

#### 作用

用于评估用户价值。

它模拟真实用户会问的问题。

#### 示例

```json
{
  "question_id": "q_release_001",
  "question": "5 月 5 日现在能不能对外承诺？",
  "expected_answer_points": [
    "不能对外承诺 5 月 5 日",
    "5 月 5 日只是内部目标",
    "对外口径是预计 5 月上旬"
  ],
  "forbidden_answer_points": [
    "5 月 5 日已确认上线",
    "可以直接承诺客户 5 月 5 日"
  ],
  "required_topics": [
    "release_date_policy",
    "sales_commitment_risk"
  ]
}
```

#### 推荐指标

```text
qa_accuracy
answer_point_recall
forbidden_claim_violation_rate
citation_accuracy
first_turn_success_rate
manual_correction_needed
```

---

### 6.6 Gold 生成方式

推荐三步：

```text
1. 自动 draft
   根据 utterance_plan 生成 expected_events / memory_blocks / current_state 草稿。

2. 程序校验
   evidence_quote 是否是消息子串。
   event_id 是否存在。
   block 引用是否闭合。
   current_state 是否有 supporting_event_ids。

3. 人工 review
   第一批 5-10 个黄金 case 必须人工过一遍。
```

---

## 7. Dataset Validation：验证 case 是否合格

Dataset Validation 是单元测试层。

它不比较 OpenClaw 原始方式和 Task Wiki 方式。

它只回答：

```text
这个 case 是否合格？
它能不能作为评测样本？
```

### 7.1 新增模块

```text
builder_v2/validation/
  schema_validator.py
  complexity_validator.py
  gold_consistency_validator.py
  ingress_validator.py
  dataset_validation_runner.py
```

### 7.2 Schema Tests

```text
- case_seed schema valid
- case_world schema valid
- characters schema valid
- conversation_plan schema valid
- utterance_plan schema valid
- realized_messages schema valid
- openclaw ingress schema valid
```

### 7.3 Complexity Tests

```text
- session_count >= 3
- source_session_count >= 3
- message_count >= 18
- topic_count >= 3
- event_family_coverage >= 5
- state_transition_count >= 4
- supersession_count >= 1
- cross_source_revision_count >= 1
- thread_reply_depth >= 3
```

### 7.4 Gold Consistency Tests

```text
- 每个 expected_event 都有 evidence_message_id
- evidence_quote 是 content_text 子串
- expected_memory_blocks 引用的 event_id 都存在
- expected_current_state 的 active / superseded claim 都能追溯到 event
- eval_questions 的 required_topics 都能命中 memory block
```

### 7.5 Ingress Tests

```text
- openclaw_message_ingress.jsonl 可被 OpenClaw 消费
- message 顺序稳定
- thread_id / root_id / chat_id 完整
```

### 7.6 输出

```text
checks/
  complexity_report.json
  dataset_validation_report.json
```

---

## 8. Component Scoring：逐层测试 Task Wiki pipeline

Component Scoring 是组件测试层。

它验证：

```text
Task Wiki pipeline 每一层是否正确。
```

---

### 8.1 Layer 1：Task Binding

```text
输入：
openclaw_message_ingress.jsonl

输出：
message_id → task_id

对比：
gold task_id
```

指标：

```text
binding_precision
binding_recall
binding_f1
```

---

### 8.2 Layer 2：Event Extraction

```text
输入：
source session

输出：
session_events.jsonl

对比：
expected_events.jsonl
```

指标：

```text
event_precision
event_recall
event_f1
event_type_accuracy
claim_support_rate
atomicity_pass_rate
unsupported_claim_rate
```

---

### 8.3 Layer 3：Memory Block

```text
输入：
session_events.jsonl

输出：
session_wiki.md / memory_blocks

对比：
expected_memory_blocks.json
```

指标：

```text
block_grouping_accuracy
slot_accuracy
memory_block_recall
orphan_event_rate
wrong_slot_rate
```

---

### 8.4 Layer 4：Current State

```text
输入：
多个 source session / 多轮 ingest

输出：
task_wiki.md / current_state

对比：
expected_current_state.json
```

指标：

```text
current_state_accuracy
stale_claim_error_rate
supersession_accuracy
must_not_show_violation_rate
```

---

## 9. System Evaluation：比较 OpenClaw 原始方式 vs Task Wiki 方式

System Evaluation 是最终系统测试层。

它比较：

```text
OpenClaw 原始处理方式
vs
Task Wiki 方式
```

### 9.1 输入相同

```text
data/openclaw_message_ingress.jsonl
```

---

### 9.2 Run A：Baseline

```text
OpenClaw 原始处理方式
→ baseline_output/
```

需要保存：

```text
baseline_output/
  extracted_facts.jsonl 或 equivalent output
  summaries.md 或 current output
  qa_answers.json
```

具体格式可以后面适配，但必须能转成统一 scoring schema。

---

### 9.3 Run B：Task Wiki

```text
Task Wiki pipeline
→ task_memory_output/
```

保存：

```text
task_memory_output/
  sessions/*/session_events.jsonl
  sessions/*/session_wiki.md
  index.md
  task_wiki.md
  qa_answers.json
```

---

### 9.4 Scoring

对比 gold：

```text
expected_events.jsonl
expected_memory_blocks.json
expected_current_state.json
eval_questions.json
```

输出报告示例：

```json
{
  "case_id": "case_release_001",
  "baseline": {
    "event_recall": 0.62,
    "current_state_accuracy": 0.50,
    "stale_claim_errors": 3,
    "qa_accuracy": 0.58,
    "citation_accuracy": 0.41
  },
  "task_wiki": {
    "event_recall": 0.81,
    "current_state_accuracy": 0.90,
    "stale_claim_errors": 0,
    "qa_accuracy": 0.86,
    "citation_accuracy": 0.82
  }
}
```

---

## 10. 推荐工程目录

```text
amem_docs/
  builder_v2/
    seed/
      seed_schema.py
      seed_generator.py
      seed_loader.py

    world/
      world_generator.py
      world_schema.py
      world_validator.py

    characters/
      character_generator.py
      character_schema.py
      character_validator.py

    planning/
      conversation_plan_generator.py
      conversation_plan_schema.py
      conversation_plan_validator.py

    realization/
      utterance_plan_generator.py
      message_realizer.py
      message_validator.py

    gold/
      expected_event_generator.py
      expected_memory_block_generator.py
      expected_current_state_generator.py
      eval_question_generator.py
      gold_validator.py

    validation/
      schema_validator.py
      complexity_validator.py
      gold_consistency_validator.py
      ingress_validator.py
      dataset_validation_runner.py

    scoring/
      event_scorer.py
      memory_block_scorer.py
      current_state_scorer.py
      qa_scorer.py
      system_eval_runner.py

    cli.py
```

---

## 11. 推荐 CLI / Script Phase

可以保留 V1 的脚本风格，但新增 V2 phase：

```bash
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase generate-seeds
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase compile-v2
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase validate-dataset
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase execute
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase collect
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase adapt
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase score
```

推荐阶段定义：

```text
generate-seeds:
  批量生成 case_seed.json。

compile-v2:
  case_seed → case_world → characters → conversation_plan → utterance_plan → realized_messages → execution_plan。

validate-dataset:
  执行 schema / complexity / gold consistency / ingress validation。

execute:
  使用当前执行逻辑，把 execution_plan 写入飞书。

collect:
  使用当前收集逻辑，从飞书拉取真实消息。

adapt:
  使用当前适配逻辑，生成 openclaw_message_ingress.jsonl。

score:
  执行 component scoring 和 system evaluation。
```

---

## 12. 推荐分阶段实施计划

### Phase 1：解决“只能一个 case”的问题

目标：

```text
能批量生成 case_seed。
```

任务：

```text
- 新增 case_seed.json schema
- 新增 seed_generator
- 新增 dataset_manifest v2
- 支持 --num-cases
- 支持 --seed
```

验收：

```text
运行一次生成 5 个 case_seed。
每个 case_id / task_id 不同。
difficulty / domain / complexity_profile 可控。
```

---

### Phase 2：实现 `case_world + characters`

目标：

```text
每个 seed 能生成不同 case_world 和角色组。
```

任务：

```text
- world_generator
- character_generator
- world_validator
- character_validator
```

验收：

```text
每个 case 有明确 conflict_axes / hidden_constraints / reversal_points。
每个 case 至少 6 个角色。
角色有立场差异和信息不对称。
```

---

### Phase 3：实现 `conversation_plan`

目标：

```text
先规划多轮、多 source、状态演化，再生成消息。
```

任务：

```text
- conversation_plan_generator
- conversation_plan_validator
- source_layout planner
- topic_state_transition planner
```

验收：

```text
session_count >= 3
topic_count >= 3
supersession_count >= 1
cross_source_revision_count >= 1
event_family_coverage >= 5
```

---

### Phase 4：实现 `utterance_plan + realized_messages`

目标：

```text
把计划变成自然语言消息，同时保持可追溯。
```

任务：

```text
- utterance_plan_generator
- message_realizer
- evidence_quote_checker
- realized_messages.jsonl writer
```

验收：

```text
每个 gold candidate 都能回到 message_id。
evidence_quote 是原文子串。
消息顺序稳定。
thread/root/chat 关系可构造。
```

---

### Phase 5：继续演进 execution_plan

目标：

```text
把 realized_messages 转成当前可执行的 execution_plan。
```

任务：

```text
- realized_messages_to_execution_plan
- chat/thread/comment action builder
- stable resource refs
- dry-run support
```

验收：

```text
可以跑 --phase full --dry-run。
可以生成 openclaw_message_ingress.jsonl。
不破坏当前 execute / collect / adapt。
```

---

### Phase 6：实现 gold 生成

目标：

```text
每个 case 都有 expected_events / memory_blocks / current_state / questions。
```

任务：

```text
- expected_event_generator
- expected_memory_block_generator
- expected_current_state_generator
- eval_question_generator
- gold_validator
```

验收：

```text
expected_events 都有 evidence_quote。
expected_memory_blocks 引用 event_id 闭合。
expected_current_state 能表达 active / superseded。
eval_questions 能映射到 memory block。
```

---

### Phase 7：实现 Dataset Validation

目标：

```text
自动判断 case 是否合格。
```

任务：

```text
- complexity_report
- dataset_validation_report
- pytest suite
```

验收：

```text
不合格 case 自动 fail。
报告能说明 fail 在哪里。
支持批量统计通过率。
```

---

### Phase 8：实现 Component Scoring

目标：

```text
逐层测试 Task Wiki pipeline。
```

任务：

```text
- event_scorer
- memory_block_scorer
- current_state_scorer
```

验收：

```text
能对单 case 输出 layer-by-layer score。
能指出 missing event / wrong slot / stale claim。
```

---

### Phase 9：实现 System Evaluation

目标：

```text
比较 OpenClaw 原始处理方式 vs Task Wiki 方式。
```

任务：

```text
- baseline output adapter
- task_wiki output adapter
- unified scorer
- system_eval_report.json
```

验收：

```text
同一 ingress 可跑两套系统。
能输出 baseline vs task_wiki 指标对比。
能定位 Task Wiki 优势主要来自哪里。
```

---

## 13. 第一版 MVP 范围

不要一开始做很大。

第一版只做：

```text
5 个黄金 case

每个 case:
  3 个 source session
  20-30 条消息
  3-4 个 topic
  至少 1 个 current state 修正
  至少 1 个 source 间口径不一致
  至少 5 类 event
  3-5 个 eval questions
```

第一版不做：

```text
完整 τ²-bench user simulator
复杂 pass^k
真实文档 / 多维表格 / 审批
大规模自动标注
```

第一版必须做：

```text
case 多样化
gold expected state
dataset validation
component scoring
system scoring
```

---

## 14. 最小 case 示例

以 `FEISHU-231 发布口径` 为例。

### Source 1：主群 chat

```text
PM 说内部先按 5 月 5 日推进。
销售问能不能对客户说。
风险同学提醒不能说死。
```

### Source 2：thread

```text
研发说迁移窗口还没锁定。
QA 说回归还差两个场景。
PM 说 5 月 5 日只是内部目标。
```

### Source 3：后续主群 / comment

```text
负责人最终裁决：对外只说预计 5 月上旬。
不允许销售承诺 5 月 5 日。
李四负责补接口文档，周五前完成。
```

这个 case 可以验证：

```text
task binding
time_event
objection_event
constraint_event
commitment_event
current state
supersession
source conflict
QA retrieval
```

对应用户问题：

```text
1. 5 月 5 日能不能对外承诺？
2. 当前对外口径是什么？
3. 谁负责补接口文档？
4. 销售承诺风险后来有没有解决？
5. 迁移窗口是否已经锁定？
```

---

## 15. 最终判断

V2 的核心不是把 V1 多套几次，也不是给固定 case 补几个测试。

完整 V2 应该是：

```text
生成器改造：
从固定 case_spec
升级为 case_seed + case_world + conversation_plan + messages。

测试体系改造：
从“能不能跑”
升级为 dataset validation + component scoring + system evaluation。

比较方式改造：
从单系统自测
升级为 OpenClaw 原始方式 vs Task Wiki 方式。
```

最终要同时解决两个问题：

```text
1. V1 永远只能生成一个固定 case。
2. 数据集无法证明 Task Wiki 的实际价值。
```

最重要的一点是：

```text
LLM 不应该替代规则。
LLM 负责生成多样性。
规则负责约束、校验、可复现、可评测。
```
