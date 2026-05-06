# 2026-05-06 feishu_builder_agent V3 三阶段实施计划

## 1. 文档目标与边界

本文是 `feishu_builder_agent` 的 V3 三阶段实施计划，不是 V2 的增量修补说明。

V3 的核心边界是：

1. 不兼容旧 `target_state / expected_* / check golden / target-gold / gold / validate` 流水线。
2. 复用底层 `execute / collect / runtime adapter`。
3. 先生成会让 OpenClaw 当前 `Memory.md` 失败的数据，再做 annotation gold、replay-eval 和 baseline comparison。

这次升级的固定口径是：

```text
V3 不是重写整个 builder 包，而是删除 V2 的 gold/control-plane 语义，在可复用执行底座之上重建 failure-oriented benchmark contract。
```

本文与主设计文档的关系如下：

- `2026-05-06-Task Wiki 评测与 Golden 设计.md`
  继续作为 V3 规范文档
- `2026-05-06-feishu_builder_agent-v3-三阶段实施计划.md`
  作为 builder V3 落地计划文档

## 2. V3 总体流水线

V3 的正式 pipeline 为：

```text
spec-generation
-> memory-failure-blueprint
-> task-actor-layout
-> case-world
-> characters
-> state-trajectory
-> conversation-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
-> optional-adapt
-> annotation-gold
-> build-checks
-> gold-validate
-> replay-runtime
-> replay-eval
-> memory-md-baseline
-> value-eval
-> report
```

每一步的简短职责如下：

- `spec-generation`
  生成最小 case 规格，确定 `case_id`、`task_id`、`difficulty`、`selected_failure_modes`、`primary_failure_mode`。
- `memory-failure-blueprint`
  用正式 prompt 生成并校验 `memory_failure_blueprint`，把 `Memory.md` 的失败模式具体化成 traps、probe queries、落地要求和成功/失败判据。
- `task-actor-layout`
  生成目标任务、干扰任务、共享角色槽位，以及角色和任务的交叉关系。
- `case-world`
  把 blueprint 翻译成自然企业协作背景，解释为什么这些人会在这些场景里讨论这些问题。
- `characters`
  把角色槽位实例化成具体人物，并生成 `characters.json` 与 `actor_registry.json`。
- `state-trajectory`
  生成每个 topic 的状态演进、修正关系、过期状态和最终 current state。
- `conversation-plan`
  直接基于 blueprint 和 state trajectory 生成多 source、多 session、多 turn 的对话计划，并标注每条 turn 的 benchmark 角色和风险意图。
- `command-plan`
  把对话计划转成可执行动作，如建群、发消息、回 thread、拉消息。
- `execute`
  真实执行这些动作，把 case 发到飞书或模拟环境里。
- `collect`
  回收真实产生的消息，形成 observed data，而不是计划草稿。
- `pre-annotation-validate`
  检查 trap 是否真的落地、消息和 source 是否完整、覆盖度是否达标。
- `optional-adapt`
  只修 observed data 的完整性和覆盖问题，不改 gold 语义。
- `annotation-gold`
  基于最终 `collected_messages` 回标 evidence-bound annotation gold。
- `build-checks`
  生成 `complexity_gate / integrity_gate / eval_manifest` 这些 deterministic 质量门。
- `gold-validate`
  检查 gold、checks 和最终 `collected_messages` 是否一致，不运行 runtime。
- `replay-runtime`
  用真实 `task-events` 和 `task-wiki` runtime 重放消息，生成 prediction。
- `replay-eval`
  把 gold 和 prediction 做 Event / Block / QA 分层比较。
- `memory-md-baseline`
  跑 OpenClaw `Memory.md` baseline，生成同一批 query 的 baseline 回答结果。
- `value-eval`
  比较 `Memory.md`、`raw-message RAG`、`Task Wiki` 三者的离线效果差异。
- `report`
  汇总整个 case 的生成结果、评测结果和 baseline 对比结论。

这里有三个关键约束：

