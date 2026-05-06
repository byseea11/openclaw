# Task Wiki Benchmark Builder Skill 设计拆分稿

> 目标：先把 Skill 需要包含的部分拆清楚，作为后续正式编写 `SKILL.md` 和 references 的基础。  
> 当前版本优先对齐 builder agent 的三阶段执行流程，不先重构 pipeline。

---

## 1. Skill 定位

这个 Skill 的定位不是普通故事生成器，而是：

```text
指导 builder agent 生成 Task Wiki vs OpenClaw Memory.md 的企业级 benchmark 数据集。
```

它主要规定：

```text
1. builder agent 应该按什么流程生成数据集
2. 每个阶段的职责是什么
3. 哪些地方必须针对 OpenClaw Memory.md 的弱点
4. 如何判断一个 case 是否有效
5. 每个阶段应该产出什么 artifact
6. 最终 Benchmark Report 应该证明什么
```

一句话：

```text
Skill = builder agent 的三阶段执行 SOP + OpenClaw weakness 定义 + artifact contract。
```

---

## 2. 第一版 Skill 目录结构

第一版不要拆太细，先保持轻量。

```text
task-wiki-benchmark-builder/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    ├── full.workflow.md
    ├── phase1.case-generation.md
    ├── phase2.gold-eval.md
    ├── phase3.baseline-report.md
    ├── openclaw-weaknesses.md
    └── artifact-contracts.md
```

暂时不需要：

```text
scripts/
assets/
family-personal-memory-pollution.md
family-static-memory-stale-state.md
family-unverifiable-summary-claim.md
family-dependency-propagation.md
```

这些可以放到第二版再拆。

---

## 3. SKILL.md 应该包含什么

`SKILL.md` 只做入口和路由，不写过多细节。

### 3.1 Frontmatter

```yaml
---
name: task-wiki-benchmark-builder
description: generate enterprise-grade benchmark datasets for comparing task wiki against openclaw memory.md. use when creating, revising, or validating benchmark cases involving openclaw weakness targeting, anti-interference tests, contradiction-update tests, probe targets, annotation gold, baseline comparison, value evaluation, or benchmark reports.
---
```

### 3.2 一句话目标

```text
Use this skill to guide builder agents that generate enterprise-grade benchmark datasets comparing Task Wiki against OpenClaw Memory.md.
```

中文解释：

```text
这个 Skill 用来规定 builder agent 如何生成企业级 benchmark 数据集，而不是单纯生成故事。
```

### 3.3 核心原则

`SKILL.md` 中应该写清楚以下原则：

```text
1. 不要先写故事，先确定 benchmark 目标和 OpenClaw weakness。
2. 每个 case 必须至少命中一个 OpenClaw Memory.md 的具体弱点。
3. case-world 和 characters 必须在 weakness 约束下生成，不能先编世界再硬塞 weakness。
4. collect 之前不能生成真正 gold，只能生成 probe targets 或计划目标。
5. annotation gold 必须在 collect 之后，基于真实 observed messages 回标。
6. 如果 probe query 只是读取 Memory.md 中已有显式字段，它不是有效 failure probe。
```

### 3.4 Reference loading rules

`SKILL.md` 需要告诉 agent 什么时候读哪个文件：

```md
## Reference loading rules

- 需要理解完整 builder 流程时，读取 `references/full.workflow.md`。
- 需要生成 case、企业故事、角色、计划消息、命令计划、执行与采集时，读取 `references/phase1.case-generation.md`。
- 需要定义或检查 OpenClaw 弱点与四类 case 时，读取 `references/openclaw-weaknesses.md`。
- 需要生成 annotation gold、gold validate、replay runtime 或 replay eval 时，读取 `references/phase2.gold-eval.md`。
- 需要跑 Memory.md baseline、value eval 或 Benchmark Report 时，读取 `references/phase3.baseline-report.md`。
- 需要检查每个 artifact 的输入输出字段时，读取 `references/artifact-contracts.md`。
```

---

## 4. full.workflow.md 应该包含什么

`full.workflow.md` 负责描述完整三阶段流程。

### 4.1 三阶段总览

```text
Phase 1: Case Generation
生成会让 OpenClaw Memory.md 失败的企业级 case，并完成 execute / collect。

Phase 2: Gold + Eval
基于 collected messages 生成 annotation gold，并运行 Task Wiki replay eval。

Phase 3: Baseline + Report
运行 OpenClaw Memory.md baseline、value eval，并生成最终 benchmark report。
```

### 4.2 完整流程

