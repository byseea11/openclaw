# execute

## 职责

这个 skill 负责真实执行 `command-plan` 生成的 action plan。它是 Phase 1 中第一个允许产生飞书 side effect 的阶段。

## 读取

- `input/command_plan.jsonl`
- execution plan
- lark-cli auth/preflight 状态

## 输出

- `runtime/executed_commands.jsonl`
- execution result
- `created_resources`

## 如何执行

- 执行前必须检查 `lark-cli auth status`。
- action 必须按 dependency graph 执行，不能只按 JSONL 原始顺序盲跑。
- `create_chat` 成功后记录 `chat_id`。
- `send_message` 成功后记录 `message_id`。
- `reply_in_thread` 成功后记录 `message_id`，并尽量记录 `thread_id`。
- 每个 action 都必须记录 stdout、stderr、returncode 和 status。

## Resource Ref 规则

- `output_ref` 是计划内稳定引用。
- 真实执行后要把 `output_ref` 映射到飞书返回的真实 id。
- 后续 action 使用真实 `chat_id / message_id / thread_id` 替换计划 ref。

## 下游作用

- `collect` 使用 execution result 中的真实 resource ids 执行 fetch。
- `pre-annotation-validate` 使用 execution trace 判断 planned turn 是否实际落地。

## 禁止

- 不要在 auth 失败时继续执行。
- 不要静默吞掉失败 action。
- 不要用 planned message 伪造执行成功。