1. `case_spec` 负责提供 `selected_failure_modes / primary_failure_mode`。
2. `failure_mode_selector` 是 `spec-generation` 的内部步骤，不单独落文件，不单独暴露为 CLI 阶段。
3. `memory_failure_blueprint.json` 是第一个正式 artifact。

## 3. 第 0 层：Memory Failure Blueprint 层

### 3.1 为什么需要单独的 blueprint 层

只有 `memory_failure_profile` 还不够。

如果只是写：

```text
selected_failure_modes = ["static_memory_stale_state"]
```

那 builder 仍然可能生成一个“看起来很复杂”的普通故事，而不是一个真正会让 `Memory.md` 失败的 case。

因此 V3 必须先生成：

```text
trap spec
```

再围绕 trap 展开：

- `task_actor_layout`
- `case_world`
- `state_trajectory`
- `coverage_spec`
- `conversation_plan`
- `query_benchmark`

这里要特别澄清：

```text
blueprint 不是 fallback artifact。
```

它不是“失败了再兜底”的东西，而是：

```text
专门定义 Memory.md 会掉进去的 failure trap 的正式控制面。
```

为了避免 `failure-trap` 这个名字听起来像 fallback，V3 正式 artifact 建议命名为：

```text
input/memory_failure_blueprint.json
```

其中内部再包含：

```text
traps[]
```

也就是说，`memory_failure_blueprint` 是整个 V3 case generation 的唯一上游控制面，而 `trap` 是它内部的测试单元。

### 3.1.1 这个阶段的真实实现方式

`memory-failure-blueprint` 不是一个抽象命名，也不是手工拼 schema。

它在工程上应被实现为：

```text
case_spec + builder_settings.yml
-> build_memory_failure_blueprint_prompt()
-> LLM 产出 blueprint JSON
-> schema validate
-> deterministic audit
-> repair / fallback if needed
-> input/memory_failure_blueprint.json
```

这里的“具化”具体指四件事：

1. 把抽象 failure mode 变成具体 trap
   - 哪个 task
   - 哪类污染或状态变化
   - 哪些 probe query
2. 把 trap 变成 typed payload
   - 不同 failure mode 进入不同 payload 结构
3. 把 trap 变成可审计的落地要求
   - `landing_requirements`
4. 把 trap 变成后续生成器的唯一控制面
   - `task_actor_layout`
   - `case_world`
   - `state_trajectory`
   - `conversation_plan`
   - `query_benchmark`

也就是说，这一步本身就是一个正式的 prompt 生成阶段，不是 fallback。

### 3.2 blueprint 的统一结构

建议统一使用：

```json
{
  "trap_id": "trap_finance_claim_001",
  "failure_mode": "unverifiable_summary_claim",
  "target_task_id": "FEISHU-231",
  "trap_mechanism": "把模糊说法和明确事实混在一起，诱发无证据总结。",
  "common": {
    "distractor_tasks": ["FEISHU-291"],
    "shared_actors": ["Alice", "Bob", "Carol"],
    "probe_queries": [
      "现在说 FEISHU-231 被财务问题阻塞，这是谁明确说的？"
    ],
    "metric_targets": [
      "unsupported_claim_rate",
      "evidence_citation_success_rate"
    ],
    "landing_requirements": {
      "required_benchmark_roles": [
        "evidence_anchor_turn",
        "ambiguous_claim_turn",
        "hearsay_turn",
        "ordinary_ack_turn"
      ],
      "required_evidence_messages_min": 4,
      "required_probe_queries_min": 1
    }
  },
  "typed_payload": {
    "target_claim": "FEISHU-231 当前受财务问题阻塞",
    "evidence_distribution": {
      "verified_fact_turns": 2,
      "ambiguous_turns": 2,
      "hearsay_turns": 1,
      "weak_commitment_turns": 1,
      "no_event_turns": 2
    }
  },
  "expected_openclaw_failure": "Memory.md 可能把猜测写成确定事实，且无法回到原始证据。",
  "expected_task_wiki_success": "Task Wiki 应区分 verified / needs_review / no_event，并给出证据引用。"
}
```

### 3.3 四类 typed payload