```text
Phase 1: Case Generation
spec-generation
-> openclaw-weakness-selection
-> case-world
-> characters
-> plan
-> probe-targets
-> command-plan
-> execute
-> collect
-> pre-gold-validate
-> adapt

Phase 2: Gold + Eval
annotation-gold
-> gold-validate
-> replay-runtime
-> replay-eval

Phase 3: Baseline + Report
memory-md-baseline
-> value-eval
-> benchmark-report
```

### 4.3 当前 Skill 的约束

```text
1. Skill 第一版先对齐这个简化三阶段流程。
2. 具体工程实现可以继续复用已有 builder agent 底座。
3. 不在 Skill 第一版里强行拆 task-actor-layout、state-trajectory、memory-failure-blueprint 等内部实现细节。
4. 如果当前代码里已有更细阶段，可以把它们映射到上面的简化阶段。
```

---

## 5. phase1.case-generation.md 应该包含什么

这个文件负责定义 Phase 1：如何生成 OpenClaw fail case。

### 5.1 Phase 1 目标

```text
稳定生成会让 OpenClaw Memory.md 暴露弱点的数据，并在 collect 后验证关键 trap 是否落地。
```

### 5.2 Phase 1 流程

```text
spec-generation
-> openclaw-weakness-selection
-> case-world
-> characters
-> plan
-> probe-targets
-> command-plan
-> execute
-> collect
-> pre-gold-validate
-> adapt
```

### 5.3 阶段说明

#### spec-generation

职责：生成 case 的最小控制信息。

应确定：

```text
case_id
task_id
difficulty
benchmark_goal
comparison_target
required_test_type
```

不要在这个阶段写故事。

---

#### openclaw-weakness-selection

职责：选择这条 case 要针对的 OpenClaw weakness。

应确定：

```text
primary_weakness
secondary_weaknesses
expected_openclaw_failure
expected_task_wiki_success
```

这个阶段可以是 spec-generation 的内部步骤，也可以是 case-world 的前置约束，但在 Skill 语义上必须显式存在。

---

#### case-world

职责：在 OpenClaw weakness 约束下生成企业协作场景。

应回答：

```text
这个企业场景是什么？
有哪些任务？
有哪些干扰任务？
为什么这些任务会被同时讨论？
为什么这些信息会分散在不同人、不同 source 或不同 session 里？
为什么这个场景会让 Memory.md 容易失败？
```

禁止：

```text
先编一个普通企业故事，再后补 weakness。
```

---

#### characters

职责：生成参与者，并明确每个人在不同任务中的角色。

应包含：

```text
actor_id
display_name
team
role
task_roles
pollution_risk
```

重点：

```text
同一个人可以出现在多个任务中，但必须明确他在每个任务中的角色不同。
```

---

#### plan

职责：生成消息计划，把 case-world、characters 和 weakness 变成具体对话结构。

应包含：

```text
source/session
turn 顺序
speaker
message intent
benchmark role
memory trap
expected OpenClaw risk
Task Wiki expected handling
```

---

#### probe-targets

职责：生成 collect 前的计划型 query 目标。

注意：

```text
probe-targets 不是 gold。
probe-targets 只是说明这个 case 最后应该问什么，预期暴露什么 Memory.md failure。
```

每个 probe target 应包含：

```text
query
source weakness
expected_openclaw_failure
task_wiki_success_condition
metric_targets
```

---

#### command-plan

职责：把 plan 转成可执行命令。

应保证：

```text
每个 planned turn 都能映射到一个 command。
command 的 speaker、source、timestamp 合法。
```

---

#### execute

职责：执行 command-plan。

输出执行结果。

---

#### collect

职责：采集真实 observed messages。

注意：

```text
后续 annotation gold 只能基于 collected messages 生成。
不能基于 plan 或 probe-targets 脑补 gold。
```

---

#### pre-gold-validate

职责：在生成 gold 前检查数据是否可用。

应检查：

```text
关键 weakness 是否真的落地
关键消息是否成功 collect
probe-targets 是否有对应上下文
是否有足够 distractor / update / evidence / dependency
```

---

#### adapt

职责：修正 observed data 的覆盖问题。

限制：

```text
只修完整性和覆盖问题，不直接改 gold 语义。
```

---

## 6. phase2.gold-eval.md 应该包含什么

这个文件负责定义 Phase 2：如何生成 annotation gold 并评估 Task Wiki。

### 6.1 Phase 2 流程

```text
annotation-gold
-> gold-validate
-> replay-runtime
-> replay-eval
```

### 6.2 annotation-gold

职责：基于 collected messages 回标 gold。

必须遵守：

