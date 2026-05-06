# evaluation

## 职责

这个 skill 负责说明 `pre-annotation-validate`、gold、query benchmark、baseline 和 value eval 的评测口径。

## 硬规则

- `pre-annotation-validate` 只能基于 observed messages 判断关键 beat 是否落地。
- `annotation-gold` 只能基于 observed messages 回标，不能把未发生的计划内容直接标成 gold。
- `query-benchmark` 负责把 `planned_probe_queries` 收口成正式 query。
- `value-eval` 负责比较 Task Wiki 与 baseline 的能力差异。
- benchmark query 只围绕单个目标 task 评测；distractor 只作为误答来源，不是并列评测对象。

## 禁止

- 不要把 observed validation 当成 gold。
- 不要跳过 collect 直接写理想化 gold。
- 不要把 `效能指标验证` 误当成 formal family。
- 不要把 distractor 当成正式 query target。

## JSON 示例

下面是评测期望的片段示例：

```json
{
  "pre_annotation_validation_report": {
    "critical_beats_present": true,
    "probe_ready": true
  },
  "query_benchmark": {
    "queries": [
      {
        "query_id": "query_01",
        "question": "FEISHU-201 当前负责人是谁？"
      }
    ]
  }
}
```
