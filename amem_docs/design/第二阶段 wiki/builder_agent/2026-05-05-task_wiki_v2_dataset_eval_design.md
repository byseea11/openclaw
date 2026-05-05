# Task Wiki V2 数据集与评测设计说明

## 0. 背景与目标

当前目标不是简单做一个“长对话数据集”，也不是复刻 `τ²-bench`。

当前代码现实先说明一下：

- `feishu_builder_agent` 已经按纯 V2 口径运行
- 默认输出根目录已经是 `amem_docs/ds/feishu_im_dataset_v2`
- 当前主产物已经是 `case_world / conversation_plan / realized_messages / gold / checks`
- 下面文中如果提到 V1，统一只表示历史背景，不再表示当前默认实现

当前真正要做的是：

```text
1. 生成一批能跑 OpenClaw 的飞书协作数据
2. 验证这些数据本身是否合格
3. 用这些数据比较：
   - OpenClaw 原始处理方式
   - Task Wiki / Event + Memory Block + Current State 方式
```

因此，V2 数据集应该同时服务两个目的：

```text
数据生产：
生成真实 / 半真实的飞书协作输入，能够进入 OpenClaw ingress 链路。

系统评测：
验证 Task Wiki 方法是否比 OpenClaw 原始处理方式更能维护正确、可追溯、当前有效的项目记忆。
```

比较对象不是 Raw RAG，而是：

```text
Baseline:
OpenClaw 原始处理方式

Your Method:
OpenClaw + Task Wiki / session_event / Memory Block / current state
```

---

## 1. 总体结论

V2 数据集不应该被设计成一个单纯的聊天数据集，而应该被设计成：

```text
OpenClaw ingress 数据
+
gold expected state
+
scoring scripts
```

也就是说，每个 case 至少要包含：

```text
1. 输入数据
2. 预期事件
3. 预期 Memory Block
4. 预期当前状态
5. 评测问题
6. 数据复杂度报告
```

最终要回答的问题是：

```text
同样一批飞书协作数据下，
Task Wiki 方式是否比 OpenClaw 原始处理方式更能得到正确、可追溯、当前有效的项目记忆？
```

---

## 2. 数据集需要验证什么？

这里的“验证”分成两类，不能混在一起。

---

### 2.1 Dataset Validation：验证数据集本身合不合格

这一步验证的是：

```text
这个 case 有没有资格作为评测样本？
```

它不验证方法好坏，只验证数据是否满足 V2 复杂度要求。

需要检查：

```text
- 是否有足够多的 session
- 是否有多个 source
- 是否有多 topic
- 是否有状态演化
- 是否有旧结论被新结论覆盖
- 是否有 source 间口径不一致
- 是否有足够事件类型覆盖
- 是否每个 gold event 都有 evidence quote
- 是否能生成合法的 openclaw_message_ingress.jsonl
```

这部分适合做单元测试 / 静态校验。

---

### 2.2 System Evaluation：验证系统是否更好

这一步验证的是：

```text
同一批输入下，
OpenClaw 原始处理方式和 Task Wiki 方式谁更好？
```

比较维度包括：

```text
- event 抽取是否正确
- Memory Block 组织是否正确
- current state 是否正确
- 是否把旧结论错误地当成当前结论
- 用户问题是否回答正确
- 引用是否能回到 evidence
- 是否减少重复检索和人工纠错
```

---

## 3. τ-bench / τ²-bench 应该怎么参考？

当前阶段不建议直接做完整的 `τ²-bench`。

`τ-bench / τ²-bench` 可以参考的是评测思想，而不是框架本身。

---

### 3.1 应该参考的思想

#### 1. Final State Evaluation

不要只看模型输出文本像不像，而要看最终系统状态是否正确。

对应到 Task Wiki，就是检查：

```text
task_wiki.md
index.md
session_wiki.md
session_events.jsonl
Memory Blocks
current state
```

是否和 gold state 对齐。

---

#### 2. Repeated Reliability

