# 2026-05-06 feishu_builder_agent V3 当前实现状态

## 1. 文档目标与边界

本文记录 `feishu_builder_agent` V3 当前已经实现到什么程度。

本文是实现状态说明，不替代 V3 规范文档，也不替代三阶段实施计划。

V2 已废弃，当前实现只对应 V3 contract。

本文重点回答：

- 哪些已经可跑
- 哪些是当前已知边界
- 哪些仍是后续收口项

当前实现继续沿用 V3 的固定口径：

- `memory_failure_blueprint.json` 是第一个正式 artifact。
- 正式输出根目录是 `amem_docs/ds/feishu_im_dataset_v3`。
- 不恢复任何 `expected_* / target_state / check golden / adapt-case` 语义。

## 2. V3 总体结论

当前 `feishu_builder_agent` 已经形成 V3 三阶段闭环。

- `已实现`
  - Phase 1 已实现：能生成 `memory_failure_blueprint -> observed data`，并完成 `pre-annotation-validate`。
  - Phase 2 已实现：能生成 annotation-only gold，跑真实 Task Wiki replay runtime，并完成 Event / Block / QA 分层评测。
  - Phase 3 已实现：能产出 `Memory.md` baseline、`raw-message RAG` baseline、`value_eval` 和最终汇总报告。
- `已实现但有已知边界`
  - `Memory.md` baseline 的正式执行路径会先尝试 real OpenClaw query chain；本地环境里若 `memory-core` 查询超时，会显式退化到 `materialized_memory_fallback`，并写入 report。
  - QA semantic judge 在离线环境下会自动退回 heuristic fallback，但 evaluator contract 不变。
- `未保留 / 已删除`
  - 不再保留 `target_state.json`
  - 不再保留 `expected_events.jsonl / expected_memory_blocks.json / expected_current_state.json`
  - 不再保留 `target-gold / gold / validate / adapt-case` 旧 V2 阶段

## 3. 按三阶段看当前已实现内容

### 3.1 Phase 1：已实现内容

Phase 1 当前已经实现 fail-oriented case generation 到 observed data 的完整控制面。

- `spec-generation`
  已支持 `comparison_target / selected_failure_modes / primary_failure_mode`
- `case_spec` identity
  `task_id / case_id` 当前由 system-owned deterministic control 生成；LLM 只参与 failure mode 选择，不参与 case identity 命名
- `memory-failure-blueprint`
  已有正式生成器、schema validate、audit/repair、四类 typed payload
- `task-actor-layout`
  已生成 `target_task / distractor_tasks / shared_actor_slots / pollution_dimensions`
- `case-world / characters / state-trajectory / conversation-plan / command-plan`
  已全部落地并进入 CLI
- `execute / collect / pre-annotation-validate`
  已可跑，observed data contract 已稳定
- `case_manifest.json`
  已引入，作为阶段推进与 artifact 路径的统一状态文件

这里有一个已经完成的 contract 收口：

- `case_spec.json` 已不再落 `title_hint / main_goal_hint / scenario_profile / department_hints` 这类故事提示字段
- `memory_failure_blueprint.json` 继续作为唯一正式上游控制面
- `coverage_spec.json` 与 `story_beats.json` 已从正式 input control plane 降级，不再要求作为 Phase 1/2/3 的正式前置输入

当前 Phase 1 正式 artifact 已落地为：

```text
case_spec.json
case_manifest.json

input/
  memory_failure_blueprint.json
  task_actor_layout.json
  case_world.json
  characters.json
  actor_registry.json
  state_trajectory.json
  conversation_plan.json
  command_plan.jsonl

data/
  collected_messages.jsonl
  openclaw_message_ingress.jsonl

checks/
  pre_annotation_validation_report.json
```

当前 Phase 1 的正式 input 关联关系已经收口为：

```text
case_spec
-> memory_failure_blueprint
-> task_actor_layout
-> case_world
-> characters
-> state_trajectory
-> conversation_plan
-> command_plan
```

### 3.2 Phase 2：已实现内容

Phase 2 当前已经实现 annotation gold、真实 replay runtime 和分层 evaluator。

#### Gold

- `annotation_gold_generator.py` 已实现
- 只生成：
  - `gold/event_annotations.jsonl`
  - `gold/block_annotations.json`
  - `gold/query_benchmark.json`
- `event_annotations` 已统一为：
  - `positive_event`
  - `negative_no_event`
  - `review_event`
- `expected_verdict` 已统一支持：
  - `verified`
  - `needs_review`
  - `rejected`
  - `no_event`

#### Runtime

- `replay_runtime.py` 已实现
- 已包装真实 Task Wiki runtime 接口
- 当前 replay-runtime 的 event ingestion 主链已经收口为：
  `session-ingest(write-only) -> pending_ingests/evidence_spans -> batch drain extraction -> candidate_events -> verification -> session_events -> projector`
- 当前 replay 输出为：
  - `predictions/candidate_events.jsonl`
  - `predictions/session_events.jsonl`
  - `predictions/session_wiki_state.json`
  - `predictions/task_index_state.json`
  - `predictions/task_wiki_state.json`

