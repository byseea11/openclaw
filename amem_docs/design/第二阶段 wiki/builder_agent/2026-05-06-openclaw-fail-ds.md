对，这个判断是对的。你现在这份重构方案还是偏“评测框架设计”，但**没有把最关键的东西讲清楚**：

> 到底怎样生成一批会让 OpenClaw 当前 `Memory.md` 失败、但 Task Wiki 能成功的数据？

这应该单独成为文档里的核心章节。否则你的 benchmark 只是“复杂”，不是“有杀伤力”。

---

# 1. 你缺的是一层：`failure-oriented case generation`

你现在文档讲了：

```text
case_world
-> state_trajectory
-> story_beats
-> evidence_obligations
-> natural_messages
-> collect
-> annotation gold
-> replay
-> eval
```

但还缺这个逻辑：

```text
OpenClaw Memory.md failure mode
-> case pattern
-> source/message construction
-> probe query
-> metric
```

也就是说，case 不是随便复杂，而是要先决定：

```text
这个 case 要让 Memory.md 怎么失败？
```

然后倒推：

```text
需要哪些任务？
需要哪些人？
需要哪些 source？
需要哪些消息？
需要哪些旧状态？
需要哪些模糊信息？
需要哪些混杂信息？
最后问什么问题能把失败暴露出来？
```

所以你的文档里应新增一节：

```text
## OpenClaw Failure-oriented Case Generation
```

---

# 2. 生成 OpenClaw fail 数据的总流程

应该写成这个流程：

```text
1. 选择 Memory.md 失败模式
2. 选择对应 case pattern
3. 生成任务与人员混杂环境
4. 生成目标 task 的状态轨迹
5. 生成干扰 task / 干扰人员信息
6. 生成多 source 协作消息
7. 注入 Memory.md trap
8. 生成 probe queries
9. 生成 evidence-bound gold
10. 跑 OpenClaw Memory.md baseline 与 Task Wiki 对比
```

更工程化一点：

```text
memory_failure_profile
-> failure_case_pattern
-> task_and_actor_layout
-> target_task_state_trajectory
-> distractor_memory_context
-> source_session_plan
-> trap_turn_plan
-> natural_messages
-> memory_probe_queries
-> annotation_gold
-> baseline_comparison
```

这才是“如何生成 OpenClaw fail 数据”。

---

# 3. 三类 OpenClaw fail 数据应该分别怎么生成

你的 OpenClaw 问题已经写得很清楚：个人为核心导致信息分散，抽取不完全和多源冲突，无法验证与更新。
所以 case generation 要围绕这三类失败模式分别生成。

---

## Failure Mode 1：个人 Memory.md 稀释 / 任务边界失败

### 要让 OpenClaw 怎么失败？

让 `Memory.md` 把多个任务、多个角色、多个时间状态混在一起，导致用户问某个 task 时，它要么答进无关任务，要么漏掉目标任务的关键信息。

### Case pattern

```text
Personal Memory Pollution Pattern
```

### 生成规则

一个 case 里至少生成：

```text
1 个 target task
2-3 个 distractor tasks
3-5 个 shared actors
多条跨任务相似字段
```

例如：

```text
target task: FEISHU-231 接入方案
distractor task A: PROD-123 新功能上线
distractor task B: FEISHU-312 上线依赖
distractor task C: FEISHU-291 财务审批
shared actors: Alice / Bob / Carol / xzy
```

关键是让多个任务共享相同人员、相似字段：

```text
负责人
审批状态
截止时间
依赖关系
当前 blocker
```

这样 `Memory.md` 很容易变成：

```text
Bob 关联 FEISHU-231 和 PROD-123
Carol 关联审批和财务
FEISHU-312 依赖 FEISHU-231
PROD-123 也有审批和迁移
```

最后用户问：

```text
只看 FEISHU-231，当前负责人是谁？当前阻塞是什么？
```

OpenClaw Memory.md 的失败可能是：

```text
把 PROD-123 的 AP-456 或 TASK-789 混进 FEISHU-231；
把 Bob/Alice/xzy 都当成当前负责人；
回答包含无关任务信息。
```

Task Wiki 应该成功，因为它以 `task_id` 组织记忆，而不是以个人 Memory.md 混写。

### 需要写进 case 的字段