```text
1. gold 必须来自真实 collected messages。
2. verified event 必须有 evidence_quote。
3. 如果 collected text 不支持预期 event，必须降级或报错。
4. benchmark_role / memory_trap 只能作为 annotation hint，不能直接当 gold。
```

### 6.3 gold-validate

职责：检查 gold 与 observed data 是否一致。

应检查：

```text
evidence_message_id 是否存在
evidence_quote 是否能在原文中找到
current state 和 stale state 是否区分清楚
probe query 是否能回到 source weakness
```

### 6.4 replay-runtime

职责：运行 Task Wiki runtime。

输出：

```text
candidate_events
session_events
session_wiki_state
task_index_state
task_wiki_state
task_wiki_answers
```

### 6.5 replay-eval

职责：比较 Task Wiki prediction 与 annotation gold。

至少按以下维度输出：

```text
event-level eval
block/current-state eval
QA eval
by_weakness aggregation
```

---

## 7. phase3.baseline-report.md 应该包含什么

这个文件负责定义 Phase 3：如何跑 OpenClaw baseline、value eval 和最终报告。

### 7.1 Phase 3 流程

```text
memory-md-baseline
-> value-eval
-> benchmark-report
```

### 7.2 memory-md-baseline

职责：用同一批 probe queries 跑 OpenClaw Memory.md baseline。

必须记录：

```text
baseline mode
query
Memory.md answer
failure labels
是否有 evidence quote
是否混入无关任务
是否返回 stale state
```

baseline mode 可以是：

```text
openclaw_compatible
prompt_simulated
fixture
```

第一版可以先用 `prompt_simulated` 或 `fixture`，但报告里必须标注清楚。

### 7.3 value-eval

职责：比较 Task Wiki 与 OpenClaw Memory.md 的效果。

建议指标：

```text
task_specific_answer_accuracy
irrelevant_memory_pollution_rate
evidence_citation_success_rate
stale_memory_answer_rate
current_state_answer_accuracy
dependency_impact_recall
memory_claim_traceability_rate
memory_scope_purity
```

### 7.4 benchmark-report

职责：生成最终自证评测报告。

必须包含：

```text
dataset overview
tested weaknesses
anti-interference results
contradiction-update results
evidence validation results
OpenClaw baseline failures
Task Wiki success evidence
value metrics
limitations
reproducibility notes
```

---

## 8. openclaw-weaknesses.md 应该包含什么

这个文件是第一版 Skill 的核心。

它负责定义四类 case，以及每类 case 如何打 Memory.md 的弱点。

---

### 8.1 personal_memory_pollution

#### Weakness

Memory.md 以个人为中心组织信息，多个任务和多个人的信息容易混在一起，导致目标任务信息被干扰任务稀释。

#### 用于什么测试

```text
抗干扰测试
任务隔离测试
只看 target task 的查询
```

#### 必须生成

```text
1 个 target task
2-3 个 distractor tasks
3-5 个 shared actors
多个相似字段：owner、deadline、blocker、approval_status、dependency
```

#### 有效 probe

```text
只看 FEISHU-231，不要混入 PROD-123：当前负责人、审批状态和阻塞项分别是什么？请给证据。
```

#### 无效 probe

```text
FEISHU-231 当前负责人是谁？
```

因为这个问题可能直接从 Memory.md 显式字段中读出来。

---

### 8.2 unverifiable_summary_claim

#### Weakness

Memory.md 可以生成看似合理的总结，但没有 evidence quote，无法验证它来自明确事实、猜测、转述还是普通确认。

#### 用于什么测试

```text
证据引用测试
事实 / 模糊表达 / 转述 / no-event 区分测试
```

#### 必须生成

```text
verified_fact turn
ambiguous_claim turn
hearsay turn
weak_commitment turn
ordinary_ack turn
no_event turn
```

#### 有效 probe

```text
财务问题是谁明确提出的？这是确定阻塞、猜测还是转述？请给原文证据。
```

#### 无效 probe

```text
FEISHU-231 有财务问题吗？
```

---

### 8.3 static_memory_stale_state

#### Weakness

Memory.md 会保留历史状态，但不一定能稳定区分 current state 和 stale state。

#### 用于什么测试

```text
矛盾更新测试
时序覆盖测试
current-state 测试
```

#### 必须生成

```text
initial state
intermediate update
final current state
stale states
supersession relation
```

#### 有效 probe

```text
FEISHU-231 当前负责人是谁？Bob 和 Alice 现在还负责吗？请说明依据。
```

#### 无效 probe

```text
FEISHU-231 负责人是谁？
```

---

### 8.4 dependency_propagation_failure

