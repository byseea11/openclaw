# 2026-05-06 feishu_builder_agent V3 Prompt 与流程整理

## 1. 文档目标与边界

本文整理 `feishu_builder_agent` V3 当前真实流程，以及 builder prompt 的分布现状与后续收口边界。

本文不是主设计文档，也不替代三阶段实施计划；它只回答两个实现问题：

1. V3 现在到底哪些阶段需要 LLM，哪些阶段不需要。
2. 当前 prompt 集中在什么位置，后续还准备如何继续管理。

当前固定事实如下：

- 当前 `feishu_builder_agent/prompts/` 不是正式的 V3 prompt registry，目录目前为空。
- 当前 V3 的 builder creative prompt 已全部收口到 `feishu_builder_agent/prompt_registry.py`。
- `llm_mode=llm` 表示该阶段成功拿到 live LLM 结果。
- `llm_mode=fallback` 表示该阶段支持 live LLM，但本次运行没有成功拿到 live 结果，因此退回 fallback。
- `--require-live-llm` 已经在 `amem_docs/scripts/feishu-builder-agent-run.sh` 的 help 中暴露，用来要求所有可生成阶段必须使用 live LLM，否则直接失败。

这里要固定一个实现判断：

- V3 不是“所有阶段都该由 LLM 生成”。
- V3 只有 creative control plane 需要 LLM；其余阶段保持 `derived / runtime / deterministic` 更稳，也更容易保证可评测性。

## 2. V3 当前真实流程

V3 当前正式流程可以分成四类阶段：

- `LLM-generated`
  负责生成 failure-oriented control plane 中需要自然语言表达、trap realization 或企业协作合理性的部分。
- `derived`
  负责从已有 control plane 机械推导结构，不依赖创造性生成。
- `runtime`
  负责真实执行、回放或 baseline 查询。
- `deterministic`
  负责校验、评测、汇总，不应再引入新的 case 语义。

当前流程链如下：

```text
spec-generation [LLM]
-> memory-failure-blueprint [LLM]
-> task-actor-layout [derived]
-> case-world [LLM]
-> characters [LLM]
-> state-trajectory [derived]
-> conversation-plan [LLM]
-> command-plan [derived]
-> execute [runtime]
-> collect [runtime]
-> pre-annotation-validate [deterministic]
-> annotation-gold [deterministic]
-> build-checks [deterministic]
-> gold-validate [deterministic]
-> replay-runtime [runtime]
-> replay-eval [deterministic + judge]
-> memory-md-baseline [runtime]
-> value-eval [deterministic]
-> report [deterministic]
```

每一步的职责固定如下：

- `spec-generation`：生成最小 `case_spec.json`，决定这个 case 比谁、测哪些 failure mode，是后续所有生成阶段的控制起点。
- `memory-failure-blueprint`：生成 `memory_failure_blueprint.json`，把 failure mode 具体化成 trap、probe query 和 landing requirement。
- `task-actor-layout`：生成 `task_actor_layout.json`，定义 target task、distractor task 和 shared actor 的结构边界。
- `case-world`：生成 `case_world.json`，把 trap 翻译成自然企业协作背景。
- `characters`：生成 `characters.json` 和 `actor_registry.json`，把角色槽位实例化为真实协作者。
- `state-trajectory`：生成 `state_trajectory.json`，定义 current-state、stale-state 和 supersession 的状态演进。
- `conversation-plan`：生成 `conversation_plan.json`，把 trap 和状态轨迹落到 session、turn 和 benchmark_role。
- `command-plan`：生成 `command_plan.jsonl`，把对话计划转成可执行动作。
- `execute`：执行动作计划，把 planned turn 落成真实消息动作。
- `collect`：生成 `collected_messages.jsonl` 和 `openclaw_message_ingress.jsonl`，形成 observed data。
- `pre-annotation-validate`：生成 `pre_annotation_validation_report.json`，检查 trap 是否真的落地。
- `annotation-gold`：生成 annotation-only gold，作为 replay-eval 的比较基准。
- `build-checks`：生成 deterministic quality gate，约束 eval 入口质量。
- `gold-validate`：验证 gold 与最终 observed data 的一致性。
- `replay-runtime`：先走 `session-ingest(write-only)` 写入 `pending_ingests/evidence_spans`，再通过 batch drain 产出 `candidate_events / session_events` 并投影出 wiki 状态。
- `replay-eval`：生成 Event、Block、QA 分层评测结果，判断“记住了没有”。
- `memory-md-baseline`：生成 OpenClaw `Memory.md` baseline 回答，提供对照系统。
- `value-eval`：生成三方 baseline comparison，判断“有没有实际效能提升”。
- `report`：汇总最终 benchmark 结论。

