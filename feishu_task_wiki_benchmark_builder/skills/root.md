# Feishu Task Wiki Builder Skills

这是 Feishu Task Wiki benchmark builder 的机器 guidance 总入口。

## 当前提供的内部 skills

- `family-selection`
- `capability-brief`
- `case-world`
- `story-plan`
- `evaluation`

## 当前正式比赛 family

- `anti_interference`
- `contradiction_update`
- `evidence_dependency_reasoning`

## Stage Routing

| 当前阶段 | 使用的 skill | 目标 |
| --- | --- | --- |
| `dataset-plan` | 无单独 skill | 这是 deterministic planning，不需要模型自由发挥 |
| `family-selection` | `family-selection` | 选择当前 case 要测哪一类 memory capability family |
| `memory-capability-brief` | `capability-brief` | 把 family 实例化成 case-specific brief |
| `case-spec` | 无单独 skill | 这是 code-owned control artifact |
| `case-world` | `case-world` | 把 brief 业务化成自然企业场景 |
| `story-plan` | `story-plan` | 统一生成 `story_plan.json` |
| `command-plan` | 无单独 skill | 这是 code-owned compilation step |
| `execute` / `collect` | 无单独 skill | 这是 runtime step |
| `pre-annotation-validate` / `annotation-gold` / `query-benchmark` / `replay-eval` / `baseline-eval` / `value-eval` | `evaluation` | 解释 observed validation、gold 和 eval 口径 |

## Stage Identification

- 如果当前问题是“这条 case 应该测哪类能力”，进入 `family-selection`
- 如果 family 已定，当前要定义能力目标、失败原因、generation rules 或 probe strategy，进入 `capability-brief`
- 如果 brief 已定，当前要把它落成真实企业协作背景，进入 `case-world`
- 如果当前要生成 tasks、actors、state_changes、message_beats 或 planned_probe_queries，进入 `story-plan`
- 如果当前讨论 observed validation、annotation gold、query benchmark、baseline 或 value report，进入 `evaluation`

## 全局硬规则

- `story_plan.json` 是唯一核心中间 artifact
- 正式比赛 family 只有 `anti_interference`、`contradiction_update`、`evidence_dependency_reasoning`
- `效能指标验证` 是跨 family 的最终评测维度，不是 formal family
- 不允许重新引入 `memory_failure_blueprint`
- 不允许重新引入 `case_manifest`
- 不允许把 `state_trajectory.json` 重新变成正式独立 artifact
- 不允许把 `probe_targets.json` 重新变成正式独立 artifact
- 不允许把 `memory_case_contract.json` 重新变成正式独立 artifact
- prompt 只存在于代码里的 `prompt.py`
- `docs/` 只给人看，不是 runtime prompt source，也不是 machine skill source