同一个类型的 case 可以多跑几次，检查结果是否稳定。

例如：

```text
同一类“发布日期被修正”的 case，
换不同表达、不同消息顺序、不同角色名后，
系统是否仍然能识别正确 current state。
```

---

### 3.2 当前不需要做的部分

当前阶段不需要：

```text
- 完整 user simulator
- agent/user 双控工具环境
- Dec-POMDP 式动态环境
- 复杂 pass^k benchmark
```

这些可以等后续系统进入“持续互动、撤回、遗忘、用户主动修改环境”的阶段再考虑。

---

### 3.3 什么时候再考虑 τ²-bench-like？

当系统需要模拟下面这种动态流程时，可以再考虑：

```text
用户继续发消息
→ 系统更新 Wiki
→ 用户撤回 / 修改文档
→ 系统处理 forgetting
→ 用户再提问
→ 检查系统是否仍能维护正确状态
```

也就是说，`τ²-bench-like` 更适合后续评测：

```text
持续更新
撤回
遗忘
invalidation
多轮用户协作
```

当前 V2 阶段先不做。

---

## 4. 推荐的 case 目录结构

每个 case 可以设计成三层：

```text
case input 层：用于生成数据
case gold 层：用于判断正确答案
case eval 层：用于比较 baseline 和你的方法
```

推荐目录：

```text
cases/FEISHU-231/
  input/
    case_seed.json
    case_world.json
    characters.json
    conversation_plan.json

  data/
    realized_messages.jsonl
    openclaw_message_ingress.jsonl

  gold/
    expected_events.jsonl
    expected_memory_blocks.json
    expected_current_state.json
    expected_answers.json

  checks/
    conversation_complexity_report.json
    dataset_validation_report.json

  eval/
    eval_questions.json
    scoring_config.json
```

如果想做最小版本，可以先保留：

```text
cases/FEISHU-231/
  input/
    case_world.json
    conversation_plan.json

  data/
    openclaw_message_ingress.jsonl

  gold/
    expected_events.jsonl
    expected_memory_blocks.json
    expected_current_state.json

  eval/
    eval_questions.json

  checks/
    complexity_report.json
```

---

## 5. 核心文件说明

---

### 5.1 `openclaw_message_ingress.jsonl`

这是系统测试的真实输入。

它应该由 Builder / Adapter 生成，直接喂给 OpenClaw。

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

### 5.2 `expected_events.jsonl`

这是 Layer 2 的 gold。

它定义：

```text
从输入消息中应该抽取出哪些 verified session_event。
```

示例：

```json
{
  "event_id": "gold_evt_001",
  "event_type": "time_event",
  "claim": "内部暂按 5 月 5 日作为目标发布时间推进",
  "evidence_message_id": "msg_012",
  "evidence_quote": "我们内部先按 5 月 5 日推进",
  "certainty": "tentative"
}
```

它用于评估：

```text
- 是否抽到了关键事实
- claim 是否被 quote 支撑
- event type 是否正确
- 是否保持了原文强度
- 是否出现 unsupported inference
```

推荐指标：

```text
event_precision
event_recall
event_f1
claim_support_rate
atomicity_pass_rate
event_type_accuracy
```

---

### 5.3 `expected_memory_blocks.json`

这是 Layer 3 的 gold。

它定义：

```text
哪些 event 应该被组织到哪些 Memory Block 里，
并进入哪些 KI slot。
```

示例：

```json
{
  "block_id": "release_date_policy",
  "topic_key": "release_date",
  "expected_slots": {
    "conclusion": ["内部暂按 5 月 5 日推进"],
    "constraint": ["不能对外承诺 5 月 5 日"],
    "objection": ["销售可能会把 5 月 5 日说成客户承诺"],
    "time": ["对外口径为 5 月上旬"]
  },
  "evidence_event_ids": ["gold_evt_001", "gold_evt_004", "gold_evt_007"]
}
```

它用于评估：