这里需要特别澄清为什么 `spec-generation` 也需要 LLM：

- 它不是简单填默认值。
- 它负责生成 case 级别的 failure-oriented seed，包括 `selected_failure_modes` 与 `primary_failure_mode` 的自然组合。
- 它仍然保留 fallback，是为了保证离线环境下可以继续调试 V3 pipeline，而不是为了弱化 live LLM 路径。

## 3. 当前文件与作用表

下面只按“文件 -> 一句话作用”记录当前关键实现面。

- `feishu_builder_agent/spec_generator.py`：生成 `case_spec.json`，决定 case 的 failure-oriented 控制字段。
- `feishu_builder_agent/memory_failure_blueprint_generator.py`：生成 `memory_failure_blueprint.json`，定义四类 fail trap 的正式控制面。
- `feishu_builder_agent/task_actor_layout_generator.py`：生成 `task_actor_layout.json`，约束任务、干扰任务和共享角色的结构关系。
- `feishu_builder_agent/case_world_generator.py`：生成 `case_world.json`，把 trap 变成合理的企业协作背景。
- `feishu_builder_agent/character_generator.py`：生成 `characters.json`，把角色槽位实例化为具体人物。
- `feishu_builder_agent/actor_registry.py`：生成 `actor_registry.json`，把人物映射成稳定的 actor registry 供执行和 collect 使用。
- `feishu_builder_agent/state_trajectory_generator.py`：生成 `state_trajectory.json`，定义状态变化和 supersession 轨迹。
- `feishu_builder_agent/conversation_plan_generator.py`：生成 `conversation_plan.json`，把 trap 落到消息级 turn 设计。
- `feishu_builder_agent/command_plan_generator.py`：生成 `command_plan.jsonl`，把 turn 变成可执行动作序列。
- `feishu_builder_agent/executor.py`：消费 `command_plan`，执行动作并产出执行结果。
- `feishu_builder_agent/collector.py`：消费执行结果，回收真实消息并形成 observed data。
- `feishu_builder_agent/pre_annotation_validator.py`：消费 blueprint、conversation plan 和 collected messages，输出 trap 落地审计。
- `feishu_builder_agent/annotation_gold_generator.py`：基于最终 observed data 生成 annotation-only gold。
- `feishu_builder_agent/check_builder.py`：基于 case 目录生成 `complexity_gate / integrity_gate / eval_manifest`，约束 eval 入口质量。
- `feishu_builder_agent/gold_validator.py`：检查 gold 与最终 observed data 的 evidence 引用是否一致。
- `feishu_builder_agent/replay_runtime.py`：调用真实 Task Wiki runtime，生成 `predictions/*`。
- `extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js`：把消息写入 source session，并维护 `pending_ingests / evidence_spans` 这两层 batch extraction 中间状态。
- `feishu_builder_agent/event_alignment.py`：把 gold event 和 runtime prediction 做 evidence / claim 对齐。
- `feishu_builder_agent/event_evaluator.py`：输出 event 层指标，判断 `verified / needs_review / rejected / no_event` 表现。
- `feishu_builder_agent/block_evaluator.py`：输出 block/current-state 层指标，区分 extractor failure 和 projector failure。
- `feishu_builder_agent/qa_evaluator.py`：输出 query 层指标，判断回答是否 faithful、有 citation、是否 stale。
- `feishu_builder_agent/memory_md_baseline_runner.py`：生成 OpenClaw `Memory.md` baseline 结果。
- `feishu_builder_agent/raw_message_rag_runner.py`：生成 raw-message RAG baseline 结果。
- `feishu_builder_agent/value_evaluator.py`：输出三方 baseline comparison，判断 Task Wiki 是否有实际效能提升。
- `feishu_builder_agent/report_builder.py`：汇总所有 report，形成最终 benchmark 总结。
- `feishu_builder_agent/case_manifest.py`：统一维护当前 case 的阶段完成情况与 artifact 路径。
- `feishu_builder_agent/cli.py`：把上述阶段暴露成 CLI 和 `compile-case-phase1/2/3` 总入口。
- `amem_docs/scripts/feishu-builder-agent-run.sh`：把 CLI 编排成 V3 runner，支持 `full`、`--require-live-llm` 和 run log。