V3 里必须明确四类 `typed_payload`：

1. `personal_memory_pollution_payload`
2. `unverifiable_summary_claim_payload`
3. `static_memory_stale_state_payload`
4. `dependency_propagation_failure_payload`

推荐约束如下。

`personal_memory_pollution_payload`

- `overlapping_slots`
- `pollution_dimensions`
- `min_distractor_tasks`
- `min_shared_actors`

`unverifiable_summary_claim_payload`

- `target_claim`
- `evidence_distribution`
- `ambiguous_claim_family`

`static_memory_stale_state_payload`

- `required_state_track`
- `stale_states`
- `final_current_state`
- `supersession_edges`

`dependency_propagation_failure_payload`

- `dependency_path`
- `blocking_edge`
- `downstream_effects`

### 3.4 typed payload 的 prompt 改造策略

文档里不能只列 schema，还必须明确 prompt 如何改。

V3 不建议继续使用“一个大 prompt 同时生成所有 failure mode”的方式。  
推荐改成：

```text
shared blueprint system prompt
-> mode-specific blueprint prompt builders
-> 合并为 memory_failure_blueprint.json
```

具体做法：

1. `spec-generation`
   - 只负责确定：
     - `comparison_target`
     - `selected_failure_modes`
     - `primary_failure_mode`
   - 不让 blueprint prompt 自己“发明” failure mode

2. `memory_failure_blueprint_generator`
   - 读取 `case_spec`
   - 对 `selected_failure_modes` 逐个调用 mode-specific prompt builder
   - 每个 mode 至少生成 1 个 trap
   - 最后合并成统一的 `memory_failure_blueprint.json`

建议把生成器内部拆成下面四步：

1. `build_memory_failure_blueprint_prompt()`
   - 组装 shared system prompt 与 mode-specific user prompt
2. `request_blueprint_json()`
   - 调 LLM 获取 blueprint 初稿
3. `validate_memory_failure_blueprint()`
   - 做 schema 校验
4. `audit_and_repair_memory_failure_blueprint()`
   - 做 deterministic audit
   - 不达标时 repair
   - LLM 不可用或 repair 失败时 deterministic fallback

3. prompt 结构
   - `system prompt`
     - 固定说明：你不是在写故事，你是在设计会让 OpenClaw 当前 `Memory.md` 失败的 benchmark trap
     - 输出必须是 JSON
     - 必须满足对应 mode 的 typed payload schema
   - `user prompt`
     - 输入：
       - `case_spec`
       - `selected_failure_modes`
       - `primary_failure_mode`
       - `difficulty`
       - `comparison_target=openclaw_memory_md`
     - 要求输出：
       - 通用字段
       - mode 对应的 `typed_payload`
       - `landing_requirements`
       - `probe_queries`
       - `expected_openclaw_failure`
       - `expected_task_wiki_success`

推荐拆成 4 个 prompt builder。

`build_personal_memory_pollution_blueprint_prompt`

- 强制生成：
  - `target_task_id`
  - `distractor_tasks`
  - `shared_actors`
  - `overlapping_slots`
  - `pollution_dimensions`
  - task-specific probe query
- 明确禁止：
  - 只写状态轨迹而没有污染维度

参考例子：

```text
target task: FEISHU-231 接入方案
distractor task A: PROD-123 新功能上线
distractor task B: FEISHU-312 上线依赖
distractor task C: FEISHU-291 财务审批
shared actors: Alice / Bob / Carol / xzy
```

这个 prompt 应强制模型输出：

```text
为什么同一个人会同时出现在多个任务里；
为什么多个任务会共享负责人、审批状态、截止时间、依赖关系、当前 blocker；
最后要生成什么 query 才能逼出“只看 FEISHU-231，不要混入 PROD-123”的失败。
```

`build_unverifiable_summary_claim_blueprint_prompt`

- 强制生成：
  - `target_claim`
  - `evidence_distribution`
  - `verified_fact_turns`
  - `ambiguous_turns`
  - `hearsay_turns`
  - `weak_commitment_turns`
  - `no_event_turns`
  - 证据敏感型 probe query