```text
- event 是否被分到正确 block
- event 是否进入正确 slot
- block summary 是否表达正确
- block status 是否正确
```

推荐指标：

```text
block_grouping_accuracy
slot_accuracy
memory_block_recall
orphan_event_rate
wrong_slot_rate
```

---

### 5.4 `expected_current_state.json`

这是最关键的 gold。

它定义：

```text
每个 topic 最终的当前状态是什么。
哪些 claim 是 active。
哪些 claim 已经 superseded。
哪些 claim 不能被展示为当前结论。
```

示例：

```json
{
  "topic_key": "release_date",
  "current_state": "不能对外承诺 5 月 5 日；对外只能说预计 5 月上旬",
  "active_claims": ["不能对外承诺 5 月 5 日", "对外口径为预计 5 月上旬"],
  "superseded_claims": ["5 月 5 日是确定上线日期"],
  "must_not_show_as_current": ["5 月 5 日已确认上线", "可以对客户承诺 5 月 5 日"],
  "supporting_event_ids": ["gold_evt_004", "gold_evt_007"],
  "superseded_event_ids": ["gold_evt_002"]
}
```

注意：

```text
不需要单独做 gold_supersession_graph.json。
supersession 可以放在 expected_current_state.json 里。
```

它用于评估：

```text
- 当前状态是否正确
- 是否识别旧结论已经失效
- 是否把新事实作为当前状态
- 是否保留历史但不把历史误当当前
```

推荐指标：

```text
current_state_accuracy
stale_claim_error_rate
supersession_accuracy
invalidated_claim_error_rate
```

---

### 5.5 `eval_questions.json`

这是用户价值评测，不是系统内部 gold。

它模拟真实用户会问的问题。

示例：

```json
{
  "question_id": "q_release_001",
  "question": "5 月 5 日现在能不能对外承诺？",
  "expected_answer_points": [
    "不能对外承诺 5 月 5 日",
    "5 月 5 日只是内部暂定目标",
    "对外口径是预计 5 月上旬"
  ],
  "forbidden_answer_points": ["5 月 5 日已确认上线", "可以直接承诺客户 5 月 5 日"],
  "required_topics": ["release_date_policy", "sales_commitment_risk"],
  "required_evidence_event_ids": ["gold_evt_004", "gold_evt_007"]
}
```

它用于评估：

```text
用户提问时，
OpenClaw 原始处理方式和 Task Wiki 方式，
谁回答得更准、更当前、更可追溯。
```

推荐指标：

```text
qa_accuracy
answer_point_recall
forbidden_claim_violation_rate
citation_accuracy
first_turn_success_rate
manual_correction_needed
```

---

### 5.6 `complexity_report.json`

这是数据集自身质量报告。

示例：

```json
{
  "session_count": 3,
  "source_session_count": 3,
  "message_count": 24,
  "topic_count": 4,
  "event_family_coverage": 6,
  "state_transition_count": 5,
  "supersession_count": 1,
  "cross_source_revision_count": 1,
  "thread_reply_depth": 4,
  "passes_v2_bar": true
}
```

它用于判断：

```text
这个 case 是否足够复杂，
能不能用来证明 Task Wiki 的优势。
```

---

## 6. 为什么不需要 `gold_supersession_graph.json`？

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

推荐表达方式：

```json
{
  "topic_key": "release_date",
  "current_value": "对外口径为预计 5 月上旬，不能承诺 5 月 5 日",
  "active_event_ids": ["gold_evt_008", "gold_evt_011"],
  "superseded_event_ids": ["gold_evt_003"],
  "reason": "后续主群消息修正了 thread 中的 5 月 5 日说法"
}
```

这样更轻，也更符合系统架构。

---

## 7. 单元测试、组件测试、系统测试怎么分？

---

### 7.1 单元测试：验证 Builder 和数据质量

单元测试不比较方法好坏。

它只回答：

```text
这条 case 生成得对不对？
它能不能作为评测样本？
```