这里要单独固定一句最终结论：

- 当前 builder prompt 的唯一正式集中管理面是 `feishu_builder_agent/prompt_registry.py`。

## 4. 当前 Prompt Inventory

当前真正承载 builder live prompt 的位置，已经统一收口到 `feishu_builder_agent/prompt_registry.py`。

### 4.1 当前已由 `prompt_registry.py` 提供的 prompt

- `feishu_builder_agent/spec_generator.py`
  - prompt 作用：生成最小 `case_spec`
  - 当前状态：prompt 已迁移到 `feishu_builder_agent/prompt_registry.py`，生成器只负责 normalize、validate 和 fallback
- `feishu_builder_agent/memory_failure_blueprint_generator.py`
  - prompt 作用：生成四类 failure trap blueprint
  - 当前状态：prompt 已迁移到 `feishu_builder_agent/prompt_registry.py`，生成器只负责校验、审计和 fallback
- `feishu_builder_agent/case_world_generator.py`
  - prompt 作用：把 trap 翻译成自然业务背景
  - 当前状态：prompt 已迁移到 `feishu_builder_agent/prompt_registry.py`，生成器只负责 merge、validate 和 fallback
- `feishu_builder_agent/character_generator.py`
  - prompt 作用：生成更自然的人名和 profile
  - 当前状态：prompt 已迁移到 `feishu_builder_agent/prompt_registry.py`，生成器只负责 scaffold merge、validate 和 fallback
- `feishu_builder_agent/conversation_plan_generator.py`
  - prompt 作用：把 trap 和 `state_trajectory` 翻译成真实企业消息口径
  - 当前状态：prompt 已迁移到 `feishu_builder_agent/prompt_registry.py`，生成器只负责 scaffold、validate 和 fallback

### 4.2 不使用 builder prompt 的阶段

- `feishu_builder_agent/task_actor_layout_generator.py`
  - prompt 作用：无 prompt
  - 当前状态：属于 derived 阶段，从 blueprint 机械生成结构布局
- `feishu_builder_agent/state_trajectory_generator.py`
  - prompt 作用：无 prompt
  - 当前状态：属于 derived 阶段，从 blueprint、layout 和 world 推导状态轨迹
- `feishu_builder_agent/command_plan_generator.py`
  - prompt 作用：无 prompt
  - 当前状态：属于 derived 阶段，把 `conversation_plan` 转成可执行动作

当前必须固定三句结论：

- 当前 prompt 没有集中在 `feishu_builder_agent/prompts/`。
- 当前 builder creative prompt 已经集中到单一 Python registry。
- 当前 builder prompt 的唯一正式集中管理面是 `feishu_builder_agent/prompt_registry.py`。

## 5. 为什么还需要 LLM

V3 当前不是所有阶段都需要 LLM，但 creative control plane 仍然需要 LLM。

需要 LLM 的阶段有两个共同特征：

1. 需要把结构化 trap 翻译成像真实企业协作那样自然的表达。
2. 需要在多 source、多角色、多回合条件下，让 failure trap 既真实又稳定落地。

因此：

- `spec-generation`
  需要 LLM 来生成更自然的 failure-mode 组合，而不是每次只靠固定模板硬拼。
  但 `task_id / case_id` 当前由系统按 seed 生成，LLM 不参与 case identity 决策。
- `memory-failure-blueprint`
  需要 LLM 来把抽象 failure mode 展开成更合理的 trap、query 和 landing requirement。
- `case-world`
  需要 LLM 来解释为什么这些信息会分散、为什么会有模糊说法、为什么旧状态会被修正。
