# command-plan

## 职责

这个 skill 负责把 `conversation_plan.json` 转成真实可执行的 `lark-cli` action plan。它不是故事生成阶段，而是执行计划生成阶段。

## 读取

- `input/conversation_plan.json`
- `input/characters.json`
- `input/actor_registry.json`
- source session refs

## 输出

- `input/command_plan.jsonl`

## 如何生成

每一行都是一个可执行 action row。至少支持：

- `create_chat`
- `send_message`
- `reply_in_thread`
- `fetch_chat_messages`
- `fetch_thread_messages`

人物来源只能来自 `characters.json / actor_registry.json`：

- `speaker_ref / sender_ref` 使用稳定 `person_id`。
- `params.content_text` 使用 `【department/name】正文`，其中 department/name 来自 actor registry。
- 不能从 `task_actor_layout.display_name / role` 直接拼 `【project_manager/Alice】` 这类调试标签。
- 如果 `conversation_plan` 引用了 registry 中不存在的 `person_id`，必须直接失败。

每个 action 必须包含：

- `action_type`
- `sequence_no`
- `session_id`
- `source_type`
- `speaker_actor_id` 或 `speaker_ref`
- `planned_message_text`
- `depends_on_step_ids`
- `output_ref`
- `benchmark_role`
- `family_id`
- `state_field_hints`
- `lark_cli_command`

## Lark CLI 语义

- `create_chat` 预览 `lark-cli im +chat-create`。
- `send_message` 预览 `lark-cli im +messages-send`。
- `reply_in_thread` 预览 `lark-cli im +messages-reply --reply-in-thread`。
- `fetch_chat_messages` 预览 `lark-cli im +chat-messages-list`。
- `fetch_thread_messages` 预览 `lark-cli im +threads-messages-list`。

`command-plan` 只生成 command preview 和 action dependency，不直接执行。

## Thread 依赖规则

- thread reply 必须依赖 chat 已创建。
- thread reply 必须依赖 root message 已发送。
- fetch thread 必须依赖 root message 或 thread id 已可解析。

## 下游作用

- `execute` 根据 action dependency graph 真正调用 `lark-cli`。
- `collect` 根据 fetch action 和 execution result 回收 observed messages。
- `pre-annotation-validate` 通过 benchmark trace fields 对齐 planned turn 与 observed message。

## 禁止

- 不要用自由文本描述替代 action row。
- 不要在本阶段真实调用 `lark-cli`。
- 不要丢失 `turn_id / benchmark_role / family_id / output_ref`。