建议测试：

```text
Dataset schema tests
- case_seed schema valid
- case_world schema valid
- conversation_plan schema valid
- openclaw ingress schema valid

Complexity tests
- session_count >= 3
- source_session_count >= 3
- topic_count >= 3
- event_family_coverage >= 5
- state_transition_count >= 4
- supersession_count >= 1

Gold consistency tests
- 每个 expected_event 都有 evidence_message_id
- evidence_quote 是原消息子串
- 每个 expected_memory_block 引用的 event_id 都存在
- expected_current_state 的 active/superseded claim 都能追溯到 event
```

---

### 7.2 组件测试：验证每一层 pipeline

组件测试是：

```text
只跑系统的一层，然后和对应 gold 比。
```

例如：

```text
Layer 1 Task Binding Test
输入:
messages

输出:
task_id

比较:
expected task_id
```

```text
Layer 2 Event Extraction Test
输入:
source session

输出:
session_events

比较:
expected_events.jsonl
```

```text
Layer 3 Memory Block Test
输入:
session_events

输出:
memory_blocks

比较:
expected_memory_blocks.json
```

```text
Current State Test
输入:
多次 ingest / 多个 source session

输出:
task_wiki current state

比较:
expected_current_state.json
```

---

### 7.3 系统测试：比较 OpenClaw 原始方式 vs Task Wiki 方式

系统测试是 end-to-end。

流程：

```text
同一份 openclaw_message_ingress.jsonl

Run A:
  OpenClaw 原始处理方式
  → baseline_output/

Run B:
  Task Wiki 方式
  → task_memory_output/

Scoring:
  对比 expected_events.jsonl
  对比 expected_memory_blocks.json
  对比 expected_current_state.json
  对比 eval_questions.json
```

输出报告示例：

```json
{
  "case_id": "FEISHU-231",
  "baseline": {
    "event_recall": 0.62,
    "current_state_accuracy": 0.5,
    "stale_claim_errors": 3,
    "qa_accuracy": 0.58,
    "citation_accuracy": 0.41
  },
  "task_wiki": {
    "event_recall": 0.81,
    "current_state_accuracy": 0.9,
    "stale_claim_errors": 0,
    "qa_accuracy": 0.86,
    "citation_accuracy": 0.82
  }
}
```

---

## 8. 推荐系统评测指标

### 8.1 Event 层

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

### 8.2 Memory Block 层

```text
block_grouping_accuracy
slot_accuracy
memory_block_recall
wrong_slot_rate
orphan_event_rate
```

---

### 8.3 Current State 层

```text
current_state_accuracy
stale_claim_error_rate
supersession_accuracy
invalidated_claim_error_rate
must_not_show_violation_rate
```

---

### 8.4 QA / 用户价值层

```text
qa_accuracy
answer_point_recall
forbidden_claim_violation_rate
citation_accuracy
first_turn_success_rate
manual_correction_needed
```

---

### 8.5 效率层

如果后续能记录系统内部行为，可以加：

```text
source_reads
raw_message_reads
memory_block_reads
tokens_used
latency
turns_to_answer
```

这些不是第一版必须，但可以用来证明实际效率提升。

---

## 9. 一个最小 case 示例

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

## 10. 建议的第一阶段实施计划

不要一开始做大 benchmark。

建议先做 5 个黄金 case。

每个 case 满足：

```text
3 个 source session
20-30 条消息
3-4 个 topic
至少 1 个 current state 修正
至少 1 个 source 间口径不一致
至少 5 类 event
3-5 个 eval questions
```

每个 case 人工或半自动标注：

```text
expected_events.jsonl
expected_memory_blocks.json
expected_current_state.json
eval_questions.json
```

这 5 个 case 就能支撑第一版系统测试。

---

## 11. 推荐路线图

### Phase 1：定义数据对象

先固定这些对象：

