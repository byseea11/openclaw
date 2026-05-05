# 2026-05-05 `feishu_builder_agent` V2 实现详解

## 1. 当前定位

`feishu_builder_agent` 当前是一个面向 Task Wiki 评测的数据集构建器。

它的目标不是简单“编几条飞书消息”，而是稳定产出一整套可执行、可回收、可评测、可 replay 的企业协作 case。

当前它要同时满足四件事：

1. 生成真实可执行的飞书动作链
2. 拉回真实飞书消息与 source metadata
3. 生成对齐 Layer 2 / Layer 3 的 gold
4. 生成 OpenClaw 可消费的 ingress 产物

当前默认数据根目录：

- `amem_docs/ds/feishu_im_dataset_v2`

当前默认执行模式：

- `operator_identity = "user"`
- `delivery_mode = "prefixed_single_operator"`

也就是说：

- 真实飞书里仍由一个真实用户发消息
- 多角色语义通过 builder 的 `characters / actor_registry / collect / adapt` 这一套链路抬升出来

---

## 2. 当前主链

当前公开阶段链是：

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

这条链的真实含义是：

- 先定义 case 的结构目标
- 再定义角色与会话计划
- 再编译成可执行飞书动作
- 再执行并回收真实消息
- 再把 target state 绑定到真实 evidence

所以当前 V2 已经不是旧思路：

```text
story -> timeline -> realized_messages -> execution_plan
```

而是：

```text
catalog -> case_seed/world -> characters -> conversation_plan
-> target_state -> command_plan -> execution_plan
-> execute -> collect -> gold -> validate -> adapt
```

---

## 3. 当前关键输入输出

一个 case 当前的关键目录结构是：

