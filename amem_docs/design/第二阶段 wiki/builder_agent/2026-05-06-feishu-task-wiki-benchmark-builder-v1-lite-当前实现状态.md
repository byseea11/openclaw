# 2026-05-06 Feishu Task Wiki Benchmark Builder V1-Lite 当前实现状态

## 1. 文档目标与边界

本文记录当前仓库里已经落地的 `feishu_task_wiki_benchmark_builder/` 实现状态。

这份文档对应的是新的 hard-break builder 实现，不再对应旧的 `feishu_builder_agent/`。

本文重点回答：

- 当前已经实现了什么
- 当前正式口径是什么
- 当前有哪些 artifact 和阶段
- 当前代码、skill、docs 的边界如何划分
- 当前已经验证到什么程度
- 当前还剩哪些明确边界

## 2. 当前实现的总体结论

当前实现已经不是旧的 V3 `memory_failure_blueprint` 路线，而是新的 V1-Lite family-first 路线。

- `已实现`
  - 新包已经切换到 `feishu_task_wiki_benchmark_builder/`
  - 正式 family 已收成 3 类比赛口径
  - `story_plan.json` 已成为唯一核心中间 artifact
  - Phase 1 / Phase 2 / Phase 3 三阶段闭环已经可跑
  - `.agents/skills/` 触发壳、代码侧 `skills/`、代码侧 `prompt.py`、human docs 四层分工已经落地
- `已删除 / 不再保留`
  - 不再保留旧 `feishu_builder_agent/`
  - 不再保留 `memory_failure_blueprint.json`
  - 不再保留 `task_actor_layout.json`、`state_trajectory.json`、`probe_targets.json`、`memory_case_contract.json` 这些正式独立 artifact
  - 不再保留旧四类 formal family id
- `当前固定口径`
  - 正式 family 只有：
    - `anti_interference`
    - `contradiction_update`
    - `evidence_dependency_reasoning`
  - `效能指标验证` 继续保留为跨 family 的最终评测维度，不是 formal family

## 3. 当前正式架构

### 3.1 四层分工

当前 builder 采用四层分工：

- `.agents/skills/feishu-task-wiki-benchmark-builder/`
  - 只负责 trigger shell
- `feishu_task_wiki_benchmark_builder/skills/`
  - 代码目录下的 machine guidance
- `feishu_task_wiki_benchmark_builder/prompt.py`
  - 运行时 system prompt source
- `feishu_task_wiki_benchmark_builder/docs/`
  - 给人看的说明文档

这里的固定边界已经很明确：

- 真正给模型看的 builder skill 内容在 `feishu_task_wiki_benchmark_builder/skills/`
- runtime prompt 不再从 markdown 读取，而是直接来自 `prompt.py`
- `docs/` 不再承担 runtime prompt source 或 machine skill source

### 3.2 当前正式比赛 family

当前 formal family 已固定为三类：

#### 1. `anti_interference`

- 对应项目需求：抗干扰测试
- 关注点：共享角色、相似任务、噪音上下文下的精准回忆

#### 2. `contradiction_update`

- 对应项目需求：矛盾更新测试
- 关注点：时序覆盖、current vs historical、旧口径作废

#### 3. `evidence_dependency_reasoning`

- 对应项目需求与 benchmark 口径：
  - 证据验证结果
  - 企业任务网络 / 依赖传播验证
- 关注点：
  - 谁的说法是可信证据
  - 该证据如何定义真实 blocker
  - 该 blocker 如何影响目标任务和下游任务

### 3.3 `family_catalog.py` 的当前角色

当前 `feishu_task_wiki_benchmark_builder/family_catalog.py` 已是正式机器语义源，而不只是展示层文本。

它当前会直接驱动：

- `memory_capability_brief.json`
- `case_world`
- `story_plan`
- 最终 benchmark report 的比赛口径映射

当前 `FamilyDefinition` 已显式包含比赛映射字段：

- `benchmark_requirement_name`
- `benchmark_requirement_summary`
- `report_display_name`

也就是说：

- 比赛口径映射不是只写在文档里
- 它已经进入代码 contract，并会进入 downstream artifact

## 4. 按三阶段看当前已实现内容

### 4.1 Phase 1：已实现内容

当前 Phase 1 固定为：

```text
dataset-plan
-> family-selection
-> memory-capability-brief
-> case-spec
-> case-world
-> story-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
```

当前已经落地：

- `dataset-plan`
  - 生成 `dataset_generation_plan.json`
- `family-selection`
  - single case 支持 seed deterministic 选择
  - batch 支持 family quota
- `memory-capability-brief`
  - 直接由 `family_catalog.py` 生成
  - 已包含比赛映射字段
- `case-spec`
  - 只保留控制字段
- `case-world`
  - 已按 3 类 family 提供模板化 business context
- `story-plan`
  - 已成为唯一核心中间 artifact
  - 统一承载：
    - `tasks`
    - `actors`
    - `task_actor_layout`
    - `state_changes`
    - `message_beats`
    - `planned_probe_queries`
- `command-plan`
  - 已把 story plan 映射成执行动作
- `execute / collect`
  - 已产出 observed messages 和 openclaw ingress
- `pre-annotation-validate`
  - 已作为 collect 后的 observed-side gate 落地

当前 Phase 1 正式 artifact 为：

```text
dataset_generation_plan.json

case_spec.json

input/
  family_selection.json
  memory_capability_brief.json
  case_world.json
  story_plan.json
  command_plan.jsonl

runtime/
  executed_commands.jsonl

data/
  collected_messages.jsonl
  openclaw_message_ingress.jsonl

checks/
  pre_annotation_validation_report.json
```

