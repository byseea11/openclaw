# 2026-05-01 `feishu_builder_agent` 当前实现说明

## 1. 当前定位

`feishu_builder_agent` 当前已经按 **纯 V2 口径**运行。

它现在不是“固定 case 的 IM 编译器”，而是一个面向 Task Wiki 的企业协作数据集构建器，负责同时产出：

1. 可控的 V2 case 输入对象
2. 可执行的飞书 IM 执行动作
3. 可供 OpenClaw 消费的 ingress 数据
4. 可供评测的 gold / checks 产物

当前默认输出根目录是：

- `amem_docs/ds/feishu_im_dataset_v2`

当前默认执行模式仍然保持：

- `operator_identity = "user"`
- `delivery_mode = "prefixed_single_operator"`

也就是：

- 飞书里真正发消息的是同一个真实用户
- 多角色差异通过消息前缀表达
- 但 case 世界观、会话计划、gold current state 都已经是 V2 对象

## 2. 当前目录结构

当前实现目录如下：

```text
feishu_builder_agent/
  __init__.py
  cli.py
  config.py
  schemas.py
  io_utils.py
  llm_client.py
  case_world_generator.py
  story_generator.py
  character_generator.py
  timeline_planner.py
  conversation_plan_generator.py
  utterance_generator.py
  message_realizer.py
  complexity_validator.py
  gold_generator.py
  dataset_validator.py
  plan_mapper.py
  executor.py
  collector.py
  adapter.py
  build_report.py
  prompts/
  templates/
  tests/
```

其中关键分层已经是：

- 生成层：
  - `case_world_generator.py`
  - `character_generator.py`
  - `conversation_plan_generator.py`
  - `utterance_generator.py`
  - `message_realizer.py`
- 校验层：
  - `schemas.py`
  - `complexity_validator.py`
  - `gold_generator.py`
  - `dataset_validator.py`
- 执行层：
  - `plan_mapper.py`
  - `executor.py`
  - `collector.py`
  - `adapter.py`

## 3. 当前主流程

当前 Builder 的主流程是：

```text
case_spec.json
  -> case_seed.json
  -> case_world.json
  -> characters.json
  -> conversation_plan.json
  -> utterance_plan.jsonl
  -> realized_messages.jsonl
  -> expected_events / expected_memory_blocks / expected_current_state
  -> conversation_complexity_report / dataset_validation_report
  -> execution_plan.json
  -> execute-case
  -> collect
  -> adapt-case
```

当前 `compile-case` 的职责已经是：

1. 生成 V2 输入对象
2. 生成 V2 gold 与 checks
3. 再把 `realized_messages` 映射成 `execution_plan.json`

也就是说，`execution_plan.json` 现在是 **V2 运行飞书链路所需的执行对象**，不是为了保留旧目录结构而存在的兼容残留。

## 4. 当前 case 产物结构

一个 case 当前会落到：

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
        utterance_plan.jsonl
      data/
        realized_messages.jsonl
      gold/
        expected_events.jsonl
        expected_memory_blocks.json
        expected_current_state.json
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

当前不会再默认额外落这些旧层文件：

- `story.json`
- `characters.json`
- `conflict_timeline.json`

如果后续需要保留它们，应该作为调试辅助对象重新定义，而不是再当成默认主契约。

## 5. 当前关键对象

### 5.1 `input/case_seed.json`

最小输入种子，定义：

- `case_id`
- `task_id`
- `domain`
- `company_type`
- `departments`
- `main_goal`
- `difficulty`
- `seed`
- `complexity_profile`

### 5.2 `input/case_world.json`

定义这个 case 的企业协作世界观，至少包含：

- 组织背景
- 外部压力
- stakeholders
- conflict axes
- hidden constraints
- reversal points

### 5.3 `input/characters.json`

角色对象已经不是简单 roster，至少包含：

- `person_id`
- `name`
- `department`
- `role`
- `responsibility`
- `communication_style`
- `conflict_bias`
- `stance`
- `risk_preference`
- `information_access_level`
- `default_channels`

### 5.4 `input/conversation_plan.json`