- 明确禁止：
  - 把“模糊说法”和“verified fact”混成一个字段

参考例子：

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

这个 prompt 应强制模型输出：

```text
哪个 turn 是 verified fact；
哪个 turn 是 ambiguous / hearsay / ordinary_ack；
probe query 必须要求回答“是谁明确说的？请给原文依据”。
```

`build_static_memory_stale_state_blueprint_prompt`

- 强制生成：
  - `required_state_track`
  - `states`
  - `final_current_state`
  - `stale_states`
  - `supersession_edges`
  - current-state probe query
- 明确禁止：
  - 只有 final state，没有 stale states

参考例子：

```text
t1: FEISHU-231 负责人 Bob
t2: Bob 转给 Alice
t3: Alice 有事，xzy 接手

t1: 截止 4/24
t2: 改到 4/28

t1: 法务审批中
t2: 新增财务问题
t3: 财务未过前不能继续
```

这个 prompt 应强制模型输出：

```text
至少 1 条 owner track；
至少 1 条 deadline 或 blocker track；
每条 track 都要有 initial / update / final_current_state；
必须显式列出 stale_states，不能只给 final state。
```

`build_dependency_propagation_failure_blueprint_prompt`

- 强制生成：
  - `dependency_path`
  - `blocking_edge`
  - `downstream_effects`
  - cross-task / cross-source probe query
- 明确禁止：
  - 只描述单点 blocker，不描述依赖传播后果

参考例子：

```text
FEISHU-231 财务审批未通过
FEISHU-312 依赖 FEISHU-231 完成后上线
FEISHU-291 依赖 FEISHU-231 财务审批通过
```

这个 prompt 应强制模型输出：

```text
哪个是 upstream task；
哪些是 downstream tasks；
当前 blocker 的变化如何影响下游；
probe query 必须问“现在会影响哪些任务”，而不是只问单点状态。
```

建议在实现里保留一个 shared system prompt，再配四个 mode-specific user prompt builder，而不是四个完全独立的 system prompt。这样有两点好处：

1. 所有 trap 都共享同一套 benchmark 原则
2. mode-specific 差异只体现在 typed payload 与 failure mechanism 上

另外还要加一条硬规则：

```text
如果 LLM 不可用，blueprint generator 可以 deterministic fallback 生成 blueprint，
但 fallback 生成的仍然是正式的 memory_failure_blueprint artifact，
不是“备用文件”。
```

shared system prompt 建议至少写清楚下面几条：

```text
你不是在写故事摘要，而是在设计会让 OpenClaw 当前 Memory.md 失败的 benchmark trap。
不要先写剧情再补 failure mode，而是先围绕给定 failure mode 设计 trap。
输出必须是 JSON。
typed_payload 必须满足对应 mode 的字段约束。
probe_queries 必须直接暴露预期的 OpenClaw failure。
landing_requirements 必须可以被 pre-annotation-validator 做 deterministic audit。
```

mode-specific user prompt 则应注入：

1. `case_spec`
2. `comparison_target=openclaw_memory_md`
3. `selected_failure_modes`
4. `primary_failure_mode`
5. `difficulty`
6. 该 mode 对应的示例与禁止项

### 3.5 deterministic audit 规则

LLM 产出的 blueprint 不能直接信任，必须过 deterministic audit。

建议至少检查：

1. `selected_failure_modes` 是否与 `case_spec` 一致
2. `primary_failure_mode` 是否存在于 `selected_failure_modes`
3. 每个 selected mode 是否至少生成 1 个 trap
4. 每个 trap 是否至少有 1 个 `probe_query`
5. 每个 trap 是否有 `landing_requirements`
6. `typed_payload` 是否满足对应 mode 的字段要求
7. `metric_targets` 是否非空
8. `expected_openclaw_failure` 与 `expected_task_wiki_success` 是否存在

如果不达标，处理顺序应为：

```text
schema fail
-> repair prompt
-> revalidate
-> redudit
-> deterministic fallback
```

## 4. builder_settings.yml 的 V3 扩展建议