### 4.2 Phase 2：已实现内容

当前 Phase 2 固定为：

```text
annotation-gold
-> query-benchmark
-> replay-eval
```

当前已经落地：

- `annotation-gold`
  - 基于 collected messages 回标 observed events
- `query-benchmark`
  - 从 `planned_probe_queries` 收口成正式 query
- `replay-eval`
  - 生成 Task Wiki replay 评测结果

当前 Phase 2 正式 artifact 为：

```text
gold/
  annotation_gold.jsonl
  query_benchmark.json

reports/
  replay_eval.json
```

### 4.3 Phase 3：已实现内容

当前 Phase 3 固定为：

```text
baseline-eval
-> value-eval
-> benchmark-report
```

当前已经落地：

- `baseline-eval`
  - 当前固定 baseline mode：
    - `openclaw_memory_md`
    - `raw_message_rag`
    - `task_wiki`
- `value-eval`
  - 对比 Task Wiki 相对 baseline 的 query success uplift
- `benchmark-report`
  - 当前会显式输出 `Project Requirement Mapping`
  - 直接消费 `memory_capability_brief` 中的比赛映射字段

当前 Phase 3 正式 artifact 为：

```text
reports/
  baseline_eval.json
  value_eval.json
  final_benchmark_report.md
```

## 5. 当前三类 family 的实现重点

### 5.1 `anti_interference`

当前 story builder 重点落在：

- `task_actor_layout`
- `planned_probe_queries`

当前 case 结构要求：

- 1 个 target task
- 至少 2 个 distractor tasks
- shared actors
- 需要 scope boundary 判断的 query

### 5.2 `contradiction_update`

当前 story builder 重点落在：

- `state_changes`
- `planned_probe_queries`

当前 case 结构要求：

- 多轮状态更新
- `initial / historical / current`
- 需要 stale distinction 的 query

### 5.3 `evidence_dependency_reasoning`

这是当前新合并出来的第三类。

当前 story builder 已要求同一条 case 同时落地：

- verified / hearsay / ambiguous 证据强弱差异
- upstream task / target task / downstream task
- 真实 blocker 的证据归因
- upstream -> target -> downstream 的影响链

也就是说，第三类不是“证据验证”和“依赖传播”并列展示，而是合成成一类正式测试目标：

- 先判断哪条消息可信
- 再用可信证据解释依赖传播

## 6. 当前 CLI、脚本与验证状态

### 6.1 当前 CLI

当前 `feishu_task_wiki_benchmark_builder/cli.py` 已支持：

- `dataset-plan`
- `phase1`
- `phase2`
- `phase3`
- `build-all`

### 6.2 当前 runner 脚本

当前 runner 为：

- `amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh`

脚本帮助文案已经同步到 3 类正式 family：

- `anti_interference`
- `contradiction_update`
- `evidence_dependency_reasoning`

并明确说明：

- `效能指标验证` 不是 formal family
- 它属于最终 report 的横向评测维度

### 6.3 当前已跑验证

当前实现状态已经验证过：

- `python3 -m unittest discover -s feishu_task_wiki_benchmark_builder/tests -p 'test_*.py'`
  - 当前结果：`20 tests OK`
- `bash -n amem_docs/scripts/feishu-task-wiki-benchmark-builder-run.sh`
  - 当前结果：通过
- 三个正式 family 的 `build-all` 贯通：
  - `anti_interference`
  - `contradiction_update`
  - `evidence_dependency_reasoning`

这意味着：

- 新的 3-family contract 已经进入代码、docs、skills、runner 和 tests
- 当前实现不是只改了文案，而是已经完成代码路径切换

## 7. 当前实现的已知边界

当前这版已经可跑，但还有几个明确边界需要知道。

### 7.1 当前 Phase 1 仍然是模板化生成，不是 LLM-heavy generation

虽然架构上保留了 `skills/` 和 `prompt.py`，但当前 `case_world`、`story_plan` 等阶段主要还是 deterministic / template-first 实现。

也就是说：

- 机器 guidance 和 prompt 层已经摆正
- 但内容生成还没有真的完全切到 LLM-native builder

### 7.2 Phase 2 / Phase 3 当前仍然偏轻量 mock 评测

当前：

- `replay_eval` 是轻量固定结果骨架
- `baseline_eval` 也是当前实现内的 mock-style penalty 模型

因此这版的价值主要是：

- 固定新的 builder contract
- 固定比赛口径
- 固定三阶段 artifact 与数据流

而不是说明 replay / baseline 已经完全等价于真实生产评测系统。

### 7.3 数据集与旧样例还没有统一迁到新 contract

当前 builder 主路径已经切到新 contract，但历史 `amem_docs/ds/feishu_im_dataset_v3` 里的旧样例并不等于都已经迁移成当前 3-family 正式语义。

所以这份文档描述的是：

- 当前代码实现状态

不等于：

- 所有历史样例都已经按当前口径重新整理完成

## 8. 当前结论

如果按“当前仓库已经实现了什么”来总结，可以归纳为：

- 旧 `feishu_builder_agent` 已废弃
- 当前正式实现是 `feishu_task_wiki_benchmark_builder/`
- 当前正式比赛 family 已固定为 3 类
- `story_plan.json` 已成为唯一核心中间 artifact
- `family_catalog.py` 已成为比赛口径的机器语义源
- Phase 1 / 2 / 3 已可跑通
- docs、skills、prompt、runner、tests 已对齐到当前实现

因此，现在可以把这版理解为：

**一套已经完成 hard-break 架构切换、并完成 3 类正式比赛口径收口的 V1-Lite benchmark builder 当前实现。**