```json
{
  "failure_case_pattern": "personal_memory_pollution",
  "target_task_id": "FEISHU-231",
  "distractor_tasks": ["PROD-123", "FEISHU-312", "FEISHU-291"],
  "shared_actors": ["Alice", "Bob", "Carol", "xzy"],
  "pollution_dimensions": [
    "相同负责人出现在多个任务",
    "多个任务都有审批状态",
    "多个任务都有依赖关系",
    "同一用户 Memory.md 同时记录项目与人员信息"
  ],
  "openclaw_expected_failure": [
    "回答目标任务时混入其他任务状态",
    "无法区分当前负责人和历史负责人",
    "把人员长期信息当成任务当前信息"
  ],
  "task_wiki_expected_success": [
    "只返回绑定到 target_task_id 的信息",
    "区分当前状态与历史状态",
    "通过 task_wiki / index 定位目标任务相关 block"
  ]
}
```

### 对应指标

```text
Task Memory Isolation Accuracy
Irrelevant Memory Pollution Rate
Task-specific Answer Accuracy
```

---

## Failure Mode 2：无证据 Memory claim / 真伪不可验证

### 要让 OpenClaw 怎么失败？

让 `Memory.md` 可以写出一个看似合理的总结，但这条总结没有证据，或者把猜测、转述、弱承诺写成确定事实。

### Case pattern

```text
Unverifiable Summary Claim Pattern
```

### 生成规则

同一个 topic 下生成 4 类消息：

```text
A. 明确事实消息
B. 模糊表达消息
C. 转述/猜测消息
D. 普通确认/无事件消息
```

例如关于财务问题：

```text
明确事实：
Carol：财务这边还没过，FEISHU-231 先不要继续推进。

模糊表达：
Bob：感觉财务那边可能还有点问题。

转述：
Alice：我听说财务好像还没确认。

无事件：
xzy：收到，我先看看。
```

OpenClaw Memory.md 可能写成：

```text
财务有问题，需要等财务好了才能继续。
```

这个总结“可能还不错”，但问题是：

```text
它来自哪一句？
是 Carol 的明确事实，还是 Bob 的猜测？
有没有把“可能”写成“确定”？
```

Task Wiki 应该把 Carol 的明确事实写成 verified event，把 Bob 的“可能”降级为 needs_review 或不作为 verified，把“收到我看看”标成 no_event。

### 需要写进 case 的字段

```json
{
  "failure_case_pattern": "unverifiable_summary_claim",
  "target_claim": "FEISHU-231 当前受财务问题阻塞",
  "evidence_distribution": {
    "verified_fact_turns": 2,
    "ambiguous_turns": 2,
    "hearsay_turns": 1,
    "ordinary_ack_turns": 2,
    "context_only_turns": 1
  },
  "openclaw_expected_failure": [
    "把模糊表达写成确定记忆",
    "Memory.md claim 无法回到原文 quote",
    "无法区分 verified fact 与 hearsay / weak signal"
  ],
  "task_wiki_expected_success": [
    "verified event 必须绑定 evidence_quote",
    "弱表达进入 needs_review 或 no_event",
    "回答时能引用原文证据"
  ]
}
```

### 对应指标

```text
Evidence Coverage Rate
Unsupported Memory Claim Rate
Verified Event Precision
No-event False Positive Rate
Needs Review Accuracy
```

---

## Failure Mode 3：静态 Memory.md 不会自动更新 / 旧状态继续污染当前态

### 要让 OpenClaw 怎么失败？

让同一个任务的状态连续变化，早期状态仍然是真实历史，但已经不是当前状态。`Memory.md` 容易把多个状态都堆在一起，或者继续把旧状态当当前状态。

### Case pattern

```text
Static Memory Stale State Pattern
```

### 生成规则

一个 topic 至少生成三段状态：

```text
initial state
intermediate update
final current state
```

例如负责人变更：

```text
t1: FEISHU-231 负责人 Bob
t2: Bob 转给 Alice
t3: Alice 有事，xzy 接手
```

截止时间变更：

```text
t1: 截止 4/24
t2: 改到 4/28
```

审批状态变更：

```text
t1: 法务审批中
t2: 新增财务问题
t3: 财务未过前不能继续
```

