# evaluation

## 职责

这个 skill 负责说明 `pre-annotation-validate`、gold、query benchmark、baseline 和 value eval 的评测口径。

## 硬规则

- `pre-annotation-validate` 只能基于 observed messages 判断关键 beat 是否落地。
- `annotation-gold` 只能基于 observed messages 回标，不能把未发生的计划内容直接标成 gold。
- `semantic-gold` 只能基于 `observed_evidence_rows` 生成语义 gold；每条语义事实、事件语义和 query answer 都必须引用 observed `message_id`。
- `query-benchmark` 负责把 `planned_probe_queries` 收口成正式 query。
- `value-eval` 负责比较 Task Wiki 与 baseline 的能力差异。
- benchmark query 只围绕单个目标 task 评测；distractor 只作为误答来源，不是并列评测对象。

## 禁止

- 不要把 observed validation 当成 gold。
- 不要跳过 collect 直接写理想化 gold。
- 不要在 `semantic-gold` 最终输出里引用 `turn_id / beat_id / annotation_id`；这些只能辅助理解，最终 evidence id 必须是 `message_id`。
- 不要输出 Markdown、解释文字或数组根节点；只能输出一个 JSON object。
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

## Semantic Gold JSON Contract

`semantic-gold` 必须输出一个 JSON object，且只允许这些顶层字段作为正式内容：

```json
{
  "expected_task_facts": [
    {
      "fact_id": "fact_001",
      "claim": "目标任务当前事实。",
      "required_supporting_message_ids": ["om_xxx"]
    }
  ],
  "expected_event_semantics": [
    {
      "event_semantic_id": "event_semantic_001",
      "purpose": "这条证据表达的事件语义。",
      "turn_kind": "event_bearing",
      "required_supporting_message_ids": ["om_xxx"]
    }
  ],
  "expected_query_answers": [
    {
      "query_id": "semantic_query_001",
      "query": "要评测的问题。",
      "expected_answer_summary": "只基于 observed evidence 的答案摘要。",
      "required_supporting_message_ids": ["om_xxx"]
    }
  ]
}
```

硬规则：

- `required_supporting_message_ids` 里的每一项必须从 `allowed_message_ids` 原样复制。
- `annotation_id / turn_id / beat_id` 不能作为最终 citation。
- 如果无法找到 observed `message_id` 支撑某条语义结论，就不要输出这条结论。