`builder_settings.yml` 在 V3 里不能只保留当前的 `difficulty_profiles`。  
它至少还需要新增三层控制面：

### 4.1 case 级控制

控制单个 case 至少要长成什么样。

建议新增：

```yaml
v3_blueprint:
  comparison_target_default: openclaw_memory_md
  min_traps_per_case: 3
  max_traps_per_case: 5
  min_probe_queries_per_trap: 1
  primary_failure_mode_required: true
```

### 4.2 failure mode 配比

控制整个数据集层面的 mode 分布。

建议新增：

```yaml
failure_mode_mix:
  personal_memory_pollution: 0.30
  unverifiable_summary_claim: 0.25
  static_memory_stale_state: 0.30
  dependency_propagation_failure: 0.15
```

这里只是数据集层面的配比目标，不足以保证单个 case 合格。

### 4.3 每类 failure mode 的 hard constraints

这层比“比例”更重要，因为它决定单个 case 是否真的构成有效 trap。

建议新增：

```yaml
failure_mode_constraints:
  personal_memory_pollution:
    min_distractor_tasks: 2
    min_shared_actors: 3
    min_overlapping_slots: 3

  unverifiable_summary_claim:
    min_verified_fact_turns: 2
    min_ambiguous_turns: 2
    min_hearsay_turns: 1
    min_weak_commitment_turns: 1
    min_no_event_turns: 2

  static_memory_stale_state:
    min_state_tracks: 2
    min_states_per_track: 3
    min_stale_states: 2
    min_supersession_edges: 2

  dependency_propagation_failure:
    min_downstream_tasks: 2
    min_blocking_edges: 1
    min_dependency_queries: 1
```

### 4.4 difficulty profile 的 V3 扩展

不同难度下，还要约束覆盖度与 trap 强度。

建议在现有 `difficulty_profiles` 基础上扩展：

```yaml
difficulty_profiles:
  medium:
    selected_failure_modes_min: 2
    min_traps_per_case: 2

  hard:
    selected_failure_modes_min: 3
    min_traps_per_case: 3
    require_cross_source_revision: true
```

### 4.5 V3 的结论：比例 + 下限约束

V3 不建议只用“4 类 mode 的比例”。

更稳的做法是：

```text
数据集层面：用 failure_mode_mix 控制占比
单 case 层面：用 failure_mode_constraints 与 difficulty_profiles 控制下限
```

这样既能做全局均衡，也能保证每个 case 真正构成 OpenClaw fail case。

## 5. Artifact 与输入输出边界

### 4.1 正式 artifact contract

V3 保留这些为正式 artifact：

