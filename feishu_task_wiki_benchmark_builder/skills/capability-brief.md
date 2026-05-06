# capability-brief

## 什么时候使用

当 family 已经确定，当前要把这类能力实例化成 case-specific brief 时使用。

## 这一步要解决什么

- 说明本 case 测什么能力
- 说明默认记忆系统为什么可能失败
- 定义生成约束
- 定义 required case structure
- 定义 probe strategy
- 把比赛口径映射写进 brief，供 report 和 downstream 阶段共用

## 输出目标

- `input/memory_capability_brief.json`

## 字段应该帮助后续什么

- `capability_under_test`
  帮助后续判断这条 case 的主测试目标
- `benchmark_requirement_name`
  帮助后续 report 直接映射项目需求里的 benchmark 名称
- `benchmark_requirement_summary`
  帮助 case-world 和评审者理解这类 case 为什么存在
- `report_display_name`
  帮助最终报告以比赛口径展示结果
- `why_memory_systems_may_fail`
  帮助后续保持 trap 对准真实失败原理
- `generation_rules`
  约束 case-world 和 story-plan 不要跑偏
- `required_case_structure`
  约束 case-world 必须长成什么样
- `probe_strategy`
  约束 story-plan 的 planned probes 应该测试什么
- `expected_good_system_behavior`
  帮助 eval 阶段理解好系统应该怎么答

## 不要做什么

- 不要开始写企业场景
- 不要开始写任务细节
- 不要开始写 message beats
- 不要重新定义 family
- 不要把 `效能指标验证` 写成 family 字段