```text
case_world.json
conversation_plan.json
realized_messages.jsonl
openclaw_message_ingress.jsonl
expected_events.jsonl
expected_memory_blocks.json
expected_current_state.json
eval_questions.json
complexity_report.json
```

---

### Phase 2：做 Dataset Validation

验证 case 是否合格：

```text
schema
复杂度
source 分布
event 覆盖
evidence 可追溯
current state 修正
```

---

### Phase 3：做 Component Scoring

分别评：

```text
task binding
event extraction
memory block grouping
current state update
```

---

### Phase 4：做 End-to-End System Scoring

比较：

```text
OpenClaw 原始处理方式
vs
Task Wiki 方式
```

指标：

```text
event precision / recall
memory block accuracy
current state accuracy
stale claim error
QA accuracy
citation accuracy
```

---

### Phase 5：以后再考虑 τ²-bench-like

当系统需要模拟持续互动、撤回、遗忘和用户主动修改环境时，再引入：

```text
user simulator
multi-turn update
forgetting scenario
pass^k / reliability evaluation
```

当前阶段先不要做。

---

## 12. 最简定义

当前 V2 数据集的最简定义：

```text
一个 OpenClaw ingress 数据集
+
一套 gold expected state
+
一套 scoring 脚本
```

单元测试验证：

```text
数据集 case 质量合格。
```

系统测试验证：

```text
同样的数据下，
Task Wiki 方式是否比 OpenClaw 原始处理方式
更能得到正确、可追溯、当前有效的项目记忆。
```

τ-bench / τ²-bench 只参考两个思想：

```text
1. 不只看文本输出，要看最终状态是否正确。
2. 不只看单次成功，要看同类 case 多次运行是否稳定。
```

# V2 Builder + 数据集验证 + 系统评测完整实现计划

## 0. 当前问题判断

当前代码已经是纯 V2 Builder，完整链路是：

```text
case_spec
  → case_seed
  → case_world
  → characters
  → conversation_plan
  → utterance_plan
  → realized_messages
  → gold
  → checks
  → execution_plan
  → execute
  → collect
  → adapt
```

当前问题已经不再是“怎么从 V1 升级到 V2”，而是：

```text
1. 怎么把 V2 继续推进到批量 case 生成
2. 怎么把 V2 接成完整 dataset validation + system evaluation
3. 怎么把复杂度设计进一步和 locomo 式长时程记忆压力校准
```

文中如果继续提到 V1，只表示历史背景：它说明为什么当初要引入 `case_world / conversation_plan / gold / checks` 这些 V2 对象。

所以 V2 要同时做两件事：

```text
1. 改 Builder：让它能生成多样 case
2. 改评测：让生成的数据可以测试 OpenClaw 原始方式 vs Task Wiki 方式
```

---

## 1. 总体目标

V2 最终要形成这个闭环：

```text
case_seed
  → case_world
  → characters
  → conversation_plan
  → realized_messages
  → openclaw_message_ingress
  → gold expected state
  → dataset validation
  → system evaluation
```

一句话：

```text
V2 Builder 不只是“生成消息”，而是生成一套可评测的项目记忆 case。
```

每个 case 最终应该包含：

```text
input/
  case_seed.json
  case_world.json
  characters.json
  conversation_plan.json

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

## 2. 核心改造一：以 `case_seed` 为最小输入

### 历史背景

V1 是：

```text
case_spec → story → characters → timeline → execution_plan
```

问题是 `case_spec` 太重，而且太确定。只要输入不变，后面基本不会变。

### V2 改法

改成：

```text
case_seed → case_world → characters → conversation_plan → messages
```

这也是你 V2 草案中建议的生成顺序：不要再让 `case_spec` 直接决定 story 和消息，而是先定义世界，再生成对话。

### 新增文件：`case_seed.json`

它只负责定义方向，不负责写死对话。

示例：

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

### 需要实现

新增模块：

```text
builder_v2/seed/
  seed_schema.py
  seed_generator.py
  seed_loader.py
```

支持两种模式：

```text
manual seed:
  用户手写 case_seed.json