#### Eval

- `event_alignment.py` 已实现
- `event_evaluator.py` 已实现
- `block_evaluator.py` 已实现
- `qa_evaluator.py` 已实现
- `qa_evaluator` 已支持 deterministic checks + semantic judge 双层判断
- 所有结果都支持 `by_failure_mode`

当前 Phase 2 已有的正式报告包括：

```text
reports/
  event_alignment.json
  event_eval.json
  block_eval.json
  qa_eval.json
```

这里有一个明确的工程边界：

- semantic judge 在离线环境下已做熔断；首次 live LLM 失败后，本轮后续 query 直接走 heuristic fallback，不会持续重复外网失败请求。

### 3.3 Phase 3：已实现内容

Phase 3 当前已经实现三方 baseline comparison、value eval 和最终汇总报告。

- `memory_md_baseline_runner.py` 已实现
- `raw_message_rag_runner.py` 已实现
- `value_evaluator.py` 已实现
- `report_builder.py` 已实现

当前 report 语义已经固定：

- `baseline_mode`
  固定写 `openclaw_real`
- `runner_attempt`
  表示先尝试的真实 baseline 路径
- `runner_backend`
  表示最终实际使用的 backend
- `fallback_reason`
  在真实链路失败时给出原因
- `value_eval.json`
  已支持：
  - `overall`
  - `by_failure_mode`
  - `by_query_family`

当前 Phase 3 已有的正式报告包括：

```text
reports/
  memory_md_baseline_report.json
  value_eval.json
  overall_eval.json
  final_benchmark_report.json
```

这里需要明确当前已知边界：

- 当前代码会优先尝试真实 OpenClaw `Memory.md` query chain。
- 在本地环境下，这条链路可能卡在 `memory-core` 查询初始化或 manager 获取阶段。
- 失败后不会静默伪装成 real success，而是显式退回 `materialized_memory_fallback`，并在报告中记录。

## 4. 当前 CLI / 测试覆盖状态

### 4.1 CLI 已支持

- `compile-case-phase1`
- `compile-case-phase2`
- `compile-case-phase3`
- `annotation-gold`
- `build-checks`
- `gold-validate`
- `replay-runtime`
- `replay-eval`
- `memory-md-baseline`
- `value-eval`
- `report`

### 4.2 测试已覆盖

- Phase 1 单测
- Phase 2 单测
- Phase 3 单测
- E2E 覆盖至少三类 case family

当前 `python3 -m unittest discover -s feishu_builder_agent/tests -p 'test_*.py'` 已通过，作为“当前实现状态”的验证依据。

## 5. 重要接口与类型

当前 V3 的正式接口面已经固定在以下几类 artifact 上。

- `case_manifest.json`
  统一记录 completed stages 和 artifact paths
- `gold/event_annotations.jsonl`
  三类 annotation record + `expected_verdict`
- `predictions/*`
  真实 replay runtime prediction contract
- `pending_ingests.jsonl / evidence_spans.jsonl`
  当前 replay-runtime 前半段的正式中间层，负责承载 write-only ingest 后的 dirty span 与 batch extraction 输入
- `reports/event_eval.json / block_eval.json / qa_eval.json / value_eval.json / overall_eval.json / final_benchmark_report.json`
  当前 V3 正式报告集合
- `reports/memory_md_baseline_report.json`
  新增 `runner_attempt / runner_backend / fallback_reason`

## 6. 当前已验收结论

当前实现状态下，V3 三阶段可以按下面的验收口径理解：

- Phase 1：能生成 fail-oriented case control plane 与 observed data
- Phase 2：能生成 annotation-only gold，并跑通 replay runtime 与三层评测
- Phase 3：能生成 baseline comparison 和最终 report
- 全量 Python 单测已通过
- 当前剩余边界已在 baseline report 中显式暴露，不是静默失败

## 7. 已知边界与下一步收口项

当前真正还没有完全收口的点主要有三类。

1. 真实 `Memory.md` baseline 仍存在 fallback 语义
   - 方向正确，但本地真实 query chain 还需继续收口
2. semantic judge 目前在离线环境中有 heuristic fallback
   - contract 已稳定，但 live judge 结果取决于外部模型可用性
3. Phase 3 当前是“功能完成、真实 baseline 仍有环境边界”
   - 这应被视为当前实现状态的一部分，而不是隐藏细节

当前可以给出一个固定判断：

- 从 builder contract、artifact contract、CLI 流程和分层评测角度看，V3 三阶段已经实现闭环；
- 当前剩余问题主要集中在真实 OpenClaw `Memory.md` baseline 的运行时稳定性，而不是 V2/V3 设计边界未完成。

## 8. 默认假设

- 采用“新建状态文档”，不改写现有 V3 三阶段实施计划主文。
- 文风继续沿用 `builder_agent` 下 V3 计划文档：中文技术设计风格、工程边界优先、少空话。
- 文档重点写“已实现状态”，不是再重复一遍完整规范。
- “真实 baseline 存在 fallback 边界”已写入正文，不做弱化处理。
