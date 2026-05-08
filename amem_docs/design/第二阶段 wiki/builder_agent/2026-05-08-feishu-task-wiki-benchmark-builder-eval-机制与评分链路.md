# Feishu Task Wiki Benchmark Builder Eval 机制与评分链路

## 文档目标

本文说明 builder agent 是如何评测 Feishu Task Wiki benchmark case 的。

它不重复 Phase 2 / Phase 3 的完整实现细节，而是把评测闭环串起来：

```text
Phase 1 observed messages
-> Phase 2 gold / query benchmark
-> Phase 3 Task Wiki runtime + OpenClaw baseline
-> reports/phase3_score.json
```

核心结论是：

- `runtime-eval` 只判断 Task Wiki 三层 runtime 是否健康跑通。
- `comparative-score` 才是 Task Wiki 和 OpenClaw baseline 的最终 cross-system scoring。
- 最终正式评分源只有 `reports/phase3_score.json`。

---

## 1. 评测总链路

builder agent 的评测不是直接拿计划文本打分。

正式评分只能从 Phase 1 真实回收的数据开始：

```text
真实飞书执行
-> data/collected_messages.jsonl
-> data/openclaw_message_ingress.jsonl
-> gold/annotation_gold.jsonl
-> gold/task_wiki_semantic_gold.json
-> gold/query_benchmark.json
-> runtime/task_wiki_replay/*
-> runtime/openclaw_baseline/*
-> reports/phase3_score.json
```

这条链路保证三件事：

- 评分依据来自真实 observed `message_id`，不是 planned-only text。
- Task Wiki 和 OpenClaw baseline 看到同一批 observed messages。
- 两个系统都用同一份 gold 和 query benchmark 做比较。

---

## 2. Phase 2：生成评分基准

Phase 2 的职责是把 observed data 转成可评分对象。

主链路是：

```text
annotation-gold
-> semantic-gold
-> query-benchmark
-> build-checks
-> gold-validate
-> replay-runtime
-> replay-eval
```

### `annotation-gold`

输出：

```text
gold/annotation_gold.jsonl
```

它是 deterministic evidence gold。

它只基于 `data/collected_messages.jsonl` 回标真实 observed messages，定义哪些真实 `message_id` 是 benchmark evidence。

它回答的问题是：

- 哪些消息承载关键事实。
- 哪些消息应该作为 event / state / query 的证据。
- 系统输出的 evidence 是否能对齐真实 observed message。

它不负责判断最终答案语义是否正确。

### `semantic-gold`

输出：

```text
gold/task_wiki_semantic_gold.json
```

它是 meaning-level gold。

它可以使用 LLM，但只能读取 observed evidence rows，并且最终每条 expected fact、event semantic 和 query answer 都必须引用 observed `message_id`。

它回答的问题是：

- 哪些事实是当前有效事实。
- 哪些旧口径已经被 supersede。
- 哪些依赖、传闻、干扰或私有信息不能污染任务状态。
- 用户 query 的预期语义答案是什么。

### `query-benchmark`

输出：

```text
gold/query_benchmark.json
```

它把 `planned_probe_queries` 和 semantic gold 收口成正式 query。

query 只围绕单个目标 task 评测。distractor 只作为误答来源，不是并列评测对象。

### `gold-validate`

输出：

```text
checks/gold_validation_report.json
checks/dataset_audit_report.json
```

它检查：

- gold 引用的 `message_id` 是否都存在于 observed messages。
- query / semantic gold / evidence 是否能闭环。
- task id 是否只落在允许的目标任务或明确允许的相关任务上。

如果 gold validation 失败，后续评分不可信，应该 fail fast。

### `replay-eval`

输出：

```text
reports/replay_eval.json
```

它是 Phase 2 的 replay 结果汇总。

它可以帮助检查 query 和 gold 是否可用于评分，但最终系统胜负不以它为唯一来源。

---

## 3. Task Wiki Runtime Eval：三层健康度

Task Wiki runtime eval 的底层入口是：

```text
node feishu_task_wiki_benchmark_builder/runtime/task_wiki_runtime_eval.mjs
```