OpenClaw Memory.md 可能保留：

```text
当前负责人：xzy（原为 Alice，再原为 Bob）
```

这看似还不错，但它无法稳定证明：

```text
哪条是 current？
谁说了这次变更？
如果后续又变了，如何增量更新？
下游任务是否同步受影响？
```

Task Wiki 应该把这些变化作为 event ledger，current slot 指向最新 event，旧 event 标为 stale/historical。

### 需要写进 case 的字段

```json
{
  "failure_case_pattern": "static_memory_stale_state",
  "state_tracks": [
    {
      "track_key": "owner",
      "states": ["Bob", "Alice", "xzy"],
      "final_current_state": "xzy",
      "stale_states": ["Bob", "Alice"]
    },
    {
      "track_key": "deadline",
      "states": ["2026-04-24", "2026-04-28"],
      "final_current_state": "2026-04-28",
      "stale_states": ["2026-04-24"]
    },
    {
      "track_key": "blocker",
      "states": ["法务审批中", "新增财务问题"],
      "final_current_state": "新增财务问题",
      "stale_states": ["法务审批中作为唯一阻塞"]
    }
  ],
  "openclaw_expected_failure": [
    "把旧负责人或旧截止时间当成当前状态",
    "无法稳定区分历史状态与 current state",
    "后续新增 session 后不能局部增量更新"
  ],
  "task_wiki_expected_success": [
    "current slot 指向最新状态",
    "stale 状态保留为历史但不作为当前答案",
    "task_wiki 随新 session 增量更新"
  ]
}
```

### 对应指标

```text
Current State Accuracy
Stale Memory Rate
Supersession Accuracy
Incremental Update Accuracy
```

---

## Failure Mode 4：依赖传播失败

这个可以作为增强型 case，不一定是三大突破点之一，但非常适合证明企业任务价值。

### 要让 OpenClaw 怎么失败？

`Memory.md` 可以写出：

```text
FEISHU-312 依赖 FEISHU-231
FEISHU-291 依赖 FEISHU-231 财务审批
```

但当 FEISHU-231 的财务状态变化时，它未必能自动回答：

```text
这会影响哪些下游任务？
```

### Case pattern

```text
Dependency Propagation Pattern
```

### 生成规则

生成：

```text
1 个 upstream task
2 个 downstream tasks
1 个 upstream blocker update
1 个 downstream impact query
```

例如：

```text
FEISHU-231 财务审批未通过
FEISHU-312 依赖 FEISHU-231 完成后上线
FEISHU-291 依赖 FEISHU-231 财务审批通过
```

Probe query：

```text
FEISHU-231 的财务问题现在会影响哪些任务？
```

OpenClaw 可能只列出某些关联任务，但不说明当前影响是否仍成立，也不给证据。

Task Wiki 应该通过 task_wiki / index / dependency block 回答。

### 对应指标

```text
Dependency Impact Recall
Update Propagation Accuracy
Citation Accuracy
```

---

# 4. 应该写在 case generation 里的核心对象

你可以把原来的 `case_world` 扩展成下面这套结构。

```json
{
  "case_generation_goal": {
    "baseline": "openclaw_memory_md",
    "goal": "生成会暴露 OpenClaw Memory.md 失败模式、同时能体现 Task Wiki 优势的企业任务记忆 case"
  },
  "memory_failure_profile": {
    "selected_failure_modes": [
      "personal_memory_pollution",
      "unverifiable_summary_claim",
      "static_memory_stale_state"
    ],
    "primary_failure_mode": "static_memory_stale_state"
  },
  "failure_case_patterns": [
    {
      "pattern_id": "personal_memory_pollution",
      "target_task_count": 1,
      "distractor_task_count": 3,
      "shared_actor_count": 4,
      "required_pollution_dimensions": ["人员混杂", "任务混杂", "审批状态混杂", "依赖关系混杂"]
    },
    {
      "pattern_id": "unverifiable_summary_claim",
      "required_turn_types": [
        "verified_fact",
        "ambiguous_claim",
        "hearsay",
        "ordinary_ack",
        "context_only"
      ]
    },
    {
      "pattern_id": "static_memory_stale_state",
      "required_state_tracks": ["owner", "deadline", "blocker", "approval_status"],
      "minimum_state_changes": 3,
      "minimum_stale_states": 2
    }
  ]
}
```

