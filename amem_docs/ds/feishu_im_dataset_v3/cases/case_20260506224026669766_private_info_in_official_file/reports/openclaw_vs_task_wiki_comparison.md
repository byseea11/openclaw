# OpenClaw Baseline vs Task Wiki 3 Layer

- Case: case_20260506224026669766_private_info_in_official_file
- Family: private_info_in_official_file
- Task: FEISHU-666
- Baseline mode: openclaw_original_adapter

重要说明：当前 Python phase3 的 baseline_eval.py 是 synthetic baseline，不代表真实 OpenClaw baseline。本报告使用同一批 observed ingress 的原始 OpenClaw adapter 结果。

## Query Metrics

| Method | Query success | Evidence trace | Current state | Private leak | Official precision |
| --- | ---: | ---: | ---: | ---: | ---: |
| openclaw_original | 1 | 1 | 1 | 0 | 1 |
| task_wiki_3_layer | see runtime health | see runtime health | see runtime health | see semantic eval when enabled | see semantic eval when enabled |

## Runtime Health

| Method | Status | Health score | Verified events | Projected tasks |
| --- | --- | ---: | ---: | ---: |
| openclaw_original | completed | n/a | n/a | n/a |
| task_wiki_3_layer | needs_review | 65 | 0 | 1 |

## Private Info In Official File Checks

- 是否把个人偏好误当任务 blocker：未检测到
- 是否保留正式纪要中的升级窗口、blocker、回滚计划：是
- 是否能回答“以正式纪要为准”：是

## Outputs

- Baseline answers: amem_docs/ds/feishu_im_dataset_v3/cases/case_20260506224026669766_private_info_in_official_file/runtime/openclaw_baseline/answers.json
- Evidence traces: amem_docs/ds/feishu_im_dataset_v3/cases/case_20260506224026669766_private_info_in_official_file/runtime/openclaw_baseline/evidence_traces.json
- Baseline report: amem_docs/ds/feishu_im_dataset_v3/cases/case_20260506224026669766_private_info_in_official_file/reports/openclaw_baseline_eval.json
- Task Wiki runtime report: amem_docs/ds/feishu_im_dataset_v3/cases/case_20260506224026669766_private_info_in_official_file/reports/task_wiki_runtime_eval.md

