# evaluation

## 职责

这个 skill 负责说明 `pre-annotation-validate`、gold、query benchmark、baseline 和 comparative eval 的评测口径。

## 硬规则

- `pre-annotation-validate` 只能基于 observed messages 判断关键 beat 是否落地。
- `annotation-gold` 只能基于 observed messages 回标，不能把未发生的计划内容直接标成 gold。
- `semantic-gold` 只能基于 `observed_evidence_rows` 生成语义 gold；每条语义事实、事件语义和 query answer 都必须引用 observed `message_id`。
- `query-benchmark` 负责把 `planned_probe_queries` 收口成正式 query。
- `comparative-score` 负责比较 Task Wiki 三层与真实 OpenClaw baseline 的答案、证据、安全和效能差异，并输出 `reports/phase3_score.json`。
- benchmark query 只围绕单个目标 task 评测；distractor 只作为误答来源，不是并列评测对象。
- Phase 3 必须把 answer correctness 和 evidence correctness 分开评分。

## 禁止

- 不要把 observed validation 当成 gold。
- 不要跳过 collect 直接写理想化 gold。
- 不要在 `semantic-gold` 最终输出里引用 `turn_id / beat_id / annotation_id`；这些只能辅助理解，最终 evidence id 必须是 `message_id`。
- 不要输出 Markdown、解释文字或数组根节点；只能输出一个 JSON object。
- 不要把 `效能指标验证` 误当成 formal family。
- 不要把 distractor 当成正式 query target。
- 不要用固定满分或 family penalty 常量伪造 Phase 3 结果。
- 不要把 Markdown report 当成 Phase 3 评分源。
- 不要默认或隐式使用 `openclaw_original_adapter`；真实 OpenClaw replay 不可用时必须失败。

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

## Phase 3 Cross-system Eval

Phase 3 的正式比较对象是：

- `task_wiki_3_layer`
- `openclaw_original`

两边必须使用同一批 observed messages、同一份 semantic gold 和同一份 query benchmark。

Phase 3 必须分别判断：

- answer 是否正确。
- evidence 是否输出。
- evidence 是否命中 gold supporting message ids。
- evidence 是否来自正确 task / source / session。
- evidence 是否避开干扰、旧状态、传闻和个人私有信息。

如果某个系统不输出结构化 evidence，必须显式记为 `evidence_output_rate=0`，不能跳过证据比较。

Phase 3 的唯一正式评分产物是：

```text
reports/phase3_score.json
```

它必须包含：

- `systems.task_wiki_3_layer`
- `systems.openclaw_original`
- `per_query_scores`
- `aggregate_scores`
- `deltas`
- `failure_reason_breakdown`
- `evidence_metrics`

## 效能指标验证

`效能指标验证` 是最终 benchmark report 的必要维度，但它不是独立 family。

它应该跨不同 family 汇总：

- 命中率提升。
- 证据输出率提升。
- 证据准确率提升。
- 平均检索步骤减少。
- 平均输入字符数减少。
- 平均完成时间减少。