这个对象不参与 runtime。
它只是让 builder 在生成 case 时知道：

```text
我不是在生成普通复杂故事，我是在生成 Memory.md 会失败的故事。
```

---

# 5. 生成流程要改成“先 trap，后 story”

你现在可能是：

```text
先生成故事
再看故事里有什么状态变化
```

应该改成：

```text
先生成 Memory.md trap
再围绕 trap 生成故事
```

具体流程：

```text
Step 1: Select failure modes
选择要测试的 OpenClaw Memory.md 失败模式。

Step 2: Instantiate trap schema
把失败模式实例化成任务、人员、状态字段、干扰任务和问题类型。

Step 3: Generate state tracks
先生成 owner / deadline / blocker / approval_status 等状态轨迹。

Step 4: Generate source distribution
决定每个状态变化出现在哪个 source：
主群、thread、任务评论、审批消息、客户同步群。

Step 5: Generate distractor context
生成会污染 Memory.md 的其他任务和人员信息。

Step 6: Generate trap turns
生成 baseline_trap_turn、revision_turn、ambiguous_turn、negative_turn。

Step 7: Generate probe queries
每个 trap 至少生成一个能暴露 OpenClaw failure 的问题。

Step 8: Generate annotations after collect
基于 collected_messages 回标 gold。
```

一句话：

```text
不要先写故事再找评测点；
要先设计 Memory.md 会掉进去的坑，再写故事让这个坑自然出现。
```

---

# 6. 每个 turn 也要标注它在制造什么 trap

你的 `conversation_plan.turns` 不应该只有 `supports_event_types` 和 `state_transition`，还要有：

```json
{
  "turn_id": "turn_012",
  "benchmark_role": "baseline_trap_turn",
  "memory_failure_mode": "static_memory_stale_state",
  "memory_trap": "这条早期消息会让 Memory.md 记录 Bob 为负责人，但后续会被 Alice 和 xzy 覆盖。",
  "expected_openclaw_memory_risk": "Memory.md 可能无法区分 Bob 是历史负责人还是当前负责人。",
  "task_wiki_expected_handling": "抽取 owner status event，并在后续 supersession 后降级为 stale。",
  "metric_targets": ["current_state_accuracy", "stale_memory_rate", "supersession_accuracy"]
}
```

另一个 no-event turn：

```json
{
  "turn_id": "turn_020",
  "benchmark_role": "negative_turn",
  "memory_failure_mode": "unverifiable_summary_claim",
  "memory_trap": "这条消息看似像承诺，但实际上只是普通确认。",
  "semantic_payload": "收到，我先看看。",
  "expected_openclaw_memory_risk": "Memory.md 可能把它写成 xzy 已承诺处理财务问题。",
  "task_wiki_expected_handling": "标为 negative_no_event，不生成 verified event。",
  "metric_targets": ["no_event_false_positive_rate", "unsupported_memory_claim_rate"]
}
```

这样 evaluator 后面才知道：

```text
这个 turn 是用来诱发哪种 OpenClaw failure 的。
```

---

# 7. Probe query 必须从 trap 里生成

每个 `memory_trap` 都要生成至少一个 probe query。

不是泛泛问：

```text
这个任务状态是什么？
```

而是问会让 Memory.md 出错的问题：

### 对个人记忆污染

```text
只看 FEISHU-231，不要带 PROD-123：当前负责人和阻塞项是什么？
```

### 对无证据 claim

```text
财务问题是谁明确提出的？请给原文依据。
```

### 对 stale state

```text
FEISHU-231 当前负责人是谁？Bob 和 Alice 现在还负责吗？
```

### 对依赖传播

```text
FEISHU-231 的财务问题现在影响哪些下游任务？
```

每个 query 应该带：

```json
{
  "query_id": "q_owner_current_001",
  "source_trap_id": "trap_owner_handoff_001",
  "failure_mode": "static_memory_stale_state",
  "expected_openclaw_failure": "可能回答 Bob 或 Alice 仍是负责人，或无法区分历史与当前。",
  "task_wiki_success_condition": "回答 xzy 是当前负责人，并说明 Bob/Alice 是历史负责人，同时引用负责人变更证据。",
  "metric_targets": ["current_state_accuracy", "stale_memory_rate", "citation_accuracy"]
}
```

