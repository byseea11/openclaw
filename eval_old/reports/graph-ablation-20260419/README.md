# Graph Vs Native Sample Report

This folder stores a small native-vs-graph comparison run focused on graph-friendly memory workloads.

Contents:

- `longmemeval/comparison.json`
  Official `run_graph_ablation.py` output using `eval/fixtures/longmemeval_smoke.json`.
- `longmemeval/native.predictions.summary.json`
  Native variant summary for the LongMemEval smoke fixture.
- `longmemeval/graph.predictions.summary.json`
  Graph-enabled variant summary for the LongMemEval smoke fixture.
- `locomo/manual-single-sample-report.json`
  Manual follow-up comparison for one LoCoMo sample after replaying the original conversation into both gateways.
- `locomo/single-sample-input.json`
  The exact LoCoMo single-sample input used for the manual comparison. It was derived from `locomo/data/locomo10.json`, sample `conv-30`, question index `13`.
- `locomo/mini-open-date-input.json`
  A smaller LoCoMo-derived sample that preserves conflicting evidence about Gina's store opening date while keeping replay cost manageable.
- `locomo/mini-open-date-report.json`
  Scored native-vs-graph comparison for the mini LoCoMo sample. On this sample, graph improves QA F1 from `0.5` to `0.8`.

Notes:

- The LongMemEval artifact is an official ablation-runner output.
- The LoCoMo artifact is intentionally a smaller manual comparison because the full LoCoMo replay cost is high for quick spot checks.
- For the LoCoMo sample, the gold answer is `16 March, 2023`.
- For the LoCoMo mini sample, the key failure mode is contradictory evidence: native over-anchors on earlier business activity, while graph recall is able to prioritize the later explicit opening event.
