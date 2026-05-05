# 2026-05-01 `feishu_builder_agent` 当前实现说明

## 1. 当前定位

`feishu_builder_agent` 当前已经是 **纯 V2 Builder**。

它现在不是“先写几条消息，再顺手拼一个 execution plan”的旧式 case 编译器，而是一个围绕 Task Wiki 评测目标构建的企业协作数据集生成器，负责同时产出：

1. V2 case 输入对象
2. 可执行的飞书动作计划
3. 真实飞书消息回收产物
4. 可追溯的 gold / checks
5. 可供 OpenClaw 消费的 ingress / report

默认数据根目录：

- `amem_docs/ds/feishu_im_dataset_v2`

默认执行模式仍然是：

- `operator_identity = "user"`
- `delivery_mode = "prefixed_single_operator"`

也就是：

- 真实飞书里仍由同一个用户发消息
- 多角色差异通过消息前缀表达
- 但 case world、conversation plan、target gold、command plan、collected evidence 都已经是 V2 对象

## 2. 当前公开主链

当前 Builder 的真实公开阶段链是：

```text
case_spec
  -> case-world
  -> characters
  -> plan
  -> target-gold
  -> command-plan
  -> execute
  -> collect
  -> gold
  -> validate
  -> adapt
  -> full
```

其中关键语义是：

- `target-gold`
  - 先定义这个 case 期望形成什么 topic / block / current state
- `command-plan`
  - 先生成真正要执行的 `lark-cli` 动作
- `collect`
  - 再拉回真实飞书消息
- `gold`
  - 最后把 target state 绑定到真实 evidence

因此，当前主链已经不是过去那种旧式链路：

```text
conversation_plan -> utterance_plan -> realized_messages -> execution_plan
```

而是：

```text
conversation_plan -> target_state -> command_plan -> execution_plan -> execute -> collect -> evidence-bound gold
```

## 3. 当前关键文件

当前实现里最关键的几层文件是：

- 生成层
  - `feishu_builder_agent/case_world_generator.py`
  - `feishu_builder_agent/character_generator.py`
  - `feishu_builder_agent/conversation_plan_generator.py`
  - `feishu_builder_agent/command_plan_generator.py`
  - `feishu_builder_agent/target_gold_generator.py`
- 运行层
  - `feishu_builder_agent/plan_mapper.py`
  - `feishu_builder_agent/executor.py`
  - `feishu_builder_agent/collector.py`
  - `feishu_builder_agent/collected_message_builder.py`
- 评测层
  - `feishu_builder_agent/gold_generator.py`
  - `feishu_builder_agent/complexity_validator.py`
  - `feishu_builder_agent/dataset_validator.py`
- 入口层
  - `feishu_builder_agent/cli.py`
  - `amem_docs/scripts/feishu-builder-agent-run.sh`

## 4. 当前 case 目录结构

一个 case 当前落盘为：

```text
amem_docs/ds/feishu_im_dataset_v2/
  dataset_manifest.json
  cases/
    <case_id>/
      case_spec.json
      input/
        case_seed.json
        case_world.json
        characters.json
        conversation_plan.json
        command_plan.jsonl
      gold/
        target_state.json
        expected_events.jsonl
        expected_memory_blocks.json
        expected_current_state.json
      data/
        collected_messages.jsonl
      checks/
        conversation_complexity_report.json
        dataset_validation_report.json
      execution_plan.json
      execution_result.json
      lark_fetch_records.jsonl
      openclaw_message_ingress.jsonl
      adapter_report.json
      build_report.json
```

## 5. 当前 canonical 中间对象

### 5.1 `input/case_seed.json`

最小输入种子，定义：

- case 基本身份
- main goal
- complexity profile

### 5.2 `input/case_world.json`

定义：

- 组织背景
- 外部压力
- conflict axes
- hidden constraints
- reversal points

### 5.3 `input/characters.json`

角色对象至少包含：

- `person_id`
- `simulated_open_id`
- `name`
- `department`
- `role`
- role / responsibility
- stance
- risk_preference
- information_access_level
- default_channels

其中：

- `person_id` 是角色稳定主键
- `simulated_open_id` 是这套 benchmark 的模拟工号
- 当前规则固定为：`simulated_open_id = ou_sim_<person_id>`
- 后续 `collect` 和 `adapt` 只能从这里读取模拟身份映射，不能再临时拼接 synthetic sender id

### 5.4 `input/conversation_plan.json`

定义：

- topic_registry
- sessions
- turns

它回答的是：

- 这个 case 准备怎么展开
- 会在哪些 source session 里推进
- 哪些 topic 会发生 supersession / cross-source revision

### 5.5 `gold/target_state.json`

这是 target gold。

它先定义：

- 预期 topic
- 预期 Memory Block
- 预期 current state
- required event coverage
- required state transitions
- required cross-source revisions

### 5.6 `input/command_plan.jsonl`

这是当前 V2 的核心执行对象。

每条记录表示一个逻辑飞书动作，至少包含：

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

也就是说：

- V2 先生成“要执行什么飞书动作”
- 再由程序编译成 `execution_plan.json`
- 而不是先生成消息文本再反推执行计划

### 5.7 `execution_plan.json`

这是程序真正执行的运行层对象。

它把 `command_plan.jsonl` 编译成：