batch seed:
  程序批量生成 N 个 case_seed
```

### 验收标准

```text
- 同一个 seed 可复现同一个 case
- 不同 seed 能生成不同 case
- dataset_manifest.json 能记录全部 case
- 不再只能生成一个固定 case
```

---

## 3. 核心改造二：新增 `case_world.json`

### 为什么需要

V1 的 story 太薄，通常只是背景文本。

V2 需要先定义一个“复杂世界”：

```text
组织背景
角色阵营
冲突轴
外部压力
隐藏约束
可能反转点
成功标准
```

这样后面的对话才不会只是模板填空。

你 V2 草案也把 `case_world` 定义成核心对象：它回答“这个 case 为什么复杂，复杂在哪里”。

### 新增文件：`case_world.json`

示例：

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
  "success_criteria": ["形成当前对外口径", "明确哪些旧口径已经失效", "明确后续行动项 owner"]
}
```

### 生成方式

这里可以用 LLM，但必须有程序校验。

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

### 验收标准

```text
- 每个 case_world 至少有 2 个 conflict_axes
- 至少 2 个 hidden_constraints
- 至少 1 个 likely_reversal_point
- success_criteria 能映射到 eval_questions
```

---

## 4. 核心改造三：升级 `characters.json`

### 当前问题

V1 的 characters 更像 roster。

V2 需要让角色真正影响对话走向。

你草案里已经要求角色要有责任、立场、风险偏好、沟通风格、信息访问等级等字段。

### 新版角色 schema

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

### 角色类型必须覆盖

```text
driver
blocker
constraint_owner
resolver
executor
external_pressure_proxy
```

### 验收标准

```text
- character_count >= 6
- 至少包含 driver / blocker / constraint_owner / resolver
- 至少一个角色知道 hidden constraint
- 至少一个角色只代表外部压力
- 至少一个角色负责最终裁决 current state
```

---

## 5. 核心改造四：新增 `conversation_plan.json`

### 为什么这是 V2 最重要的文件

不要让 LLM 直接生成消息。

要先生成计划：

```text
哪些 session
哪些 topic
哪些 source
哪些状态变化
哪些事件类型
哪些消息承担证据作用
```

你草案也明确说：`conversation_plan` 不直接是消息，而是一个多轮讨论计划，负责 session、topic、source、turn 顺序和必须发生的状态演化。

### 示例结构

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

### 生成方式

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

### 验收标准

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

这些阈值来自你 V2 草案里的复杂度规则。

---

## 6. 核心改造五：新增 `utterance_plan` 和 `realized_messages`

### 为什么不能直接生成消息

如果直接生成消息，会有两个问题：

```text
1. 消息自然，但不可测
2. gold event 很难稳定追溯
```

所以要分两步：

```text
conversation_plan
  → utterance_plan
  → realized_messages
```

### `utterance_plan.jsonl`

每条计划 turn 都要显式标注它的作用：

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

### `realized_messages.jsonl`

这是最终自然语言消息：

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

### 生成方式

```text
LLM 负责：
- 把 utterance_plan 改写成自然语言消息

规则负责：
- 检查 must_include_facts 是否出现
- 检查 evidence_quote 是否能命中原文
- 检查 message_id / turn_id / topic_key 是否完整
- 检查时序是否稳定
```

### 验收标准

```text
- 每条 should_be_gold_evidence=true 的消息都能生成 expected_event
- evidence_quote 必须是 content_text 子串
- 不允许 gold 只存在于隐含语气
- 不允许关键事实只靠上下文推断
```

这和你的 Task Wiki 设计一致：event 必须来自 Core 原文，quote 直接支撑，不能让模型脑补。

---

## 7. 核心改造六：保留 execute / collect / adapt 的规则确定性

这里不建议全部 LLM 化。

V1 的 execute / collect / adapt 规则链路是有价值的：

```text
execute:
  确定性把计划写入飞书

collect:
  拉取真实飞书消息

adapt:
  转成 OpenClaw ingress
```

