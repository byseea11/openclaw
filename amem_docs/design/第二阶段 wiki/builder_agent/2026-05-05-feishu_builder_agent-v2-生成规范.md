# 2026-05-05 `feishu_builder_agent` V2 生成规范

## 1. 目标

这份规范约束 V2 builder 如何从一个最小入口 spec，生成一套：

- 可以真实执行到飞书
- 可以被 OpenClaw replay / ingest
- 可以拿来评测 Task Wiki Layer 1/2/3

的 benchmark case。

这里的核心原则是：

- 规则库先决定结构
- LLM 再把结构展开成自然语言
- gold 最终必须回到真实 collected evidence

## 2. 两层配置边界

### 2.1 `feishu_builder_agent/templates/default_case_spec.json`

这是单个 case 的入口 spec，不是规则库本体。

它只负责：

- 选择 `scenario_profile`
- 提供 `difficulty`
- 提供 `seed`
- 提供可选 hints
  - `department_hints`
  - `title_hint`
  - `main_goal_hint`

它不负责承载：

- 全量部门池
- 全量 title 候选
- 全量 stakeholder / topic / session 规则

### 2.2 `feishu_builder_agent/templates/case_profile_catalog.json`

这是 builder 的唯一规则库。

它负责：

- profile 级部门池与必选部门
- title / goal 候选模板
- stakeholder / conflict / hidden constraint / reversal 模板
- topic 模板
- session layout 模板
- 角色模板
- 默认 complexity profile

补充：

- 这份 catalog 是仓库内的静态规则源文件
- 运行时默认直接读取它
- 如果需要扩展或重生成，可以通过：
  - `python3 -m feishu_builder_agent.cli generate-case-profile-catalog`
  - 使用 `.env` 中的 OpenAI 兼容配置（例如 DeepSeek）生成新的 catalog
- prompt 文件放在：
  - `feishu_builder_agent/prompts/case_profile_catalog_system.txt`
  - `feishu_builder_agent/prompts/case_profile_catalog_user.txt`
- prompt 不写进 `.env`
- `.env` 只负责模型凭证和调用配置

## 3. 各阶段如何生成

### 3.1 `case-world`

输入：

- `case_spec.json`

输出：

- `input/case_seed.json`
- `input/case_world.json`

规则层负责：

- 从 catalog 按 `scenario_profile + difficulty + seed` 采样：
  - departments
  - company_type
  - title
  - main_goal
  - stakeholders
  - conflict axes
  - hidden constraints
  - reversal points

LLM 负责：

- 把这些 sampled skeleton 展开成更自然的中文世界观

LLM 不允许：

- 擅自改变部门数量
- 擅自改变 topic/session 结构约束
- 擅自删除 required transitions

### 3.2 `characters`

输入：

- `case_spec.json`
- `input/case_seed.json`
- `input/case_world.json`

输出：

- `input/characters.json`
- `input/actor_registry.json`

规则层负责：

- 从 catalog 的 `character_role_templates` 里按 sampled departments 选角色模板
- 生成稳定：
  - `person_id`
  - `simulated_open_id = ou_sim_<person_id>`

LLM 负责：

- 在规则角色模板的边界内细化人物表达

`actor_registry.json` 是运行时角色映射表，后续：

- `collect`
- `adapt`
- `validate`

都只读这张表，不再自行拼 actor identity。

### 3.3 `conversation-plan`

输入：

- `input/case_seed.json`
- `input/case_world.json`
- `input/characters.json`

输出：

- `input/conversation_plan.json`

规则层负责：

- 从 catalog 里采样：
  - `topic_templates`
  - `session_layout_templates`
- 先生成 plan skeleton：
  - `topic_registry`
  - `sessions`
  - `turns`

fallback 不能再写死一整套固定 topic/session/turn 集合，而是必须从 catalog 组装。

LLM 负责：

- 在既有 topic / session / actor 约束下补充自然语言 turn 内容

### 3.4 `gold`

输入：

- `gold/target_state.json`
- `data/collected_messages.jsonl`
- `input/conversation_plan.json`

输出：

- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`

gold 分两层：

1. `target_state`
   - 先定义希望这个 case 最终形成哪些 topics、blocks、current state、state transitions
2. evidence-bound gold
   - 执行和 collect 完成后，再把 gold 绑定到真实 evidence

`expected_events.jsonl` 要对齐 Layer 2 `session_event` 结构，至少包括：

- `event_id`
- `task_ref`
- `source_session_id`
- `ingest_version`
- `event_type`
- `claim`
- `core_entry_id`
- `evidence_quote`
- `context_quotes`
- `participants`
- `event_time`
- `source`
- typed event fields
- `verification`
- `gold_meta`

builder 自己的附加字段只能进 `gold_meta`，不能污染主 schema。

## 4. `simulated_open_id` 和 actor registry

`simulated_open_id` 的职责固定为：

- benchmark / replay 中的稳定“模拟工号”
- 最终映射到 `openclaw_message_ingress.jsonl` 的标准 Feishu 字段：
  - `sender.sender_id.open_id`

注意：

- 它不等价于真实飞书用户 `open_id`
- 真实发送者只在 `data/collected_messages.jsonl` 里保留为 `actual_sender`

最终职责边界：

- `characters.json`
  - 角色画像主数据
- `actor_registry.json`
  - 运行时身份映射表
- `collected_messages.jsonl`
  - 同时保留 `actual_sender + simulated_speaker`
- `openclaw_message_ingress.jsonl`
  - 只保留标准 Feishu 事件字段，使用映射后的 `sender.sender_id.open_id`

## 5. 为什么 `validate` 独立存在

每个阶段结束后都要做本阶段本地校验：

- schema
- 必填字段
- 前置依赖
- actor 映射完整性

单独的 `validate` 阶段不是重复做 schema 校验，而是做跨阶段一致性审计：

- `conversation_plan` 是否真的被 `command_plan` 覆盖
- `command_plan` 是否真的执行成功
- `collect` 是否拿回了目标 source session
- `target_state` 是否真的绑定到了 collected evidence
- complexity gate 是否达标

## 6. 一句话结论

V2 builder 的生成规则不是“先写聊天，再补结构”，而是：

> 先用 catalog 定义可控结构，再用 LLM 细化语言，最后把 gold 绑定到真实证据。
