# collect

## 职责

这个 skill 负责从真实飞书会话回收 observed messages。它不创造数据，只根据 execute 阶段得到的真实 resource ids 执行 fetch。

## 读取

- execution result
- `created_resources`
- command plan 中的 fetch actions
- `input/characters.json`
- `input/actor_registry.json`

## 输出

- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`

## 如何回收

- chat messages 使用 `lark-cli im +chat-messages-list`。
- thread messages 使用 `lark-cli im +threads-messages-list`。
- fetch 必须基于真实 `chat_id / thread_id / message_id`。
- collected rows 必须保留 case、session、source、turn、actor 和 benchmark trace。
- collected rows 必须同时保留真实飞书 sender 与 benchmark simulated speaker。
- prefix `【department/name】` 只用于 collect 阶段解析人物，不作为 OpenClaw replay 的最终 sender。

## `collected_messages.jsonl`

这是 benchmark 的 observed data。它应能映射回：

- `case_id`
- `session_id`
- `source_type`
- `turn_id`
- `speaker_actor_id`
- `message_id`
- `thread_id`
- `benchmark_role`
- `actual_sender`
- `simulated_speaker`
- `normalized_actor_id`
- `speaker_resolution_mode`

## `openclaw_message_ingress.jsonl`

这是给 Task Wiki runtime replay 的输入。它来自真实 fetch 结果，不来自 LLM，也不来自 planned message。

输出必须是 OpenClaw Lark 可消费的 Feishu event-like shape：

- `sender.sender_id.open_id` 使用 `actor_registry.simulated_open_id`，不是真实 fetch sender。
- `message.content` 是 JSON string，例如 `{"text":"..."}`。
- `message.message_id / chat_id / thread_id / root_id / message_type / create_time / chat_type` 保留 replay 需要的字段。
- 文本中必须剥掉 `【department/name】` prefix，避免 OpenClaw 同时看到文本伪人名和 sender open id。

## 禁止

- 不要用 `conversation_plan` 直接生成 collected data。
- 不要在 fetch 失败时伪造空成功。
- 不要丢失 source/session/thread trace。