---

# 8. Codex 应该怎么改文档

你可以让 Codex 在现有重构方案里新增一个主章节：

```text
## OpenClaw Fail 数据生成方法
```

这节必须回答：

```text
如何从 Memory.md 失败模式倒推 case？
```

可以给 Codex 这段要求：

```text
请新增一节“OpenClaw Fail 数据生成方法”，不要只讲评测框架，要明确说明如何生成会让 OpenClaw 当前 Memory.md 失败的数据。

这一节需要包含：

1. 总原则：
   case 生成从 complexity-oriented 改为 failure-mode-oriented。
   不是先生成复杂故事再找评测点，而是先选择 Memory.md 失败模式，再倒推任务、人员、source、状态变化、干扰信息和 probe query。

2. 总流程：
   memory_failure_profile
   -> failure_case_pattern
   -> task_and_actor_layout
   -> target_task_state_trajectory
   -> distractor_memory_context
   -> source_session_plan
   -> trap_turn_plan
   -> natural_messages
   -> memory_probe_queries
   -> annotation_gold
   -> baseline_comparison

3. 三类核心 failure mode 的数据生成规则：

   A. personal_memory_pollution
      目标：制造个人 Memory.md 中的任务混杂和信息稀释。
      必须生成：
      - 1 个 target task
      - 2-3 个 distractor tasks
      - 3-5 个 shared actors
      - 多个相似字段：负责人、审批状态、截止时间、依赖关系、阻塞项
      - probe query 必须要求“只看 target task”
      指标：
      - task_memory_isolation_accuracy
      - irrelevant_memory_pollution_rate
      - task_specific_answer_accuracy

   B. unverifiable_summary_claim
      目标：制造 Memory.md 能总结但无法验证真伪的情况。
      必须生成：
      - verified_fact turns
      - ambiguous turns
      - hearsay turns
      - ordinary_ack turns
      - context_only turns
      - weak commitment turns
      probe query 必须要求给 evidence quote。
      指标：
      - evidence_coverage_rate
      - unsupported_memory_claim_rate
      - verified_event_precision
      - no_event_false_positive_rate

   C. static_memory_stale_state
      目标：制造 Memory.md 旧状态继续污染当前态。
      必须生成：
      - 至少 3 条 state tracks，例如 owner、deadline、blocker、approval_status
      - 每条 track 至少有 initial、update、final_current_state
      - stale states 必须仍然是真实历史，但不能作为当前答案
      probe query 必须问 current state。
      指标：
      - current_state_accuracy
      - stale_memory_rate
      - supersession_accuracy
      - incremental_update_accuracy

   可以额外加入 D. dependency_propagation：
      目标：制造上游任务状态变化影响下游任务。
      指标：
      - dependency_impact_recall
      - update_propagation_accuracy
      - citation_accuracy

4. 新增 JSON 示例：
   - memory_failure_profile
   - failure_case_patterns
   - trap_turn_plan
   - memory_probe_queries

5. 明确每个 conversation turn 应该增加字段：
   - benchmark_role
   - memory_failure_mode
   - memory_trap
   - expected_openclaw_memory_risk
   - task_wiki_expected_handling
   - metric_targets

6. 明确每个 query 应该增加字段：
   - source_trap_id
   - failure_mode
   - expected_openclaw_failure
   - task_wiki_success_condition
   - metric_targets

7. 强调：
   OpenClaw fail 数据不是靠让 OpenClaw 故意失败，也不是靠伪造不公平问题；
   而是复现 Memory.md 在个人视角、无证据总结、静态更新机制下自然会失败的企业协作场景。
```

---

# 9. 最核心的一句话

你可以在文档里这样写：

```text
OpenClaw fail 数据的生成不是“生成复杂 case”，而是“先定义 Memory.md 会失败的陷阱，再倒推生成任务、人员、source、状态变化、干扰信息和 probe query”。每个 case 必须明确回答：它复现了哪种 Memory.md 失败模式、哪几条消息构成 trap、OpenClaw 可能如何错误记忆、Task Wiki 应如何处理、最后用哪个 query 和 metric 把差异测出来。
```

这才是你现在缺的核心。
