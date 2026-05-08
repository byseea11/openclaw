# Task Wiki Runtime Eval

## 如何阅读结果

- 这份报告只评估真实 Task Wiki 三层 runtime 是否健康跑通，不判断 query answer 的语义胜负。
- `candidate_events` 表示 Layer 2 从消息中抽到了候选事件。
- `verified_events` 表示候选事件通过验证并进入 Layer 3 projector。
- `status=passed` 只代表三层健康门槛通过；完整 benchmark 效能仍看 Phase 2/3 的 gold、replay 和 value eval。

## Summary

- case_id: case_20260508030344241234_anti_interference
- task_id: FEISHU-334
- case_dir: amem_docs/ds/feishu_im_dataset_v3/batches/batch_20260508_030344240509/cases/case_20260508030344241234_anti_interference
- state_dir: amem_docs/ds/feishu_im_dataset_v3/batches/batch_20260508_030344240509/cases/case_20260508030344241234_anti_interference/runtime/task_wiki_state
- status: passed
- health_score: 96.5
- score_formula: Layer1 * 35% + Layer2 * 35% + Layer3 * 30%

## Layer 1: Task Binding

- status: passed
- score: 100
- binding_total: 28
- binding_bound: 28
- binding_rate: 1
- target_task_binding_rate: 1
- skipped_count: 0
- blocking_failures: none
- warnings: none

Layer 1 失败时优先检查：

- `data/openclaw_message_ingress.jsonl` 是否存在目标 task id 或可绑定上下文。
- `input/case_context.json` 的 `task_id` 是否和 replay 消息一致。

## Layer 2: Event Extraction / Verification

- status: passed
- score: 90
- ingested_count: 28
- candidate_event_count: 30
- verified_event_count: 27
- verification_rate: 0.9
- session_count: 4
- sessions_with_events: 4
- ready_for_verification_count: 28
- queued_verification_count: 28
- rejected_candidate_count: 2
- blocking_failures: none
- warnings: none

### Candidate Rejection Breakdown

- candidate_validation_breakdown: {"ready_for_verification":28,"rejected":2}
- rejection_reason_breakdown: {"quote_location:missing_entry":2}
- missing_field_breakdown: {}

Layer 2 失败时优先检查：

- `runtime/task_wiki_state/**/candidate_events.jsonl` 是否为空。
- `runtime/task_wiki_state/**/session_events.jsonl` 是否有 verified 事件。
- `data/openclaw_message_ingress.jsonl` 的正文是否被正确剥离 speaker prefix。

## Layer 3: Wiki Projection / Lint

- status: passed
- score: 100
- task_root_count: 1
- projected_task_count: 1
- projection_status: projected
- lint_blocking_count: 0
- lint_warning_count: 1
- blocking_failures: none
- warnings: layer3:lint_warnings_present

Layer 3 失败时优先检查：

- `runtime/task_wiki_state/**/task_wiki_state.json` 是否生成。
- `runtime/task_wiki_state/**/task_wiki.md` 是否生成。
- `runtime/task_wiki_state/**/lint_state.json` 的 blocking findings。

## Overall Health

- blocking_failures: none
- warnings: layer3:lint_warnings_present

## Output Files

- summary: amem_docs/ds/feishu_im_dataset_v3/batches/batch_20260508_030344240509/cases/case_20260508030344241234_anti_interference/runtime/task_wiki_replay/summary.json
- layer_metrics: amem_docs/ds/feishu_im_dataset_v3/batches/batch_20260508_030344240509/cases/case_20260508030344241234_anti_interference/runtime/task_wiki_replay/layer_metrics.json
- predictions: amem_docs/ds/feishu_im_dataset_v3/batches/batch_20260508_030344240509/cases/case_20260508030344241234_anti_interference/runtime/task_wiki_replay/task_wiki_runtime_predictions.json
- report: amem_docs/ds/feishu_im_dataset_v3/batches/batch_20260508_030344240509/cases/case_20260508030344241234_anti_interference/reports/task_wiki_runtime_eval.md

## Runtime Trace

- verification_result_count: 4
- lint_result_count: 1
