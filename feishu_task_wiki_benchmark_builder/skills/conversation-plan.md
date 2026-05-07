# conversation-plan

## 职责

这个 skill 负责定义 phase1 的 turn realization owner。它把 actor、session、beat skeleton 绑定成完整企业 transcript，并使用结构化 speaker 引用，后续 `command-plan` 只做 compile。

## 硬规则

- 必须产出：
  - `case_id`
  - `family_id`
  - `task_id`
  - `sessions`
  - `turns`
- 每个 turn 至少包含：
  - `turn_id`
  - `beat_id`（仅 annotation target / required coverage turn 必填）
  - `sequence_no`
  - `session_id`
  - `speaker_actor_id`
  - `speaker`
  - `planned_message_text`
  - `turn_kind`
  - `annotation_target`
  - `event_bearing`
- `speaker_actor_id` 必须引用上一步 actor roster。
- `speaker` 必须与对应 actor 的 `display_name` 一致。
- `session_id` 必须引用上一步 session roster。
- 当前正式路径必须由 LLM 生成完整 transcript；规则模板扩句只能作为 fixture/fallback，不是正式数据集质量来源。
- hard case 必须像真实企业协作，包含不同措辞、不同角色意图和不同信息密度。
- `planned_message_text` 每条默认控制在 45 个中文字符以内，避免单次 JSON 输出被模型截断。
- hard case 默认输出 difficulty 下限数量即可，例如 hard 输出 80 turns，不要为了显得复杂主动扩到 120。
- 不允许模板刷屏。
- 禁止出现“企业协作补充事实 N”“收到，我先按这个口径记录”这类模板刷屏。
- 应吸收旧版 `conversation_plan_generator.py` 的思路：
  - `speaker_ref` 是结构化引用
  - session placement 先按 benchmark role / session preference 决定
  - turn ordering 先定，再下游 compile

## 禁止

- 不要用自由文本 speaker 充当唯一执行引用。
- 不要在本阶段创造新的 actor / session / beat；可以把 required beat 扩展成多条真实企业 turn。
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
      "planned_message_text": "我刚确认过，窗口今天还没锁定，所以 FEISHU-203 先不要对外承诺上线时间。",
      "turn_kind": "event_bearing",
      "annotation_target": true,
      "event_bearing": true
    },
    {
      "turn_id": "turn_002",
      "beat_id": "",
      "sequence_no": 2,
      "session_id": "main_chat",
      "speaker_actor_id": "alice",
      "speaker": "Alice",
      "planned_message_text": "我把这个先标成待确认，不会同步成正式结论，等 Carol 的窗口邮件回来再更新任务页。",
      "turn_kind": "ack_or_coordination",
      "annotation_target": false,
      "event_bearing": false
    }
  ]
}
```

## V3 Phase 1 对接位置

在细分 Phase 1 链路里，`conversation-plan` 读取 `task-actor-layout`、`case-world`、`characters`、`actor_registry`、`state-trajectory`、`story-beats` 和 `official_file_plan`，把少量 required beat skeleton 扩展成完整企业 transcript。

难度规模必须来自 `builder_settings.yml`：

- `easy`：`25-40` turns。
- `medium`：`50-80` turns。
- `hard`：`80-120` turns。

`story-beats` 不等于全量消息。它只定义必须落地的 coverage；`conversation-plan` 负责补齐 context、interference、ack、revision bridge 和跨 session 转述。

完整 transcript 至少要包含：

- 核心事实。
- 状态更新。
- 跨 session 转述。
- 正式文件引用。
- 误导信息。
- ack。
- 追问。
- 纠偏。
- 总结。

每个 turn 必须保留：

- `turn_id`
- `beat_id`
- `sequence_no`
- `session_id`
- `speaker_actor_id`
- `planned_message_text`
- `turn_kind`
- `annotation_target`
- `event_bearing`
- `benchmark_role`
- `official_file_ref`
- `private_info_ref`
- `task_relevance_boundary`
- family/state/evidence trace

`conversation-plan` 只负责 turn realization，不生成 `lark-cli` action。下游 `command-plan` 会把所有 turn 转成 `create_chat`、`send_message`、`reply_in_thread` 和 fetch actions；OpenClaw replay 会看到完整 transcript，而 annotation gold 只消费 `annotation_target=true` 或 `event_bearing=true` 的行。
