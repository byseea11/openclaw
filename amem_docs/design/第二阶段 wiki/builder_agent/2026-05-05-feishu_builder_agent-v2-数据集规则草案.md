# 2026-05-05 `feishu_builder_agent` V2 数据集规则草案

## 1. 目标

V2 Builder 的目标不是简单生成一串聊天文本，而是生成一套同时满足下面三件事的数据：

1. 可以真实执行到飞书
2. 可以被 OpenClaw ingest / replay
3. 可以拿来评测 Task Wiki 的 event / block / current state 能力

因此，V2 数据集规则必须围绕：

- world
- conversation
- command
- collected evidence
- gold

这五层来定义。

## 2. 当前主契约

当前 V2 主契约固定为：

- `input/case_seed.json`
- `input/case_world.json`
- `input/characters.json`
- `input/conversation_plan.json`
- `gold/target_state.json`
- `input/command_plan.jsonl`
- `execution_plan.json`
- `execution_result.json`
- `lark_fetch_records.jsonl`
- `data/collected_messages.jsonl`
- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`
- `checks/conversation_complexity_report.json`
- `checks/dataset_validation_report.json`

`utterance_plan.jsonl` 和 `realized_messages.jsonl` 不再作为公开主契约。

## 3. 多轮复杂度规则

一个合格的 V2 case 至少应该满足：

- `session_count >= 3`
- `source_session_count >= 3`
- `message_count >= 18`
- `topic_count >= 3`
- `thread_reply_depth >= 3`
- `state_transition_count >= 4`
- `supersession_count >= 1`
- `cross_source_revision_count >= 1`
- `event_family_coverage >= 5`

复杂度的目标不是“消息多”，而是：

- 有 topic 交错
- 有角色博弈
- 有状态演化
- 有跨 source 修正
- 有 current state 收敛压力

## 4. 角色规则

`characters.json` 至少要表达：

- role / responsibility
- stance
- risk_preference
- information_access_level
- default_channels

也就是 builder 里的角色不应该只是“产品/研发/运维”标签，而应该能决定：

- 谁推动
- 谁反对
- 谁要求收紧口径
- 谁会在后续改写当前状态

## 5. 会话规则

`conversation_plan.json` 至少要表达：

- `topic_registry`
- `sessions`
- `turns`

其中要明确：

- 哪些 topic 在主群推进
- 哪些 topic 进入 thread 深挖
- 哪些 topic 会在另一个 source session 里被修正
- 哪些 turn 应该触发 supersession

## 6. 命令规则

V2 当前不再以“先生成消息”作为主阶段，而是以“先生成动作计划”为主。

`input/command_plan.jsonl` 每条至少要表达：

- `step_id`
- `action_type`
- `channel_scope`
- `topic_key`
- `turn_purpose`
- `speaker_role`
- `lark_cli_command`
- `expected_effect`
- `depends_on_step_ids`
- `gold_intent_refs`

命令计划的规则是：

- 必须能稳定编译成 `execution_plan.json`
- 依赖关系必须明确
- thread reply 不能先于 root message
- fetch 动作必须被显式建模，不能靠 collect 阶段临时猜

## 7. Gold 规则

Gold 拆两层：

### 7.1 `gold/target_state.json`

先定义：

- 预期 topic
- 预期 block
- 预期 current state
- required event coverage
- required state transitions
- required cross-source revisions

### 7.2 evidence-bound gold

执行和 collect 完成后，再生成：

- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`

要求：

- 每条 gold event 都能回到真实 collected message
- current state 必须来自真实 evidence，而不是只镜像计划层

## 8. validate 规则

`validate` 的语义固定为：

- 每个阶段先做本阶段本地校验
- `validate` 再做跨阶段一致性审计

`validate` 至少要检查：

- `conversation_plan` 是否被 `command_plan` 覆盖
- `command_plan` 是否成功编译并执行
- `collect` 是否拿回真实 source session
- gold 是否能回到 collected evidence
- complexity gate 是否通过

## 9. 一句话结论

V2 数据集规则的核心不是“生成更长的聊天”，而是：

> 生成一组先有目标、再有动作、再有真实证据、最后有可评测 gold 的企业协作 case。