- `characters`
  需要 LLM 来让协作者名字和 profile 更自然，而不是只用占位槽位。
- `conversation-plan`
  需要 LLM 来让消息口径、线程结构和说话方式更像真实企业沟通。

不需要 LLM 的阶段也有共同特征：

1. 目标是保持结构一致性。
2. 目标是保持可执行性。
3. 目标是保持可评测性。

因此像 `task-actor-layout`、`state-trajectory`、`command-plan`、`annotation-gold`、`build-checks`、`value-eval` 这类阶段，用 `derived / deterministic` 更稳，不应该再混入新的生成性语义。

## 6. Prompt 收口方案：单一 Python 文件优先

当前 V3 builder prompt 的正式收口目标已经落地为：

```text
feishu_builder_agent/prompt_registry.py
```

这个文件当前的职责如下：

- 集中定义所有 V3 builder prompt。
- 暴露统一的 builder 接口，而不是让每个生成器各自拼 `system_prompt / user_prompt`。
- 统一管理 mode-specific prompt，避免四类 failure mode 的 prompt 再继续散落。

当前推荐并已经使用的接口为：

- `build_spec_generation_prompts(...)`
- `build_memory_failure_blueprint_prompts(...)`
- `build_case_world_prompts(...)`
- `build_character_prompts(...)`
- `build_conversation_plan_prompts(...)`

每类接口统一返回：

- `system_prompt`
- `user_prompt`

这里要明确职责分工：

- `prompt_registry.py` 负责：
  - prompt 文本组织
  - mode-specific prompt 选择
  - 统一 prompt 构造接口
- 各生成器继续负责：
  - schema normalize
  - validator
  - audit / repair
  - fallback policy

当前已经落地的结果是：

- `spec-generation / memory_failure_blueprint / case-world / characters / conversation-plan` 已经全部改为通过 `prompt_registry.py` 提供 prompt；
- `task_id / case_id` 属于 system-owned deterministic control fields，即使 `spec-generation` prompt 输出这两个字段，最终也会被系统侧规范化覆盖；
- 生成器继续保留业务逻辑，不会因为收口 prompt 而丢失当前 V3 的校验和 fallback 机制。

## 7. 收口后的边界

V3 builder creative prompt 的收口已经完成，但仍然有明确边界：

- `prompt_registry.py` 当前只承接 builder creative prompt。
- validator、audit、repair 和 fallback 逻辑仍然留在各生成器里。
- 后续如果继续扩展，不应把 evaluator 或 runtime 语义混进这个 registry。
- 当前不需要把 registry 再拆成多个 `.txt` 文件或目录化模板。

## 8. 验收标准

这份文档完成后，必须能直接回答下面这些问题：

1. 当前哪些阶段真的用 LLM。
2. 为什么 `spec-generation` 会出现 `llm_mode=llm`。
3. 为什么 `command-plan` 不需要 LLM。
4. prompt 现在是不是集中在一个地方。
5. 当前集中到了哪个文件。
6. `--require-live-llm` 是否已经暴露在 runner script help 里。

当前这份文档给出的答案是：

- 用 LLM 的是 `spec-generation / memory-failure-blueprint / case-world / characters / conversation-plan`。
- `spec-generation` 出现 `llm_mode=llm`，是因为它现在已经走 live LLM prompt，而不是纯默认值填充。
- `command-plan` 不需要 LLM，因为它只负责把 `conversation_plan` 机械翻译成动作序列。
- prompt 现在已经集中到 `feishu_builder_agent/prompt_registry.py`。
- 当前 builder prompt 的唯一正式集中管理面是 `feishu_builder_agent/prompt_registry.py`。
- `--require-live-llm` 已经暴露在 `amem_docs/scripts/feishu-builder-agent-run.sh` help 里。

## 9. 默认假设

- `prompt_registry.py` 已经实现并承接全部 builder creative prompt。
- 文档放在 `builder_agent` 目录，不塞回主设计文档正文。
- 默认采用“单一 Python registry 文件”作为 prompt 收口目标，不以多文本文件目录作为第一方案。
- 文档里直接承认 `feishu_builder_agent/prompts/` 当前不是正式 prompt registry，不弱化这个现状。
