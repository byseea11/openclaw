# Feishu Task Wiki Benchmark Builder Phase 3 实现与原理

## 阶段目标

Phase 3 的目标是做真实 cross-system scoring。

它比较的不是两个报告，而是两个系统在同一批 observed messages、同一份 gold、同一组 query 上的表现：

- `task_wiki_3_layer`
- `openclaw_original`

Phase 3 的正式产物是评分 JSON：

```text
reports/phase3_score.json
```

Markdown 只能作为派生阅读物，不是评分源。

Phase 3 要回答四个问题：

- 谁答对了。
- 谁输出了证据。
- 谁的证据真正命中 gold `message_id`。
- 谁在干扰、旧状态、传闻或个人私有信息上发生污染。

## Phase 3 主链路

```text
task-wiki-runtime-eval
-> openclaw-real-baseline-eval
-> comparative-score
```

用户入口脚本：

```text
amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh
```

它读取 Phase 1 / Phase 2 已经生成的输入：

- `data/openclaw_message_ingress.jsonl`
- `data/collected_messages.jsonl`
- `gold/annotation_gold.jsonl`
- `gold/task_wiki_semantic_gold.json`
- `gold/query_benchmark.json`

它输出：

- `runtime/task_wiki_replay/*`
- `runtime/openclaw_baseline/answers.json`
- `runtime/openclaw_baseline/evidence_traces.json`
- `runtime/openclaw_baseline/replay_metadata.json`
- `reports/openclaw_baseline_eval.json`
- `reports/phase3_score.json`

## Stage-by-stage 实现表

| Stage | 做什么 | 怎么生成 | 为什么需要它 | 下游如何使用 |
| --- | --- | --- | --- | --- |
| `task-wiki-runtime-eval` | 跑 Task Wiki 三层 runtime。 | 读取 `openclaw_message_ingress.jsonl`，依次执行 task binding、event extraction / verification、wiki projection / lint。 | Task Wiki 的分数必须来自真实三层处理，不来自 builder 计划。 | `comparative-score` 从 runtime predictions 中提取 verified events、wiki evidence 和三层健康状态。 |
| `openclaw-real-baseline-eval` | 跑真实 OpenClaw 原生 baseline。 | 使用隔离 `OPENCLAW_HOME / OPENCLAW_STATE_DIR`，把 observed transcript 写入 OpenClaw workspace memory，再通过真实 OpenClaw replay seam 回答 query。 | `openclaw_original` 不能用本地 adapter 或 family penalty 伪造；它必须代表原生 OpenClaw 在同一批消息上的表现。 | `comparative-score` 读取 baseline answers、supporting message ids 和 evidence traces。 |
| `comparative-score` | 生成最终评分 JSON。 | 对比 Task Wiki 和 OpenClaw 的 answer、evidence、safety、efficiency 四类指标。 | 评分必须能解释“谁赢”“为什么赢”“证据是否可靠”。 | 输出 `reports/phase3_score.json`，作为 Phase 3 唯一正式评分结果。 |

## 真实 OpenClaw Baseline 原理

Phase 3 不使用 `lark-cli` 去拉一个飞书里的 OpenClaw 小助手作为正式 baseline。

原因是这种方式会混入外部状态：

- 真实账号历史。
- 飞书投递链路。
- 小助手已有 session。
- 运行时延迟和权限差异。

这些因素会让 benchmark 不可复现。

当前正式方式是 repo 内 benchmark replay seam：

```text
observed messages
-> isolated OpenClaw home/state/workspace
-> workspace MEMORY.md transcript
-> openclaw agent / replay query
-> answers + evidence traces
```

它只给 OpenClaw 原生系统看 Phase 1 collect 得到的 observed transcript。

它不读取 Task Wiki 的 events、wiki、semantic gold answer 或评分结果。

如果 OpenClaw 当前没有结构化 evidence 输出，Phase 3 不会帮它补证据。

这种情况下：

```text
evidence_output_rate = 0
```

这是评分结论的一部分，而不是脚本失败。

## 为什么 OpenClaw Baseline 是真实的

真实 baseline 的关键是隔离和最小输入。

它会为每个 case 准备独立运行目录：

- `OPENCLAW_HOME`
- `OPENCLAW_STATE_DIR`
- `OPENCLAW_CONFIG_PATH`
- workspace memory 文件

然后把 Phase 1 的 observed transcript 写成 OpenClaw 原生 workspace memory。

query 通过 OpenClaw 自己的 agent / replay 路径回答。

这和旧 adapter 的区别是：

- 旧 adapter 用脚本规则挑 evidence、拼 answer。
- 真实 replay 让 OpenClaw 自己读记忆、自己回答。
- 评分器只读取 OpenClaw 输出，不替它解释证据。

如果真实 replay seam 不可用，Phase 3 会 fail fast。

它不会静默回退到 adapter。

## Comparative Score 原理

`reports/phase3_score.json` 是 Phase 3 的唯一正式评分源。

它至少包含：

- `case_id`
- `family_id`
- `systems.task_wiki_3_layer`
- `systems.openclaw_original`
- `per_query_scores`
- `aggregate_scores`
- `deltas`
- `failure_reason_breakdown`
- `evidence_metrics`

评分按 query 逐条进行。

每个 query 都会分别记录两个系统的：

- answer text。
- answer correctness。
- output evidence ids。
- gold evidence ids。
- matched / wrong evidence ids。
- failure reasons。
- answer / evidence / safety / efficiency 分数。

最后再汇总成系统级指标。

## 为什么可以评分

Phase 3 的评分成立，是因为输入和对比对象是同源的。