V1 文档里也说明 execute 当前静态模式是 0 次 LLM 调用、纯规则确定性执行，collect/adapt 也是纯 IO 或规则转换。

V2 应该保留这个优点。

### 推荐边界

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

一句话：

```text
LLM 负责“内容多样性”，规则负责“结构正确性和可评测性”。
```

---

## 8. 核心改造七：新增 gold 生成与人工校验流程

### 需要新增的 gold 文件

```text
gold/
  expected_events.jsonl
  expected_memory_blocks.json
  expected_current_state.json

eval/
  eval_questions.json
```

### `expected_events.jsonl`

用于评 Layer 2。

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

### `expected_memory_blocks.json`

用于评 Layer 3 组织能力。

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

### `expected_current_state.json`

用于评 current state。

```json
{
  "topic_key": "release_date",
  "current_state": "不能对外承诺 5 月 5 日；对外只能说预计 5 月上旬",
  "active_claims": ["不能对外承诺 5 月 5 日", "对外只能说预计 5 月上旬"],
  "superseded_claims": ["5 月 5 日是确定上线日期"],
  "must_not_show_as_current": ["可以直接承诺客户 5 月 5 日"],
  "supporting_event_ids": ["gold_evt_002", "gold_evt_003"],
  "superseded_event_ids": ["gold_evt_001"]
}
```

### `eval_questions.json`

用于评用户问题。

```json
{
  "question_id": "q_release_001",
  "question": "5 月 5 日现在能不能对外承诺？",
  "expected_answer_points": [
    "不能对外承诺 5 月 5 日",
    "5 月 5 日只是内部目标",
    "对外口径是预计 5 月上旬"
  ],
  "forbidden_answer_points": ["5 月 5 日已确认上线", "可以直接承诺客户 5 月 5 日"],
  "required_topics": ["release_date_policy", "sales_commitment_risk"]
}
```

### Gold 生成方式

推荐三步：

```text
1. 自动 draft
   根据 utterance_plan 生成 expected_events / memory_blocks / current_state 草稿

2. 程序校验
   evidence_quote 是否是消息子串
   event_id 是否存在
   block 引用是否闭合
   current_state 是否有 supporting_event_ids

3. 人工 review
   第一批 5-10 个黄金 case 必须人工过一遍
```

---

## 9. 核心改造八：新增 Dataset Validation

这是单元测试层。

它验证：

```text
这个 case 是否合格。
```

不比较系统方法。

### 新增模块

```text
builder_v2/validation/
  schema_validator.py
  complexity_validator.py
  gold_consistency_validator.py
  ingress_validator.py
```

### 必做测试

```text
Schema tests:
- case_seed schema valid
- case_world schema valid
- characters schema valid
- conversation_plan schema valid
- realized_messages schema valid
- openclaw ingress schema valid

Complexity tests:
- session_count >= 3
- source_session_count >= 3
- message_count >= 18
- topic_count >= 3
- event_family_coverage >= 5
- state_transition_count >= 4
- supersession_count >= 1
- cross_source_revision_count >= 1

Gold consistency tests:
- 每个 expected_event 都有 evidence_message_id
- evidence_quote 是 content_text 子串
- expected_memory_blocks 引用的 event_id 都存在
- expected_current_state 的 active / superseded claim 都能追溯到 event
- eval_questions 的 required_topics 都能命中 memory block

Ingress tests:
- openclaw_message_ingress.jsonl 可被 OpenClaw 消费
- message 顺序稳定
- thread_id / root_id / chat_id 完整
```

### 输出

```text
checks/
  complexity_report.json
  dataset_validation_report.json
```

---

## 10. 核心改造九：新增 Component Scoring

这是组件测试层。

它验证：

```text
Task Wiki pipeline 每一层是否正确。
```

### Layer 1：Task Binding

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

### Layer 2：Event Extraction

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