用户侧脚本包括：

```text
amem_docs/scripts/02-feishu-task-wiki-phase2-eval.sh
amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh
```

runtime eval 的作用是检查真实 Task Wiki 三层 pipeline 是否健康。

它不是最终 cross-system score，也不替代 semantic gold、query benchmark 或 comparative eval。

### Layer 1：Task Binding

Layer 1 判断 replay message 是否能绑定到目标 task。

核心指标：

- `binding_total`
- `binding_bound`
- `binding_rate`
- `target_task_binding_rate`
- `skipped_count`

通过条件：

- 有 replay ingress message。
- 至少存在 task binding。
- `target_task_binding_rate = 1`。

### Layer 2：Event Extraction + Verification

Layer 2 判断消息是否被抽成 candidate events，并且 verification 是否把候选推进到 verified ledger。

核心指标：

- `ingested_count`
- `candidate_event_count`
- `verified_event_count`
- `verification_rate`
- `candidate_validation_breakdown`
- `rejection_reason_breakdown`
- `missing_field_breakdown`

通过条件：

```text
verified_event_count > 0
```

如果 candidate 很多但 verified 为 0，说明 extraction、schema normalization 或 verification 有问题，不能因为后面生成了 wiki 文件就算通过。

### Layer 3：Wiki Projection + Lint

Layer 3 判断 verified events 是否进入 wiki projector，并且 lint 是否存在结构性阻塞。

核心指标：

- `task_root_count`
- `projected_task_count`
- `projection_status`
- `lint_blocking_count`
- `lint_warning_count`

通过条件：

- Layer 2 已经产生 verified events。
- 目标任务已经完成 wiki projection。
- `lint_blocking_count = 0`。

如果 Layer 2 没有 verified events，Layer 3 必须标为 `blocked_by_layer2`。

### Health Score

runtime eval 会输出健康分：

```text
health_score = layer1_score * 35% + layer2_score * 35% + layer3_score * 30%
```

这个分数用于诊断 Task Wiki runtime 是否健康，不等价于最终 benchmark 胜负。

---

## 4. Phase 3：真实系统对比

Phase 3 的职责是做 cross-system scoring。

主链路是：

```text
task-wiki-runtime-eval
-> openclaw-real-baseline-eval
-> comparative-score
```

比较对象是：

- `task_wiki_3_layer`
- `openclaw_original`

两边必须使用同一批 observed messages、同一份 semantic gold 和同一份 query benchmark。

### `task-wiki-runtime-eval`

它运行真实 Task Wiki 三层 pipeline，并输出：

```text
runtime/task_wiki_replay/summary.json
runtime/task_wiki_replay/layer_metrics.json
runtime/task_wiki_replay/task_wiki_runtime_predictions.json
reports/task_wiki_runtime_eval.md
```

`comparative-score` 会读取 Task Wiki 的 runtime predictions、verified events、wiki state 和 health metrics。

### `openclaw-real-baseline-eval`

它运行真实 OpenClaw baseline，并输出：

```text
runtime/openclaw_baseline/answers.json
runtime/openclaw_baseline/evidence_traces.json
runtime/openclaw_baseline/replay_metadata.json
reports/openclaw_baseline_eval.json
```

baseline 必须走真实 OpenClaw replay seam。

它不能读取：

- Task Wiki events。
- Task Wiki wiki。
- semantic gold answer。
- scoring result。

如果 OpenClaw 没有结构化 evidence 输出，必须显式记为：

```text
evidence_output_rate = 0
```

不能由评测脚本替它补证据。

### `comparative-score`

最终输出：

```text
reports/phase3_score.json
```

它逐 query 比较两个系统：

- answer 是否正确。
- 是否输出 evidence。
- evidence 是否命中 gold supporting message ids。
- evidence 是否来自正确 task / source / session。
- 是否避开干扰、旧状态、传闻和个人私有信息。
- 是否节省查找步骤和阅读成本。

---

## 5. Answer 与 Evidence 分开评分