```text
cases/<case_id>/
  case_spec.json
  input/
    case_seed.json
    case_world.json
    characters.json
    actor_registry.json
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

### 3.1 `case_spec.json`

这是单个 case 的入口 spec。

当前它不是规则库本体，而只是最小入口，负责：

- `scenario_profile`
- `difficulty`
- `seed`
- 可选 hints
  - `department_hints`
  - `title_hint`
  - `main_goal_hint`

### 3.2 `input/case_seed.json`

这是规则采样后的最小种子对象。

它已经不是“用户原始输入”，而是 builder 运行后得到的 resolved seed。

至少包含：

- `case_id`
- `task_id`
- `title`
- `domain`
- `company_type`
- `departments`
- `scenario_profile`
- `main_goal`
- `difficulty`
- `seed`
- `complexity_profile`

### 3.3 `input/case_world.json`

定义 case 的组织背景和冲突世界观，至少包括：

- `organization_background`
- `external_pressure`
- `stakeholders`
- `conflict_axes`
- `hidden_constraints`
- `reversal_points`

### 3.4 `input/characters.json`

定义角色画像，至少包括：

- `person_id`
- `simulated_open_id`
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

### 3.5 `input/actor_registry.json`

这是运行时角色映射表。

后续：

- `collect`
- `adapt`
- `validate`

都只应该消费这张表，不应该再自行拼角色工号。

### 3.6 `input/conversation_plan.json`

这是会话结构层，至少包括：

- `topic_registry`
- `sessions`
- `turns`

它决定：

- 哪些 topic 会出现
- 会落在哪些 source session
- 哪些状态会发生 supersession / cross-source revision

### 3.7 `gold/target_state.json`

这是 target gold。

它先定义：

- 预期 topics
- 预期 block targets
- 预期 current state targets
- required event coverage
- required state transitions
- required cross-source revisions

### 3.8 `input/command_plan.jsonl`

这是 V2 当前的核心动作对象。

每条记录至少包括：

- `step_id`
- `action_type`
- `session_id`
- `source_type`
- `source_ref`
- `channel_scope`
- `chat_ref`
- `topic_key`
- `turn_purpose`
- `speaker_role`
- `speaker_ref`
- `supports_event_types`
- `depends_on_step_ids`
- `gold_intent_refs`
- `expected_effect`
- `state_transition`
- `semantic_payload`
- `params`
- `lark_cli_command`

### 3.9 `execution_plan.json`

这是运行层动作计划，供执行器直接消费。

### 3.10 `data/collected_messages.jsonl`

这是 evidence-bound gold 的直接输入。

它保留了两层身份：

- `actual_sender`
- `simulated_speaker`

以及：

- `normalized_actor_id`
- `speaker_resolution_mode`

### 3.11 `gold/expected_events.jsonl`

这是最终 gold 的事件层。

当前目标是尽量对齐 Layer 2 `session_event`，至少包括：

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

### 3.12 `openclaw_message_ingress.jsonl`

这是给 `openclaw-lark` replay 的最终输入。

它只保留标准 Feishu 事件字段，不保留 builder 自己的扩展顶层字段。

多角色模拟通过标准字段传入：

- `sender.sender_id.open_id = simulated_open_id`

---

## 4. 规则库与 prompt 边界

### 4.1 规则库

当前唯一规则库是：

- `feishu_builder_agent/templates/case_profile_catalog.json`

它不是运行时生成的 case 产物，而是仓库内静态规则源。

当前至少定义：

- `scenario_profiles`
- `department_pool`
- `must_include_departments`
- `department_count_by_difficulty`
- `title_templates`
- `main_goal_templates`
- `stakeholder_templates`
- `conflict_axis_templates`
- `hidden_constraint_templates`
- `reversal_point_templates`
- `topic_templates`
- `session_layout_templates`
- `character_role_templates`
- `default_complexity_profile_by_difficulty`

### 4.2 catalog 生成

当前也支持通过 LLM 生成或刷新 catalog：

- 命令：
  - `python3 -m feishu_builder_agent.cli generate-case-profile-catalog`

模型配置来自：

- `.env`

例如：

- `OPENAI_API_KEY`
- `OPENAI_API_BASE_URL`
- `FEISHU_BUILDER_MODEL`

### 4.3 prompt 文件

catalog 生成 prompt 不放在 `.env`，而放在：

- `feishu_builder_agent/prompts/case_profile_catalog_system.txt`
- `feishu_builder_agent/prompts/case_profile_catalog_user.txt`

这是为了把：

- 配置
- 内容
- 规则源

三者分开。

---

## 5. 核心模块与职责

### 5.1 `case_profiles.py`

职责：

- 读取 catalog
- 提供 deterministic sampling helper
- 为 `case-world / characters / conversation-plan` 提供统一规则入口

核心函数：

- `load_case_profile_catalog()`
- `resolve_case_profile()`
- `sample_case_seed_components()`
- `sample_case_world_components()`
- `resolve_character_role_templates()`
- `sample_topic_templates()`
- `build_session_layouts()`

伪代码：

```python
def sample_case_seed_components(task_id, difficulty, seed, profile_id, hints):
    profile = resolve_case_profile(profile_id)
    departments = sample_departments(profile, difficulty, seed, hints)
    company_type = choose(profile.company_type_options, seed)
    initiative_label = choose(profile.initiative_labels, seed)
    delivery_motion = choose(profile.delivery_motions, seed)
    target_window = choose(profile.target_window_options, seed)

    context = {
        "task_id": task_id,
        "focus_department": departments[0],
        "secondary_department": departments[1],
        "target_window": target_window,
        ...
    }

    title = render(choice(profile.title_templates, seed), context)
    main_goal = render(choice(profile.main_goal_templates, seed), context)
    complexity_profile = profile.default_complexity_profile_by_difficulty[difficulty]

    return {
        "domain": profile.domain,
        "company_type": company_type,
        "departments": departments,
        "title": title,
        "main_goal": main_goal,
        "complexity_profile": complexity_profile,
    }
```

### 5.2 `case_world_generator.py`

职责：

- 把 `case_seed` 变成完整 `case_world`

边界：

- 规则层决定 stakeholders/conflicts/constraints/reversals 的骨架
- LLM 只负责展开语言，不允许越权改结构

伪代码：

```python
def generate_case_world_with_mode(case_seed, llm_client):
    sampled = sample_case_world_components(case_seed)

    fallback_world = {
        "stakeholders": sampled.stakeholders,
        "conflict_axes": sampled.conflict_axes,
        "hidden_constraints": sampled.hidden_constraints,
        "reversal_points": sampled.reversal_points,
        ...
    }

    if llm_client is None:
        return fallback_world, "fallback"

    prompt = build_world_prompt(case_seed, sampled)
    try:
        live_world = llm_client.generate_json(prompt)
        return validate_case_world(live_world), "live"
    except:
        return fallback_world, "fallback"