- `case_spec.json`
- `input/memory_failure_blueprint.json`
- `input/task_actor_layout.json`
- `input/case_world.json`
- `input/characters.json`
- `input/actor_registry.json`
- `input/state_trajectory.json`
- `input/conversation_plan.json`
- `input/command_plan.jsonl`
- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`
- `gold/event_annotations.jsonl`
- `gold/block_annotations.json`
- `gold/query_benchmark.json`
- `checks/complexity_gate.json`
- `checks/integrity_gate.json`
- `checks/eval_manifest.json`
- `predictions/*`
- `reports/*`

### 4.2 support artifact 但不是 debug

下面两个文件不属于 gold/prediction，但属于正式 input/support artifact：

- `input/characters.json`
- `input/actor_registry.json`

不要放进 `debug/`，因为：

1. `personal_memory_pollution` 依赖 shared actors。
2. 同一 actor 在多个 task、多个 source 中出现，是 fail case 的关键控制面。
3. 复现实验时必须能看到角色到消息、source、task 的绑定关系。

### 4.3 删除的旧 contract

V3 明确删除：

- `gold/target_state.json`
- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`
- 旧 `target-gold`
- 旧 `gold`
- 旧 `validate`
- 旧 `adapt-case`

## 6. Phase 1：生成 OpenClaw Fail Case

### 5.1 阶段目标

```text
稳定生成会让 Memory.md 失败的数据，并能在 collect 后验证 trap 确实落地。
```

这期只做数据生成，不碰 replay-eval 与 baseline comparison。

### 5.2 本期输出 artifact

- `case_spec.json`
- `input/memory_failure_blueprint.json`
- `input/task_actor_layout.json`
- `input/case_world.json`
- `input/characters.json`
- `input/actor_registry.json`
- `input/state_trajectory.json`
- `input/conversation_plan.json`
- `input/command_plan.jsonl`
- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`
- `checks/pre_annotation_validation_report.json`

### 5.3 本期实现模块

1. `spec_generator.py`
   - 最小输入改为：
     - `comparison_target`
     - `selected_failure_modes`
     - `primary_failure_mode`
   - 不生成 gold hint

2. `failure_mode_selector.py`
   - 只在 `case_spec` 缺失时补默认值
   - 不单独落 artifact

3. `memory_failure_blueprint_generator.py`
   - 生成 trap spec
   - 每个 trap 必须带 `landing_requirements`

4. `task_actor_layout_generator.py`
   - 先生成角色槽位与 task-actor overlap
   - 输出：
     - `target_task`
     - `distractor_tasks`
     - `shared_actor_slots`
     - `pollution_dimensions`

5. `case_world_generator.py`
   - 把 trap 翻译成自然企业协作世界
   - 必须解释：
     - 为什么这些人会讨论
     - 为什么信息会分散
     - 为什么会有模糊表达
     - 为什么旧状态会被修正

6. `character_generator.py`
   - 把 actor slot 实例化成 Alice / Bob / Carol / xzy
   - 生成 `characters.json` 与 `actor_registry.json`

7. `state_trajectory_generator.py`
   - 每个 transition 必须带 `trap_id`
   - 必须支持：
     - `creates_stale_state`
     - `supersedes_transition_id`
     - `is_final_current_state`

8. `coverage_spec_generator.py`
   - 生成 `trap_coverage`
   - 生成 hard gate failure modes / roles / query types

9. `story_beats_generator.py`
   - 每个 beat 必须映射到 trap
   - 区分：
     - `trap beat`
     - `revision beat`
     - `distractor beat`

10. `conversation_plan_generator.py`
   - 固定 turn taxonomy
   - 每个 turn 带：
     - `benchmark_role`
     - `memory_failure_mode`
     - `memory_trap`
     - `expected_openclaw_memory_risk`
     - `task_wiki_expected_handling`

11. `command_plan_generator.py`
   - 删除 `target_state` 依赖
   - 删除 `gold_intent_refs`

12. `collector.py / collected_message_builder.py`
   - 只服务 observed data
   - 产出最终 `collected_messages` 和 `openclaw_message_ingress`

13. `pre_annotation_validator.py`
   - 按 `landing_requirements` 做 deterministic audit
   - 检查：
     - required benchmark roles 是否落地
     - required evidence message 数是否满足
     - required state field 是否出现
     - required probe query 前置证据是否存在

### 5.4 turn taxonomy 的建议枚举

Phase 1 中 `conversation_plan` 推荐固定以下 `benchmark_role`：

- `target_fact_turn`
- `evidence_anchor_turn`
- `stale_state_turn`
- `supersession_turn`
- `final_current_state_turn`
- `distractor_task_turn`
- `shared_actor_turn`
- `memory_pollution_turn`
- `ambiguous_claim_turn`
- `hearsay_turn`
- `weak_commitment_turn`
- `ordinary_ack_turn`
- `context_only_turn`
- `dependency_link_turn`
- `dependency_update_turn`
- `current_state_disambiguation_turn`
- `probe_setup_turn`

其中：

`probe_setup_turn`

- 指对话中的铺垫 turn
- 不等于 query
- 作用是让后续 probe query 有真实上下文可问

### 5.5 本期不做

- `annotation_gold`
- `replay_runtime`
- `event_alignment`
- `block_eval`
- `qa_eval`
- `value_eval`
- `Memory.md baseline runner`

### 5.6 本期验收标准

1. 每个 case 至少成功生成 1 个 `memory_failure_blueprint`
   - 正式落盘到 `input/memory_failure_blueprint.json`
2. 每个 trap 至少成功落地到 `collected_messages`
3. `pre_annotation_validator` 能 deterministic 地判断 trap 是否落地
4. 不再产出任何 `target_state.json / expected_events.jsonl / expected_memory_blocks.json / expected_current_state.json`

## 7. Phase 2：Annotation Gold + Replay Eval

### 6.1 阶段目标

```text
让 Task Wiki runtime 真正可评。
```

### 6.2 本期新增 artifact

- `gold/event_annotations.jsonl`
- `gold/block_annotations.json`
- `gold/query_benchmark.json`
- `checks/complexity_gate.json`
- `checks/integrity_gate.json`
- `checks/eval_manifest.json`
- `reports/event_alignment.json`
- `reports/event_eval.json`
- `reports/block_eval.json`
- `reports/qa_eval.json`
- `reports/overall_eval.json`

### 6.3 本期实现模块

1. `annotation_gold_generator.py`
   - 完全替代旧 `gold_generator.py`
   - 只允许产出 annotation-only gold
   - 严格规则：
     - `benchmark_role / memory_trap` 只能作为 annotation candidate hint
     - 必须重新检查 `collected_messages.text / evidence_quote`
     - 如果文本不支持预期 event，必须降级或报错，不能硬生 positive event

2. `gold_validator.py`
   - 检查 gold 与最终 observed data 的一致性
   - 不运行 runtime

3. `check_builder.py`
   - 产出：
     - `complexity_gate`
     - `integrity_gate`
     - `eval_manifest`

4. `replay_runtime.py`
   - 包装现有 JS runtime：
     - `task-events/session-ingest`
     - `task-events/extractor`
     - `task-wiki/projector`
   - 生成：
     - `candidate_events.jsonl`
     - `session_events.jsonl`
     - `session_wiki_state.json`
     - `task_index_state.json`
     - `task_wiki_state.json`

5. `event_alignment.py`
   - 实现 event-level matching
   - 处理：
     - `exact`
     - `partial`
     - `unmatched`
     - `over_split`
     - `over_merged`

6. `event_evaluator.py`
   - 同时读取 `candidate_events.jsonl` 和 `session_events.jsonl`
   - 评：
     - `verified`
     - `needs_review`
     - `rejected`
     - `no_event`

7. `block_evaluator.py`
   - 依赖 `event_alignment.json`
   - 同时输出：
     - `block_eval_on_all_gold_events`
     - `block_eval_on_aligned_events_only`

8. `qa_evaluator.py`
   - 评 deterministic check + semantic judge
   - `query_benchmark` 中每个 query 必须回到 trap：
     - `source_trap_id`
     - `failure_mode`
     - `expected_openclaw_failure`

### 6.4 本期不做

- `memory_md_baseline_runner`
- `value_eval`

### 6.5 本期验收标准

1. Phase 1 生成的数据能稳定产出 annotation gold
2. replay-runtime 能跑通现有 Task Wiki runtime
3. evaluator 能对 event / block / QA 三层给出结果
4. 所有结果都支持 `by_failure_mode`
5. 仍然不兼容任何 `expected_*` artifact

## 8. Phase 3：Memory.md Baseline + Value Eval

### 7.1 阶段目标

```text
证明 Task Wiki 与 OpenClaw Memory.md 有可比的离线结果。
```

### 7.2 本期新增 artifact

- `reports/value_eval.json`
- `reports/memory_md_baseline_report.json`
- `reports/final_benchmark_report.json`

### 7.3 本期实现模块

1. `memory_md_baseline_runner.py`
   - 明确定义三种模式：
     - `openclaw_compatible`
     - `prompt_simulated`
     - `fixture`
   - 第一版可以先实现 `prompt_simulated` 或 `fixture`
   - 但输出必须标注 baseline mode，防止答辩时混淆“真实 OpenClaw”与“模拟 Memory.md”

2. `value_evaluator.py`
   - 比较：
     - `OpenClaw Memory.md`
     - `raw-message RAG`
     - `Task Wiki`
   - 第一版只做离线可计算指标

3. `report_builder.py`
   - 汇总：
     - event
     - block
     - qa
     - value
     - overall

### 7.4 本期离线指标

Phase 3 第一版固定使用：

- `task_specific_answer_accuracy`
- `irrelevant_memory_pollution_rate`
- `evidence_citation_success_rate`
- `stale_memory_answer_rate`
- `current_state_answer_accuracy`
- `dependency_impact_recall`
- `memory_claim_traceability_rate`
- `memory_scope_purity`

本期不要求：

- `time_to_answer`
- `follow_up_turns`
- `manual_correction_rate`
- `user_satisfaction_score`

这些放到后续 online eval。

### 7.5 本期验收标准

1. `memory_md_baseline_runner` 输入输出 contract 稳定
2. `value_eval.json` 能明确标注 baseline runner mode
3. 能按 `overall / by_failure_mode / by_query_family` 输出三方比较结果
4. 能回答：
   - 哪类 trap 上 `Memory.md` 更容易失败
   - 哪类 trap 上 Task Wiki 通过 evidence / current-state / task isolation 获得提升

## 9. 测试计划

### 8.1 Phase 1 单测

必须新增：

- `test_memory_failure_blueprint.py`
- `test_task_actor_layout.py`
- `test_state_trajectory_v3.py`
- `test_coverage_spec_v3.py`
- `test_pre_annotation_validator.py`

关键断言：

1. `personal_memory_pollution`
   - 一定生成 `target_task + distractor_tasks + shared_actors + pollution_dimensions`
2. `unverifiable_summary_claim`
   - 一定生成 `verified_fact + ambiguous + hearsay + no_event`
3. `static_memory_stale_state`
   - 一定生成 `state_tracks + stale_states + final_current_state`
4. 每个 trap 至少 1 个 `probe_query`
5. 每个 `probe_query` 能回到 `trap_id`
6. `pre_annotation_validator` 按 `landing_requirements` 检查落地

### 8.2 Phase 2 单测

必须新增：

- `test_annotation_gold_generator_v3.py`
- `test_gold_validator_v3.py`
- `test_replay_runtime.py`
- `test_event_alignment_v3.py`
- `test_event_evaluator_v3.py`
- `test_block_evaluator_v3.py`
- `test_qa_evaluator_v3.py`

关键断言：

1. annotation 不能只因 `benchmark_role=negative_turn` 就直接生成 `negative_no_event`
2. 如果 collected text 不支撑预期 event，必须降级或失败
3. `candidate_events` 与 `session_events` 分离评测正确

### 8.3 Phase 3 单测

必须新增：

- `test_memory_md_baseline_runner.py`
- `test_value_evaluator_v3.py`
- `test_report_builder_v3.py`

关键断言：

1. baseline mode 会进入结果报告
2. `memory_claim_traceability_rate` 和 `memory_scope_purity` 能计算
3. `value_eval.json` 能按 `by_failure_mode` 聚合

### 8.4 E2E

三期完成后至少保留三条完整用例：

- `personal_memory_pollution`
- `unverifiable_summary_claim`
- `static_memory_stale_state`

每条 E2E 都要覆盖：

1. trap 生成
2. trap 落地
3. gold 生成
4. replay-runtime
5. layered eval
6. Phase 3 后再覆盖 baseline comparison

## 10. 默认假设

1. 三阶段计划写入新文档 `builder_agent/2026-05-06-feishu_builder_agent-v3-三阶段实施计划.md`
2. 主设计文档不再承载过细的 builder 分期实施细节
3. `failure_mode_selector` 不单独暴露为 CLI 阶段
4. `memory_failure_blueprint.json` 是第一个正式 artifact
5. 旧 builder 不兼容，但执行 / 采集 / runtime 调用底座继续复用
6. Phase 1 先证明“真的能生成 OpenClaw fail 数据”
7. Phase 2 再证明“Task Wiki runtime 真的能被评”
8. Phase 3 最后证明“Task Wiki 和 Memory.md 的离线比较是可成立的”