```text
Phase 1 observed messages
-> Phase 2 gold / semantic gold / query benchmark
-> Task Wiki runtime output
-> OpenClaw real baseline output
-> comparative score
```

两套系统看到的是同一批 observed messages。

两套系统回答的是同一组 query。

两套系统都用同一份 gold `message_id` 计算证据命中。

因此 Phase 3 比较的是系统行为，而不是数据差异。

## Evidence Scoring

证据是 Phase 3 的核心指标。

答案正确但没有证据，只能算弱通过。

证据存在但来自错误消息，也不能算强通过。

当前证据指标包括：

- `evidence_output_rate`：系统是否输出任何证据。
- `evidence_precision`：输出证据中有多少属于 gold supporting messages。
- `evidence_recall`：gold supporting messages 中有多少被覆盖。
- `evidence_task_relevance`：证据是否来自目标 task / 正确 source。
- `evidence_temporal_correctness`：矛盾更新场景中是否引用最新覆盖消息。
- `evidence_chain_completeness`：依赖推理场景中是否覆盖关键上游和下游。
- `evidence_private_info_safety`：是否避开不应作为 task state 的个人私有信息。

评分规则是：

- 答案语义正确但没有证据：`answer_score` 可以高，但 `evidence_score` 低。
- 证据来自干扰或旧状态：`evidence_precision` 和 family-specific safety 降低。
- 证据正确但答案语义错误：不能靠 evidence 抬高 `answer_score`。
- 没有结构化 evidence 输出：`evidence_output_rate = 0`。

## Family-specific 判定

### `anti_interference`

目标是抗干扰。

系统必须在大量无关对话、相似措辞和共享角色中找回目标任务事实。

核心指标：

- `target_fact_hit_rate`
- `distractor_leak_rate`
- `evidence_output_rate`
- `evidence_precision`
- `wrong_task_contamination_rate`

如果答案看起来正确，但证据来自干扰 session，不能算满分。

### `contradiction_update`

目标是 current-state 覆写。

系统必须理解旧口径已经被新口径覆盖。

核心指标：

- `current_state_accuracy`
- `stale_value_rejection_rate`
- `supersession_reasoning_rate`
- `evidence_ordering_accuracy`
- `current_evidence_citation_rate`

必须引用新指令或最终确认消息。

只答出新值但不给证据，属于弱通过。

### `evidence_dependency_reasoning`

目标是证据依赖和影响传播。

系统必须区分 verified、ambiguous、hearsay，并理解依赖链。

核心指标：

- `verified_fact_precision`
- `hearsay_rejection_rate`
- `dependency_impact_accuracy`
- `supporting_chain_trace_rate`
- `multi_hop_evidence_completeness`

只引用下游结论但缺少上游证据链，会降低 evidence score。

### `private_info_in_official_file`

目标是正式事实和个人私有信息不互相污染。

系统必须引用正式文件、正式纪要或正式同步消息作为任务状态证据。

个人私有信息只能作为 context，不能作为 task current state。

核心指标：

- `official_fact_precision`
- `private_info_leak_rate`
- `official_evidence_citation_rate`
- `private_context_exclusion_rate`

如果系统把个人偏好、私聊备注或个人时间限制当成任务 blocker，属于严重失败。

## 效能指标

效能不是独立 family。

它是 Phase 3 在所有 family 上的横向价值汇总。

当前效能指标包括：

- `query_success_rate_delta`
- `evidence_precision_delta`
- `answer_token_count_delta`
- `estimated_steps_saved`
- `estimated_time_saved_seconds`

这些指标回答的问题是：

- Task Wiki 是否更容易直接命中答案。
- Task Wiki 是否更稳定地输出证据。
- Task Wiki 是否减少人工查找消息的步骤。
- Task Wiki 是否降低阅读长 transcript 的成本。

## 输出如何读

### `runtime/task_wiki_replay/*`

这是 Task Wiki 三层 runtime 输出。

重点看：

- Layer 1 是否绑定目标任务。
- Layer 2 是否产生 verified events。
- Layer 3 是否完成 wiki projection 且无 blocking lint。

### `runtime/openclaw_baseline/answers.json`

这是原始 OpenClaw baseline 的 query answer。

重点看：

- 每个 query 的 `answer`。
- `supporting_message_ids` 是否存在。
- `judge_result` 是否通过。

### `runtime/openclaw_baseline/evidence_traces.json`

这是 OpenClaw baseline 的证据 trace。

如果 OpenClaw 没有输出证据，这里会保留空 evidence，而不是脚本补证据。

### `runtime/openclaw_baseline/replay_metadata.json`

这是真实 replay 的运行元信息。

它说明 baseline 是通过哪种 replay seam 跑出来的，是否使用了测试 harness，隔离 state/workspace 在哪里。

### `reports/openclaw_baseline_eval.json`

这是 OpenClaw baseline 自身指标。

它不和 Task Wiki 比较，只记录 OpenClaw 在 query 和 evidence 上的表现。

### `reports/phase3_score.json`

这是最终评分 JSON。

它是 Phase 3 唯一正式产物。

如果要判断系统胜负，优先读这个文件。

## 质量边界

Phase 3 不做三件事：

- 不重新生成数据集。
- 不修改 Phase 2 gold。
- 不给 OpenClaw 补不存在的 evidence。

Phase 3 只做真实对比。

如果 `openclaw_original` 不能通过真实 replay seam 跑起来，Phase 3 应该失败。

如果 `task_wiki_3_layer` 没有 verified events，Phase 3 应该把 Task Wiki 的 answer/evidence 分数降下来，而不是因为 wiki 文件存在就算通过。

如果某个系统答案正确但证据缺失，Phase 3 应该把它写成“弱通过”，而不是强通过。