#### Weakness

Memory.md 可能记录了依赖关系，但不能稳定回答上游任务状态变化会影响哪些下游任务。

#### 用于什么测试

```text
企业任务网络测试
依赖传播测试
下游影响查询
```

#### 必须生成

```text
1 个 upstream task
至少 2 个 downstream tasks
1 个 upstream blocker update
至少 1 个 downstream impact query
```

#### 有效 probe

```text
FEISHU-231 的财务问题现在会影响哪些下游任务？影响依据是什么？
```

#### 无效 probe

```text
FEISHU-312 依赖什么？
```

---

## 9. artifact-contracts.md 应该包含什么

这个文件负责定义每个阶段的核心输入输出。

第一版不用写完整 JSON schema，只列 required fields。

---

### 9.1 case_spec.json

Purpose:

```text
定义 case 的最小控制信息。
```

Required fields:

```text
case_id
task_id
benchmark_goal
comparison_target
required_test_type
primary_weakness
difficulty
```

---

### 9.2 case_world.json

Purpose:

```text
定义企业协作场景。
```

Required fields:

```text
enterprise_context
target_task
distractor_tasks
sources
realism_factors
weakness_alignment
```

---

### 9.3 characters.json

Purpose:

```text
定义参与者及其任务角色。
```

Required fields:

```text
actor_id
display_name
team
role
task_roles
pollution_risk
```

---

### 9.4 plan.json

Purpose:

```text
定义消息级计划。
```

Required fields:

```text
turn_id
source
timestamp
speaker
message_intent
related_task_ids
benchmark_role
memory_trap
expected_openclaw_risk
task_wiki_expected_handling
```

---

### 9.5 probe_targets.json

Purpose:

```text
定义 collect 前的计划型 probe。
```

Required fields:

```text
query_id
query
source_weakness
source_trap_id
expected_openclaw_failure
task_wiki_success_condition
metric_targets
```

---

### 9.6 command_plan.jsonl

Purpose:

```text
定义可执行动作。
```

Required fields:

```text
command_id
action
source
speaker
message
timestamp
planned_turn_id
```

---

### 9.7 collected_messages.jsonl

Purpose:

```text
记录真实 collected messages。
```

Required fields:

```text
message_id
source
timestamp
speaker
text
related_task_ids
```

---

### 9.8 annotation_gold.jsonl

Purpose:

```text
基于 collected messages 生成 annotation gold。
```

Required fields:

```text
event_id
task_id
event_type
claim
evidence_message_id
evidence_quote
current_state_flag
stale_state_flag
```

---

### 9.9 memory_md_baseline_results.json

Purpose:

```text
记录 OpenClaw Memory.md baseline 结果。
```

Required fields:

```text
query_id
baseline_mode
answer
failure_labels
has_evidence_quote
```

---

### 9.10 value_eval.json

Purpose:

```text
比较 Task Wiki 与 OpenClaw Memory.md。
```

Required fields:

```text
metrics
by_weakness
by_query_family
summary
```

---

### 9.11 benchmark_report.md

Purpose:

```text
生成最终自证评测报告。
```

Required sections:

```text
摘要
数据集设计
测试的 OpenClaw weaknesses
抗干扰测试结果
矛盾更新测试结果
证据验证结果
baseline 对比
效能指标
结论与限制
```

---

## 10. 第一版不做什么

第一版 Skill 暂时不做：

```text
1. 不拆四个 family 独立 reference 文件。
2. 不写完整 JSON schema。
3. 不强制添加 scripts。
4. 不强制添加 assets。
5. 不在 Skill 里重构当前 builder agent 的内部实现。
6. 不把 collect 前的 probe-targets 当成 gold。
```

---

## 11. 后续第二版可以增加什么

第二版可以增加：

```text
references/family-personal-memory-pollution.md
references/family-unverifiable-summary-claim.md
references/family-static-memory-stale-state.md
references/family-dependency-propagation.md
references/validation-rules.md
scripts/validate_case_artifacts.py
assets/examples/example_case/
```

---

## 12. 当前结论

第一版 Skill 应该先解决三个问题：

```text
1. 和 builder agent 当前三阶段执行流程一致。
2. 明确定义 OpenClaw Memory.md 的四类 weakness。
3. 明确每个阶段的 artifact 输入输出边界。
```

不要先追求复杂 schema，也不要先重构 pipeline。

当前最小可行目标是：

```text
让 agent 看到这个 Skill 后，知道应该按三阶段流程生成 OpenClaw fail benchmark 数据集，并且知道何时读取哪个 reference 文件。
```

