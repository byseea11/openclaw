# Feishu Task Wiki Benchmark Builder Phase 2 实现与原理

## 阶段目标

Phase 2 的目标是把 Phase 1 的 observed data 转成可评分对象。

它做两件事：

- 从真实消息生成 evidence gold 和 semantic gold。
- 用真实 OpenClaw Task Wiki runtime 跑 Layer 1 / Layer 2 / Layer 3 健康评估。

Phase 2 不重新生成企业对话。

它只读取 Phase 1 已经回收的 observed messages、OpenClaw ingress 和输入计划 trace。所有 gold、query 和评分依据都必须能回到真实 `message_id`。

## Phase 2 主链路

```text
annotation-gold
-> semantic-gold
-> query-benchmark
-> build-checks
-> gold-validate
-> replay-runtime
-> replay-eval
```

Phase 2 用户入口脚本：

```text
amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh
```

真实 runtime 健康评估的底层调试脚本是 `node feishu_task_wiki_benchmark_builder/runtime/task_wiki_runtime_eval.mjs`，Phase 3 对比也会调用它。

它读取：

- `data/openclaw_message_ingress.jsonl`
- `data/collected_messages.jsonl`
- `gold/*`
- `input/*`

它输出：

- `runtime/task_wiki_replay/summary.json`
- `runtime/task_wiki_replay/layer_metrics.json`
- `runtime/task_wiki_replay/task_wiki_runtime_predictions.json`
- `reports/task_wiki_runtime_eval.md`

## Gold 分层原理

Phase 2 的 gold 分两层。

### Deterministic Evidence Gold

`gold/annotation_gold.jsonl` 是 deterministic evidence gold。

它可以由规则生成，因为 Phase 1 已经完成了三件事：

- `conversation_plan.json` 标记了 `annotation_target` 和 `event_bearing`。
- `command-plan / execute / collect` 已经把 planned turn 对齐到真实 observed message。
- `collected_messages.jsonl` 已经包含真实 `message_id`、真实 text、session、thread、turn trace 和 speaker resolution。

所以 `annotation_gold.jsonl` 的含义不是“系统应该总结成什么答案”。

它的含义是：哪些真实消息是 benchmark evidence，哪些 observed `message_id` 应该作为事件、状态或 query 的支撑证据。

这类 gold 适合评测 evidence-level 能力：

- 系统有没有看到关键消息。
- 系统有没有保留证据引用。
- 系统抽取的 event 是否能对齐到真实 message。

它不能单独证明系统理解了任务状态。

### LLM Semantic Gold

`gold/task_wiki_semantic_gold.json` 是 semantic gold。

它需要 LLM，是因为状态、冲突、依赖和 query answer 不是简单字段拷贝。系统要理解“哪个事实是当前结论”“哪个旧口径已失效”“哪个个人信息不能污染任务状态”。

semantic gold 的输入不是完整 planned text。

它只允许读取 observed evidence rows：

- `message_id`
- `annotation_id`
- `turn_id`
- `evidence_text`
- `session_id`
- `turn_kind`
- `purpose`

最终输出必须只引用 observed `message_id`。

如果一条 expected fact、event semantic 或 query answer 找不到 observed message 支撑，就不能写入 semantic gold。

因此 semantic gold 可以作为 meaning-level judge 的基准：它不是模型凭空写答案，而是把已经发生的 evidence 归纳成可评测语义。

## Stage-by-stage 实现表

| Stage | 做什么 | 怎么生成 | 为什么需要它 | 下游如何使用 |
| --- | --- | --- | --- | --- |
| `annotation-gold` | 生成 evidence gold。 | 读取 `collected_messages.jsonl`，选择 `annotation_target=true` 或 `event_bearing=true` 的 observed rows，并保留真实 `message_id`。 | 它定义哪些真实消息是评测证据。 | event alignment、replay eval 和 semantic gold 都以它为 evidence 边界。 |
| `semantic-gold` | 生成语义 gold。 | LLM 只读取 observed evidence rows 和 allowed message ids，输出 expected facts、event semantics、query answers。 | evidence gold 只能证明证据位置，semantic gold 才能表达预期理解。 | semantic judge 和 query-level eval 用它判断 meaning 是否正确。 |
| `query-benchmark` | 生成正式 query。 | 从 capability/probe strategy 和 semantic gold 中收口目标任务问题。 | query 是最终用户视角，不是内部 event 字段。 | replay-eval 用它检查系统回答是否 faithful、有 evidence、没有 stale 或污染。 |
| `build-checks` | 生成质量 gate。 | 汇总 observed data、gold、query 和必要 schema check。 | 防止空 gold、无证据 query 或不一致 message id 进入评测。 | gold-validate 和 replay-eval 之前先做入口质量约束。 |
| `gold-validate` | 验证 gold 与 observed data 一致。 | 检查所有引用的 `message_id` 都存在，query/gold/evidence 能闭环。 | gold 如果引用不存在消息，评分就失去可信度。 | 通过后 runtime prediction 才能与 gold 对齐。 |
| `replay-runtime` | 生成 runtime prediction。 | 使用 `openclaw_message_ingress.jsonl` replay Task Wiki runtime，产出 binding、event、wiki state 和 answer 预测。 | 评分必须来自真实 runtime 行为，不来自 builder 内部计划。 | replay-eval 读取 predictions 与 gold 比较。 |
| `replay-eval` | 计算评测结果。 | 对比 prediction、annotation gold、semantic gold 和 query benchmark。 | 它把 evidence-level 和 meaning-level 判断变成报告指标。 | Phase 3 可以在此基础上做 baseline/value comparison。 |

