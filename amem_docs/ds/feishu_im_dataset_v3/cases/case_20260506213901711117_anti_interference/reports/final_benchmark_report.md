# case_20260506213901711117_anti_interference Benchmark Report

## Case Summary
- family_id: `anti_interference`
- task_id: `FEISHU-217`
- difficulty: `hard`

## Project Requirement Mapping
- report_display_name: 抗干扰测试
- benchmark_requirement_name: 抗干扰测试
- benchmark_requirement_summary: 在大量无关任务、共享角色和相似字段噪音下，仍然准确捞取目标任务的关键记忆。

## Capability Under Test
在共享角色和相似任务并存时，只回答目标任务的当前上下文，不把噪音任务的信息混入答案。

## Replay Result
- query_success_rate: 1.0
- evidence_trace_rate: 1.0
- current_state_accuracy: 1.0

## Baseline Comparison
- openclaw_memory_md: query=0.42, evidence=0.34, current_state=0.37
- raw_message_rag: query=0.68, evidence=0.64, current_state=0.65
- task_wiki: query=1.0, evidence=1.0, current_state=1.0

## Value Summary
- vs_openclaw_memory_md: 0.58
- vs_raw_message_rag: 0.32

Task Wiki 在该 case 上保持完整 query 成功率，并相对 baseline 展现正向提升。