当前 V2 的核心对象，定义：

- `topic_registry`
- `sessions`
- `turns`

它决定：

- 有几个 source session
- 每个 topic 如何跨群 / thread 推进
- 哪些 turn 会触发 supersession
- 哪些 turn 会带出 blocker / objection / commitment / status update

### 5.5 `input/utterance_plan.jsonl`

把 conversation plan 收成每轮消息的结构化计划，每行至少有：

- `turn_id`
- `sequence_no`
- `session_id`
- `source_type`
- `source_ref`
- `chat_ref`
- `speaker_ref`
- `topic_key`
- `turn_purpose`
- `supports_event_types`
- `references_previous_turns`
- `state_transition`
- `semantic_payload`
- `root_turn_id`

### 5.6 `data/realized_messages.jsonl`

在 utterance plan 的基础上生成真实飞书消息文本。

这是后续：

- gold evidence
- execution plan
- lark-cli execute

的共同输入。

### 5.7 `gold/*`

当前 gold 层包括：

- `expected_events.jsonl`
- `expected_memory_blocks.json`
- `expected_current_state.json`

职责分别是：

- 定义期望被抽出的 typed events
- 定义期望形成的 Memory Blocks
- 定义最终 task 当前态

### 5.8 `checks/*`

当前检查层包括：

- `conversation_complexity_report.json`
- `dataset_validation_report.json`

前者判断复杂度是否达标，后者判断：

- schema 是否完整
- gold 是否能回链到消息
- 对象间引用是否一致

## 6. 执行链路

当前真实执行链路仍然是：

1. `execution_plan.json`
2. `execution_result.json`
3. `lark_fetch_records.jsonl`
4. `openclaw_message_ingress.jsonl`

它们的职责分别是：

- `execution_plan.json`
  - 把 `realized_messages` 映射成飞书动作
- `execution_result.json`
  - 记录真实创建出来的 chat / message / thread 资源
- `lark_fetch_records.jsonl`
  - 从飞书拉回的原始消息
- `openclaw_message_ingress.jsonl`
  - OpenClaw 可直接消费的 ingress 事件流

这里仍然保持 IM-only：

- `chat`
- `thread`

`comment / doc` 还没有进入 Builder 的第一批 live 执行面。

## 7. 当前脚本入口

当前统一脚本在：

- `amem_docs/scripts/feishu-builder-agent-run.sh`

当前支持的阶段已经是：

- `case-world`
- `plan`
- `utterance`
- `realize`
- `gold`
- `validate`
- `compile`
- `execute`
- `collect`
- `adapt`
- `full`

## 8. 当前已验证状态

当前已经实际验证过：

- Builder 单测：
  - `feishu_builder_agent/tests/test_e2e.py`
  - `feishu_builder_agent/tests/test_live_language.py`
  - `feishu_builder_agent/tests/test_mapper.py`
  - `feishu_builder_agent/tests/test_schemas.py`
  - `feishu_builder_agent/tests/test_executor.py`
  - `feishu_builder_agent/tests/test_adapter.py`
- `python3 -m compileall feishu_builder_agent`
- `amem_docs/scripts/feishu-builder-agent-run.sh --phase compile`
- `amem_docs/scripts/feishu-builder-agent-run.sh --phase validate`

并且当前真实 case 已经成功落到：

- `amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example`

## 9. 当前边界

当前仍然保留的边界有：

1. `locomo` 目前只作为复杂度和生成结构参考，还没有接成独立 calibrator。
2. 当前 gold 还是由规则主导生成，后续可以再加人工 review / edit 流程。
3. 评测打分层还没继续补完，例如：
   - baseline 汇总
   - case scoring
   - batch evaluation
4. 当前 live 执行仍然是单 operator + 前缀角色模式，不是多账号 impersonation。

## 10. 一句话结论

当前 `feishu_builder_agent` 已经是：

> 一个默认落盘到 `amem_docs/ds/feishu_im_dataset_v2`、以 `case_world / conversation_plan / realized_messages / gold / checks` 为主契约、并可继续真实执行飞书链路的纯 V2 Builder。
