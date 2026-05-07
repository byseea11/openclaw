# story-beats

## 职责

这个 skill 负责定义 phase1 的 beat skeleton owner。它先把 benchmark roles、beat identity 和目标 session 落点定死，conversation 阶段只负责把这些 beat 展开成真实 turn。

## 硬规则

- 必须产出：
  - `case_id`
  - `family_id`
  - `task_id`
  - `beats`
- 每个 beat 至少包含：
  - `beat_id`
  - `target_session_id`
  - `benchmark_role`
  - `description`
- `target_session_id` 只能引用已声明的 session roster。
- family-specific required benchmark roles 必须在本阶段先显式落位。
- 应吸收旧版 `story_beats_generator.py` 的思路：
  - trap / requirement 先映射成 beat skeleton
  - session 落点先确定
  - 下游只展开，不重定义 beat identity

## 禁止

- 不要直接在本阶段写完整对话 turn。
- 不要让后续阶段新增本阶段不存在的 beat。
- 不要省略 benchmark role，只留下自由文本消息意图。

## JSON 示例

```json
{
  "case_id": "case_0203_evidence_dependency_reasoning",
  "family_id": "evidence_dependency_reasoning",
  "task_id": "FEISHU-203",
  "beats": [
    {
      "beat_id": "beat_001",
      "benchmark_role": "verified_anchor_turn",
      "description": "正式确认上游窗口未锁定，是当前主 blocker 的核心证据。",
      "target_session_id": "main_chat"
    },
    {
      "beat_id": "beat_002",
      "benchmark_role": "hearsay_turn",
      "description": "插入一条传闻型缓解说法，制造证据梯度。",
      "target_session_id": "risk_review_thread"
    }
  ]
}
```

## V3 Phase 1 对接位置

在细分 Phase 1 链路里，`story-beats` 读取 `capability-brief`、family context skill、`case-world`、`state-trajectory` 和 `coverage-spec`，把必须落地的证据要求映射成 beat skeleton。

不同 family 的 beat 重点：

- `anti_interference`：target fact、shared actor noise、similar wording noise、explicit exclusion、probe setup。
- `contradiction_update`：initial state、historical update、supersession、final current state、history/current disambiguation。
- `evidence_dependency_reasoning`：verified anchor、ambiguous claim、hearsay、dependency impact、target conclusion。

本阶段只定义 beat identity、benchmark role、description 和 target session。完整消息文本由 `conversation-plan` 生成，真实 action 由 `command-plan` 生成。