Phase 3 必须把 answer correctness 和 evidence correctness 分开。

这条规则很重要，因为 Task Wiki 的目标不是只给出看起来对的答案，而是给出可追溯的任务事实。

评分含义如下：

- 答案正确且证据命中 gold：强通过。
- 答案正确但没有证据：弱通过。
- 答案正确但证据来自干扰或旧状态：不能算强通过。
- 证据正确但答案语义错误：不能靠 evidence 抬高 answer score。
- 没有结构化 evidence 输出：`evidence_output_rate = 0`。

核心 evidence 指标包括：

- `evidence_output_rate`
- `evidence_precision`
- `evidence_recall`
- `evidence_task_relevance`
- `evidence_temporal_correctness`
- `evidence_chain_completeness`
- `evidence_private_info_safety`

---

## 6. Family-specific 评测重点

不同 family 的 scoring 关注点不同。

### `anti_interference`

目标是抗干扰。

重点看：

- 是否命中目标任务事实。
- 是否引用正确 source/session。
- 是否把相似任务、相似角色或噪声消息误当目标任务事实。

如果答案看起来正确，但 evidence 来自 distractor session，不能算满分。

### `contradiction_update`

目标是 current-state 覆写。

重点看：

- 是否回答最新 current value。
- 是否拒绝 stale value。
- 是否引用新口径或最终确认消息。
- 是否保留 supersession 关系。

只答出新值但不给 evidence，属于弱通过。

### `evidence_dependency_reasoning`

目标是证据依赖和影响传播。

重点看：

- 是否区分 verified / ambiguous / hearsay。
- 是否覆盖关键上游证据。
- 是否解释 downstream impact。
- 是否避免把传闻当 verified fact。

只引用下游结论但缺少上游证据链，会降低 evidence score。

### `private_info_in_official_file`

目标是正式任务事实和个人私有信息不互相污染。

重点看：

- 是否引用正式文件、正式纪要或正式同步消息。
- 是否避免把个人偏好、私聊备注或个人时间限制写成 task current state。
- 是否把 private info 只作为 context，而不是任务事实。

如果系统把个人私有信息当成任务 blocker，属于严重失败。

---

## 7. 输出文件怎么读

### `runtime/task_wiki_replay/layer_metrics.json`

这是 Task Wiki 三层健康指标。

优先看：

- `layer1_binding.status`
- `layer2_events.status`
- `layer3_wiki.status`
- `overall.health_score`
- `blocking_failures`
- `warnings`

不要只看 `health_score`，要先看每层是否有 blocking failure。

### `runtime/task_wiki_replay/task_wiki_runtime_predictions.json`

这是 Task Wiki runtime prediction 明细。

它用于追踪：

- 哪些 message 被绑定到 task。
- 哪些 candidate event 被抽取。
- 哪些 event 进入 verified ledger。
- 哪些 evidence 进入 wiki projection。

### `reports/openclaw_baseline_eval.json`

这是 OpenClaw baseline 自身评估。

它说明 baseline 是如何回答 query 的，以及是否输出了可定位 evidence。

它不是最终胜负文件。

### `reports/phase3_score.json`

这是 Phase 3 唯一正式评分源。

判断系统胜负时优先读它。

它应包含：

- `systems.task_wiki_3_layer`
- `systems.openclaw_original`
- `per_query_scores`
- `aggregate_scores`
- `deltas`
- `failure_reason_breakdown`
- `evidence_metrics`

---

## 8. 评测边界

- gold 只能引用 observed `message_id`。
- `semantic-gold` 不能引用 planned-only text 作为最终 evidence。
- `query-benchmark` 只围绕目标 task，不把 distractor 当正式 query target。
- Task Wiki answer adapter 不允许读取 semantic gold answer 后再回答。
- unified answer judge 必须同时用于 `task_wiki_3_layer` 和 `openclaw_original`。
- OpenClaw baseline 必须走真实 replay seam，不允许静默回退 adapter。
- Markdown report 只能作为阅读物，不能作为评分源。
- `reports/phase3_score.json` 是 Phase 3 唯一正式评分产物。
