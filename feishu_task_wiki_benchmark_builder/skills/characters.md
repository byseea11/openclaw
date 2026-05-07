# characters

## 职责

这个 skill 负责把 `task-actor-layout` 中已经声明的 actor slots 实例化为可执行人物，并生成稳定的 actor registry。

## 读取

- `input/task_actor_layout.json`
- `input/case_world.json`
- 当前 family context skill

## 输出

- `input/characters.json`
- `input/actor_registry.json`

## 如何生成

- `characters.json` 负责人物自然化，包括姓名、部门、角色、profile 和默认参与 source。
- `actor_registry.json` 负责执行稳定性，包括 `person_id`、`simulated_open_id`、姓名、部门、角色、默认 source 和后续 execute/collect 引用。
- 人物必须来自 `task-actor-layout` 已声明的 actor slots。
- `person_id` 默认等于上游 `actor_id`，不能由 LLM 改名。
- `simulated_open_id` 固定为 `ou_sim_<person_id>`，由 builder 系统侧生成，不来自真实飞书 fetch。
- `actor_registry.json` 使用 `actors[]` list 结构，供 command-plan、collect 和 OpenClaw replay ingress 稳定查表。
- 可以自然化 `name/profile`，但不能删除或替换上游定义的结构身份。

## 下游作用

- `conversation-plan` 使用 characters 选择 speaker。
- `command-plan` 使用 actor registry 生成 `speaker_ref / sender_ref` 和 `【department/name】` message prefix。
- `execute` 仍由单 operator 调用真实 `lark-cli`，不尝试 impersonate 多个飞书用户。
- `collect` 使用 actor registry 把真实 sender 与 benchmark simulated speaker 对齐。
- `openclaw_message_ingress.jsonl` 使用 `simulated_open_id` 作为 `sender.sender_id.open_id`。

## 禁止

- 不要新增未在 `task-actor-layout` 中出现的核心 actor。
- 不要把 shared actor 改成另一个人。
- 不要让 profile 覆盖 family context 中定义的证据、修正或干扰职责。