```

### 5.3 `character_generator.py`

职责：

- 基于 sampled departments 和 catalog 的角色模板生成角色画像
- 生成稳定的 `person_id` / `simulated_open_id`
- 产出 `actor_registry`

伪代码：

```python
def fallback_characters(case_seed):
    templates = resolve_character_role_templates(
        profile_id=case_seed.scenario_profile,
        departments=case_seed.departments
    )

    role_pool = flatten(templates for sampled departments)
    if len(role_pool) < 8:
        role_pool += extra_templates_from_profile_pool()

    characters = []
    for index, (department, template) in enumerate(role_pool):
        person_id = build_person_id(template.role_key, index)
        characters.append({
            "person_id": person_id,
            "simulated_open_id": f"ou_sim_{person_id}",
            "department": department,
            ...
        })
    return characters
```

### 5.4 `conversation_plan_generator.py`

职责：

- 从 catalog 的 topic/session 模板组装 fallback conversation skeleton
- 让 fallback 不再依赖整块硬编码 turns

当前真实做法：

- 从 `topic_templates` 采样 topics
- 从 `session_layout_templates` 组装 sessions
- 按 topic 的 `turn_templates` 生成 turn skeleton
- 再把不同 topic 的 turns 交错合并成一条多轮会话

伪代码：

```python
def fallback_conversation_plan(case_seed, characters):
    topics = sample_topic_templates(seed, difficulty, profile_id)
    turns_per_topic = []
    for topic in topics:
        context = build_topic_context(case_seed, topic)
        topic_turns = []
        for template in topic.turn_templates:
            topic_turns.append({
                "session_id": template.session_id,
                "speaker_ref": first_actor_in_department(template.speaker_department),
                "topic_key": topic.topic_key,
                "supports_event_types": template.supports_event_types,
                "semantic_payload": render(template.semantic_payload_template, context),
                ...
            })
        turns_per_topic.append(topic_turns)

    turns = interleave(turns_per_topic)
    sessions = build_sessions_from_layouts_and_turns()

    return {
        "topic_registry": topics,
        "sessions": sessions,
        "turns": turns,
    }
```

### 5.5 `command_plan_generator.py`

职责：

- 把 `conversation_plan + target_state + characters` 编译成可执行动作

当前 action family 包括：

- `create_chat`
- `send_message`
- `reply_in_thread`
- `fetch_chat_messages`
- `fetch_thread_messages`

伪代码：

```python
def fallback_command_plan(plan, target_state, characters):
    create create_chat steps for every unique chat_ref

    for turn in conversation_plan.turns:
        if session.source_type == "thread":
            action_type = "reply_in_thread"
            root_message_ref = root turn output ref
        else:
            action_type = "send_message"

        command_plan.append({
            "speaker_ref": turn.speaker_ref,
            "content_text": prefixed_message(character, turn.semantic_payload),
            "depends_on_step_ids": [...],
            "gold_intent_refs": refs_from_target_state(topic),
            ...
        })

    add fetch_chat_messages for used chats
    add fetch_thread_messages for thread sessions
```

### 5.6 `executor.py`

职责：

- 执行 `execution_plan.json`
- 与真实 `lark-cli` 交互

当前关键点：

- `create_chat`、`send_message`、`reply_in_thread` 真正调用 `lark-cli`
- 资源 id 会写回 `execution_result.json`
- 后续 `collect` / `adapt` 会依赖这些映射补全 `chat_id / message_id / thread_id`

### 5.7 `collector.py` + `collected_message_builder.py`

职责：

- 从真实执行结果中拉回飞书 fetch 记录
- 把真实单用户 sender 抬升成 benchmark 的多角色语义

关键输出：

- `lark_fetch_records.jsonl`
- `data/collected_messages.jsonl`

当前双层身份语义：

- `actual_sender`
  - 真实飞书 sender
- `simulated_speaker`
  - 来自 `characters.json / actor_registry.json`

伪代码：

```python
def build_collected_messages(characters, actor_registry, command_plan, execution_result, fetch_records):
    for each collected message:
        match it back to command_plan step
        keep actual sender from fetch result
        resolve simulated_speaker from speaker_ref
        overwrite simulated open_id from actor_registry
        emit normalized_actor_id and speaker_resolution_mode
