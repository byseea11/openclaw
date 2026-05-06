# conversation-plan

## 职责

这个 skill 负责定义 phase1 的 turn realization owner。它把 actor、session、beat skeleton 绑定成具体 turn，并使用结构化 speaker 引用，后续 `command-plan` 只做 compile。

## 硬规则

- 必须产出：
  - `case_id`
  - `family_id`
  - `task_id`
  - `sessions`
  - `turns`
- 每个 turn 至少包含：
  - `turn_id`
  - `beat_id`
  - `sequence_no`
  - `session_id`
  - `speaker_actor_id`
  - `speaker`
  - `planned_message_text`
- `speaker_actor_id` 必须引用上一步 actor roster。
- `speaker` 必须与对应 actor 的 `display_name` 一致。
- `session_id` 必须引用上一步 session roster。
- 应吸收旧版 `conversation_plan_generator.py` 的思路：
  - `speaker_ref` 是结构化引用
  - session placement 先按 benchmark role / session preference 决定
  - turn ordering 先定，再下游 compile

## 禁止

- 不要用自由文本 speaker 充当唯一执行引用。
- 不要在本阶段创造新的 actor / session / beat。
- 不要让 `command-plan` 再去猜 speaker 对应谁。

## JSON 示例

```json
{
  "case_id": "case_0203_evidence_dependency_reasoning",
  "family_id": "evidence_dependency_reasoning",
  "task_id": "FEISHU-203",
  "sessions": [
    {
      "session_id": "main_chat",
      "session_type": "main_chat",
      "title": "主群协调",
      "session_purpose": "沉淀目标任务的主线 current state。"
    }
  ],
  "turns": [
    {
      "turn_id": "turn_001",
      "beat_id": "beat_001",
      "sequence_no": 1,
      "session_id": "main_chat",
      "speaker_actor_id": "carol",
      "speaker": "Carol",
      "planned_message_text": "我刚确认过，窗口今天还没锁定，所以 FEISHU-203 先不要对外承诺上线时间。"
    }
  ]
}
```

## V3 Phase 1 对接位置

在细分 Phase 1 链路里，`conversation-plan` 读取 `task-actor-layout`、`case-world`、`characters`、`state-trajectory` 和 `story-beats`，把 beat skeleton 落成消息级 turn。

每个 turn 必须保留：

- `turn_id`
- `beat_id`
- `sequence_no`
- `session_id`
- `speaker_actor_id`
- `planned_message_text`
- `benchmark_role`
- family/state/evidence trace

`conversation-plan` 只负责 turn realization，不生成 `lark-cli` action。下游 `command-plan` 会把 turn 转成 `create_chat`、`send_message`、`reply_in_thread` 和 fetch actions。