- `create_chat`
- `send_message`
- `reply_in_thread`
- `fetch_chat_messages`
- `fetch_thread_messages`

等实际动作。

### 5.8 `lark_fetch_records.jsonl`

记录 collect 阶段从真实飞书拉回的原始结果。

### 5.9 `data/collected_messages.jsonl`

这是当前 evidence-bound gold 的直接输入。

它表示：

- 哪些 command step 真正变成了消息
- 最终 message_id 是什么
- 内容文本是什么
- 这些内容来自 fetch records 还是 execution result 补全

### 5.10 `gold/*`

当前 final gold 是：

- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`

它们必须建立在：

- `target_state.json`
- `conversation_plan.json`
- `collected_messages.jsonl`

之上，而不是简单镜像计划层。

## 6. 当前 `validate` 的真实语义

当前 `validate` 不是“补做 schema 校验”。

当前实现里：

- 每个阶段结束后都会做本阶段本地校验
- `validate` 阶段只做**跨阶段一致性审计**

它重点检查：

- `conversation_plan` 是否真的被 `command_plan` 覆盖
- `command_plan` 是否真的生成了可执行 `execution_plan`
- `collect` 是否拿回了真实消息
- `gold` 是否能回到 collected evidence
- 复杂度是否达标
- case 是否适合作为评测样本

## 7. 真实 FEISHU-231 链路验证

当前已经用真实飞书环境对 `case_feishu_231_example` 跑通过一条完整链路。真实 case 目录在：

- `amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example`

这次真实执行覆盖了：

```text
command-plan
-> execute
-> collect
-> gold
-> validate
-> adapt
```

### 7.1 真实执行结果

`execution_result.json` 当前已经是成功状态：

- `status = success`
- `25` 个动作全部成功
- `failed_steps = []`
- 创建了 2 个真实飞书群：
  - `main_chat.chat_id = oc_5b4e3cb2fb47f71a2f99fb7f911deb5b`
  - `customer_sync_chat.chat_id = oc_0864449792c12588a5040c6a60334a75`

这也说明当前执行器已经能正确从真实 `lark-cli` 返回里的嵌套 `data.chat_id` 写回 `created_resources`。

### 7.2 真实 collect 结果

`collect-case` 真实运行后：

- `lark_fetch_records.jsonl` 中共有 `3` 条 fetch 记录
- `data/collected_messages.jsonl` 中共有 `20` 条 builder 关心的文本消息

当前 `collected_messages.jsonl` 已经不只是“收回消息文本”，而是 builder 后续 gold / validate / replay 的 canonical 输入。每条记录同时保留：

- `actual_sender`
- `simulated_speaker`
- `normalized_actor_id`
- `speaker_resolution_mode`
- `prefix_speaker_hint`

因此，当前 builder 已经支持：

- 执行层只有 1 个真实用户发消息
- 评测层再把这些消息稳定切回多角色语义

### 7.3 真实 validate 结果

`validate-case` 当前对这条真实 case 的结果是通过的：

- `checks/conversation_complexity_report.json`
  - `passed = true`
- `checks/dataset_validation_report.json`
  - `passed = true`

当前这条真实 case 的关键指标是：

- `session_count = 3`
- `source_session_count = 3`
- `message_count = 20`
- `topic_count = 4`
- `thread_reply_depth = 6`
- `supersession_count = 3`
- `cross_source_revision_count = 4`
- `event_family_coverage = 8`
- `unique_actual_senders = 1`
- `unique_normalized_actors = 6`

### 7.4 真实 adapt / replay 结果

`adapt-case` 当前也已经恢复正常：

- `adapter_report.output_events = 20`
- `adapter_report.skipped_messages = 4`
- `build_report.num_openclaw_ingress_events = 20`
- `warnings = []`

这里跳过的 `4` 条消息是系统消息，不是异常：

- `Welcome to {group_type}`
- `started the group chat`

这些 `msg_type != text` 的消息本来就不应该进入 Task Wiki 评测主链。

### 7.5 当前真实中间产物应该重点看什么

如果后面要人工检查这条真实 case，优先看这几类文件：

- 执行层
  - `execution_plan.json`
  - `execution_result.json`
- 证据层
  - `lark_fetch_records.jsonl`
  - `data/collected_messages.jsonl`
- gold 层
  - `gold/target_state.json`
  - `gold/expected_events.jsonl`
  - `gold/expected_memory_blocks.json`
  - `gold/expected_current_state.json`
- 审计层
  - `checks/conversation_complexity_report.json`
  - `checks/dataset_validation_report.json`
- replay/report 层
  - `openclaw_message_ingress.jsonl`
  - `adapter_report.json`
  - `build_report.json`

## 8. 当前真实边界

当前已经完成的：

- 纯 V2 数据根
- 严格分阶段 CLI
- `target_state` 两层 gold
- `command_plan -> execution_plan`
- `collect -> collected_messages`
- `gold -> expected_*`
- `validate` 的跨阶段审计语义

当前还没继续做的：

- 批量 case 生成 orchestration
- `locomo` complexity calibrator
- 批量 scoring / baseline 对比链
- 更强的人工 review / gold 修订工作流

一句话总结：

> 当前 `feishu_builder_agent` 已经是一条以 `command_plan` 和 `collected evidence` 为中心的纯 V2 Builder 主链，而不是旧的消息先行编译器。