```

### 5.8 `gold_generator.py`

职责：

- 生成 evidence-bound gold

当前策略：

- `target_state` 先定义 topic/block/current-state 目标
- `collected_messages` 提供真实证据
- `expected_events` 尽量对齐 Layer 2 `session_event`
- `expected_memory_blocks` 和 `expected_current_state` 从 gold events 再聚合

伪代码：

```python
def generate_gold_artifacts(target_state, conversation_plan, collected_messages, llm_client):
    if llm_client exists:
        draft_events = llm_generate_events(target_state, conversation_plan, collected_messages)
        events = validate_expected_events(draft_events)
    else:
        events = deterministic_events_from_messages(...)

    blocks = aggregate_events_into_blocks(events, target_state)
    current_state = aggregate_blocks_into_current_state(blocks)
    return events, blocks, current_state
```

### 5.9 `dataset_validator.py`

职责：

- 做跨阶段一致性审计

它不只是 schema 校验，而是检查：

- `command_plan` 是否覆盖 `conversation_plan`
- `collected_messages` 是否和 `characters / actor_registry` 对齐
- `gold` 是否真的能回到 evidence
- complexity gate 是否达标

### 5.10 `adapter.py`

职责：

- 把 builder 的 collected evidence 转成 OpenClaw ingest 事件

重要边界：

- `actual_sender` / `simulated_speaker` 不会直接出现在最终 ingress 顶层
- 最终 `openclaw_message_ingress.jsonl` 只保留标准 Feishu 事件字段
- 模拟身份通过：
  - `sender.sender_id.open_id = simulated_open_id`

---

## 6. 当前 CLI 与脚本

Python CLI 入口：

- `feishu_builder_agent/cli.py`

主要命令：

- `generate-case-profile-catalog`
- `generate-case-world`
- `generate-characters`
- `generate-conversation-plan`
- `generate-target-gold`
- `generate-command-plan`
- `execute-case`
- `collect-case`
- `generate-gold`
- `validate-case`
- `adapt-case`
- `compile-case`
- `build-case`

脚本入口：

- `amem_docs/scripts/feishu-builder-agent-run.sh`

它负责：

- 生成动态 case spec
- 保存最近一次动态 case 的指针
- 按阶段驱动 builder CLI
- 落 `_runs/*.json` 和 `*.stderr.log`

---

## 7. 当前已知边界

### 7.1 LLM 与 fallback

在当前环境里，如果模型请求失败，builder 会自动回退到 fallback 结构。

这意味着：

- 结构层仍然可以稳定生成
- 但自然语言丰富度会下降

### 7.2 catalog 已经数据化，但还不是“自演化系统”

现在 catalog 已经：

- 独立成静态规则源
- 支持通过 DeepSeek/`.env` 生成器刷新

但它仍然不是：

- 自动学习型规则库
- 多 profile 自动扩展系统

它当前仍然需要人来决定：

- 要不要生成新版本
- 要不要接受新 catalog

### 7.3 gold 还在继续向 Layer 2 完全对齐

当前 `expected_events.jsonl` 已经尽量对齐 Layer 2，但这层还值得继续收：

- typed field 更完整
- verification 语义更贴近真实 Layer 2
- 与 extractor/verifier 的字段命名继续收紧

---

## 8. 一句话总结

当前 `feishu_builder_agent` V2 已经不是一个简单的“消息模板编译器”，而是一套：

> 先由 catalog 定义结构，再由 LLM 细化语言，再执行真实飞书动作，最后把目标状态绑定回真实证据的 benchmark 构建链。