## 为什么可以评分

Phase 2 的评分成立，依赖一个闭环：

```text
真实飞书消息
-> collected observed data
-> evidence gold
-> semantic gold / query benchmark
-> OpenClaw Task Wiki runtime prediction
-> replay eval
```

这个闭环有三个关键约束。

第一，gold 只能绑定 observed `message_id`。

这保证评分依据来自真实发生的消息，而不是 builder 的计划文本。

第二，evidence-level 和 semantic-level 分开。

`annotation_gold.jsonl` 判断系统有没有抓到证据；`task_wiki_semantic_gold.json` 判断系统是否理解了任务事实、状态变化、证据依赖和 query answer。

第三，runtime prediction 来自真实 Task Wiki 三层处理。

系统必须先完成 task binding，再完成 event extraction / verification，再完成 wiki projection。只有这样，Phase 2 才是在评测真实系统，而不是评测生成器自己。

## 真实 Runtime Eval

`node feishu_task_wiki_benchmark_builder/runtime/task_wiki_runtime_eval.mjs` 是当前真实三层 runtime 健康评估的底层调试入口。

运行方式：

```bash
node feishu_task_wiki_benchmark_builder/runtime/task_wiki_runtime_eval.mjs --case-dir <case_dir>
```

如果不传 `--case-dir`，脚本默认读取 dataset active case。

### Layer 1：Task Binding

Layer 1 判断 replay message 是否能绑定到目标任务。

核心指标：

- `binding_total`
- `binding_bound`
- `binding_rate`
- `target_task_binding_rate`
- `skipped_count`

通过条件是：有 replay ingress message，且目标任务绑定成功。

### Layer 2：Event Extraction + Verification

Layer 2 判断消息是否被抽成 candidate events，并且 verification 是否把候选推进到 verified ledger。

核心指标：

- `ingested_count`
- `candidate_event_count`
- `verified_event_count`
- `verification_rate`
- `session_count`
- `sessions_with_events`
- `candidate_validation_breakdown`
- `rejected_candidate_count`
- `ready_for_verification_count`
- `queued_verification_count`
- `rejection_reason_breakdown`
- `missing_field_breakdown`

通过条件是：`verified_event_count > 0`。

如果 candidate 很多但 verified 为 0，说明 Layer 2 抽取或 schema 归一有问题，不能把后续 wiki 文件存在当成通过。

### Layer 3：Wiki Projection + Lint

Layer 3 判断 verified events 是否进入 wiki projector，并且 wiki lint 是否有结构性阻塞。

核心指标：

- `task_root_count`
- `projected_task_count`
- `projection_status`
- `lint_blocking_count`
- `lint_warning_count`

通过条件是：

- Layer 2 已经有 verified events。
- 已经生成目标任务 wiki projection。
- `lint_blocking_count = 0`。

如果 Layer 2 没有 verified events，Layer 3 必须标记为被 Layer 2 阻塞，不能仅因为 wiki root 文件存在就算通过。

## 诊断输出如何读

### `summary.json`

这是 runtime eval 的机器可读摘要。

它告诉你 case 路径、状态目录、总体 status、health score 和报告位置。

### `layer_metrics.json`

这是三层健康指标。

它必须分别输出：

- `layer1_binding.status / score / blocking_failures / warnings`
- `layer2_events.status / score / blocking_failures / warnings`
- `layer3_wiki.status / score / blocking_failures / warnings`
- `overall.status / health_score / blocking_failures / warnings`

`health_score` 是三层加权分，不是唯一结论。

当前口径：

```text
health_score = layer1_score * 35% + layer2_score * 35% + layer3_score * 30%
```

报告必须先看每层 status，再看总分。

### `task_wiki_runtime_predictions.json`

这是 runtime prediction 明细。

它记录 binding、candidate events、verified events、wiki state 和 projection 结果，用于定位具体哪条消息进入了哪一层。

### `task_wiki_runtime_eval.md`

这是给人读的报告。

它需要直接展示：

- Layer 1 是否绑定成功。
- Layer 2 是否产生 verified events。
- Layer 3 是否完成 projection。
- Candidate Rejection Breakdown。
- missing fields、rejection reasons、lint blocking 和 warning。

当 Layer 2 出现大量 rejected candidate 时，优先看：

- typed required fields 是否缺失。
- evidence quote 是否能支撑 claim。
- event 是否足够 atomic。
- private-only 信息是否被错误抽成 task status。

## Phase 3 边界

Phase 3 负责真实 cross-system comparison。

当前 Phase 3 主线是：

```text
task-wiki-runtime-eval
-> openclaw-real-baseline-eval
-> comparative-score
```

它比较 `task_wiki_3_layer` 和 `openclaw_original`。

比较维度不只包括答案是否正确，也包括是否输出证据、证据是否命中 gold `message_id`、证据是否来自目标任务，以及是否混入干扰、旧状态、传闻或个人私有信息。

Phase 3 的正式结果是 `reports/phase3_score.json`。Markdown report 只能作为派生阅读物，不是评分源。

本文只解释 Phase 2 如何生成 gold、如何跑真实 runtime eval，以及为什么这些输出可以作为评分依据。
