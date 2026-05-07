# runtime-eval

## 职责

这个 skill 负责说明真实 Task Wiki runtime eval 的三层健康判定口径。

它对应脚本：

```text
amem_docs/scripts/feishu-task-wiki-runtime-eval.sh
```

runtime eval 只判断真实三层 runtime 是否健康跑通，不替代 Phase 2/3 的 semantic gold、query benchmark 或 value eval。

## 三层判定

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
- 至少有 task binding。
- `target_task_binding_rate` 必须为 1。

分数：

```text
layer1_score = target_task_binding_rate * 100
```

### Layer 2：Event Extraction + Verification

Layer 2 判断 immediate extraction 是否产生候选事件，并且 verification 是否把候选事件推进到 verified ledger。

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

通过条件：

- `verified_event_count > 0`

warning 条件：

- `candidate_event_count = 0`
- `candidate_event_count > 0` 且 `verification_rate < 0.8`

分数：

```text
layer2_score = verification_rate * 100
```

### Layer 3：Wiki Projection + Lint

Layer 3 判断 verified events 是否进入 wiki projector，并且 lint 是否存在结构性阻塞问题。

核心指标：

- `task_root_count`
- `projected_task_count`
- `projection_status`
- `lint_blocking_count`
- `lint_warning_count`

通过条件：

- `verified_event_count > 0`
- `projected_task_count > 0`
- `lint_blocking_count = 0`

如果 Layer 2 没有 verified events，Layer 3 必须标记为 `blocked_by_layer2`，不能仅因为生成了 wiki root 就算 `passed`。

blocking lint 包括：

- open conflict
- stale claim
- missing cross ref
- orphan session wiki

warning lint 包括：

- orphan event
- missing evidence ref
- quote strength finding
- unresolved objection
- overdue commitment
- orphan block

分数：

```text
layer3_score = 100 if Layer 2 has verified events and projected else 0
layer3_score -= min(20, lint_blocking_count * 5)
```

## Overall Health

总体状态：

- 任意 layer 有 `blocking_failures`，则 `overall.status = needs_review`
- 三层都无 blocking failure，则 `overall.status = passed`

总体分数：

```text
health_score = layer1_score * 35% + layer2_score * 35% + layer3_score * 30%
```

示例：

```text
Layer 1 = 100
Layer 2 = 90
Layer 3 = 100
health_score = 100 * 0.35 + 90 * 0.35 + 100 * 0.30 = 96.5
```

## 输出要求

`layer_metrics.json` 必须分别输出：

- `layer1_binding.status / score / blocking_failures / warnings`
- `layer2_events.status / score / blocking_failures / warnings / candidate_validation_breakdown / rejection_reason_breakdown / missing_field_breakdown`
- `layer3_wiki.status / score / blocking_failures / warnings`
- `overall.status / health_score / blocking_failures / warnings`

Markdown report 必须直接展示每层判定，不能只输出 overall health score。

当 candidate 被拒绝时，报告必须展示 Candidate Rejection Breakdown，用来区分：

- 缺少 typed required fields。
- evidence quote 不在 core entry 中。
- event 不满足 atomicity。
- private-only 信息被错误抽成 task status。