Task Wiki 文档里已经定义了 session_event：它必须是由原文 quote 支撑、通过 verification 的最小协作事实。

---

### Layer 3：Memory Block

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

Memory Block 在你的系统里就是围绕同一问题、主题、决策轴或执行事项聚合 session_event 的结构，且内部用 KI Slot 组织 conclusion、objection、constraint、time 等信息。

---

### Layer 4：Current State

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

## 11. 核心改造十：新增 System Evaluation

这是最终系统测试层。

它比较：

```text
OpenClaw 原始处理方式
vs
Task Wiki 方式
```

### 输入相同

```text
data/openclaw_message_ingress.jsonl
```

### Run A：Baseline

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

### Run B：Task Wiki

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

### Scoring

对比 gold：

```text
expected_events.jsonl
expected_memory_blocks.json
expected_current_state.json
eval_questions.json
```

### 输出报告

```json
{
  "case_id": "case_release_001",
  "baseline": {
    "event_recall": 0.62,
    "current_state_accuracy": 0.5,
    "stale_claim_errors": 3,
    "qa_accuracy": 0.58,
    "citation_accuracy": 0.41
  },
  "task_wiki": {
    "event_recall": 0.81,
    "current_state_accuracy": 0.9,
    "stale_claim_errors": 0,
    "qa_accuracy": 0.86,
    "citation_accuracy": 0.82
  }
}
```

---

## 12. 建议的工程目录

```text
amem_docs/
  builder_v2/
    seed/
      seed_schema.py
      seed_generator.py

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
      complexity_validator.py
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

脚本可以保留 V1 风格，但新增 V2 phase：

```bash
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase generate-seeds
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase compile-v2
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase validate-dataset
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase execute
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase collect
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase adapt
amem_docs/scripts/feishu-builder-agent-v2-run.sh --phase score
```

---

## 13. 推荐分阶段实施

### Phase 1：先解决“只能一个 case”的问题

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
运行一次生成 5 个 case_seed
每个 case_id / task_id 不同
difficulty / domain / complexity_profile 可控
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
每个 case 有明确 conflict_axes / hidden_constraints / reversal_points
每个 case 至少 6 个角色
角色有立场差异和信息不对称
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
每个 gold candidate 都能回到 message_id
evidence_quote 是原文子串
消息顺序稳定
thread/root/chat 关系可构造
```

---

### Phase 5：复用 / 改造 execution_plan

目标：

```text
把 realized_messages 转成 V1 可执行的 execution_plan。
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
可以跑 --phase full --dry-run
可以生成 openclaw_message_ingress.jsonl
不破坏 V1 execute/collect/adapt
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
expected_events 都有 evidence_quote
expected_memory_blocks 引用 event_id 闭合
expected_current_state 能表达 active / superseded
eval_questions 能映射到 memory block
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
不合格 case 自动 fail
报告能说明 fail 在哪里
支持批量统计通过率
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
能对单 case 输出 layer-by-layer score
能指出 missing event / wrong slot / stale claim
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
同一 ingress 可跑两套系统
能输出 baseline vs task_wiki 指标对比
能定位 Task Wiki 优势主要来自哪里
```

---

## 14. 第一版 MVP 范围

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

## 15. 最终判断

你的理解是对的：

```text
只补测试不够。
V1 的 case 生成方式也必须改。
```

完整 V2 应该是：

```text
生成器改造：
从固定 case_spec
升级为 case_seed + case_world + conversation_plan + messages

测试体系改造：
从“能不能跑”
升级为 dataset validation + component scoring + system evaluation

比较方式改造：
从单系统自测
升级为 OpenClaw 原始方式 vs Task Wiki 方式
```

最重要的一点是：

```text
LLM 不应该替代规则。
LLM 负责生成多样性。
规则负责约束、校验、可复现、可评测。
```

这样你才能同时解决两个问题：

```text
1. V1 永远只能生成一个固定 case
2. 数据集无法证明 Task Wiki 的实际价值
```
