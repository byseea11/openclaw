# 2026-05-05 `feishu_builder_agent` V2 实现详解

## 1. 当前定位

`feishu_builder_agent` 当前的目标不是生成一段“故事文本”，而是生成一份可以：

- 先定义一个可控的协作案例
- 再真实执行到飞书
- 再真实 collect 回来
- 再转换成 `openclaw-lark` 能直接消费的 replay 输入
- 最后作为 Task Wiki Layer 1/2/3 的评测样本

的完整数据构建链。

当前实现是纯 V2，不保留旧 catalog/template 主路径。

## 2. 当前阶段链

当前公开阶段：

```text
spec-generation
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

阶段职责：

1. `spec-generation`
   生成最小 `case_spec.json`。
2. `case-world`
   把最小 spec 扩写成真实企业协作世界。
3. `characters`
   生成角色画像与模拟 open_id 映射。
4. `plan`
   生成多 session、多 topic、多轮对话计划。
5. `target-gold`
   先定义评测目标。
6. `command-plan`
   生成要执行的飞书动作。
7. `execute`
   真实调用 `lark-cli` 执行动作。
8. `collect`
   拉取真实消息并做角色身份抬升。
9. `gold`
   把 target gold 绑定到真实证据。
10. `validate`
   做跨阶段一致性审计。
11. `adapt`
   生成 `openclaw-lark` 可直接消费的 ingress。

## 3. 单个 case 目录

当前单个 case 目录结构：

```text
amem_docs/ds/feishu_im_dataset_v2/cases/<case_id>/
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

## 4. 核心数据对象

### 4.1 `case_spec.json`

这是最小输入，不是世界对象。

当前固定结构：

```json
{
  "case_id": "case_feishu_505121846_example",
  "task_id": "FEISHU-505121846",
  "title": "",
  "company_type": "",
  "department_hints": ["产品", "研发", "安全", "运维"],
  "scenario_profile": "enterprise_release_coordination",
  "title_hint": "FEISHU-505121846 发布窗口协调",
  "main_goal_hint": "围绕 FEISHU-505121846 形成真实、可执行的跨部门协作口径",
  "main_goal": "",
  "difficulty": "medium",
  "seed": 505121846
}
```

约束：

- `difficulty` 是控制项，不允许模型改写。
- `seed` 是控制项，不允许模型改写。
- `title`、`company_type`、`main_goal` 在这一层通常保持空。
- `department_hints`、`title_hint`、`main_goal_hint` 是后续 world expansion 的提示。
- `case_id` 会被系统规范化成 `case_feishu_<digits>_example`
- `task_id` 会被系统规范化成 `FEISHU-<digits>`

这意味着即使模型返回：

```json
{
  "case_id": "CASE-001",
  "task_id": "TASK-001"
}
```

最终也会被统一收成：

```json
{
  "case_id": "case_feishu_001_example",
  "task_id": "FEISHU-001"
}
```

### 4.2 `case_seed.json`

这是控制层快照。

它从 `case_spec.json` 派生，只保留后续运行需要的控制参数：

- `case_id`
- `task_id`
- `scenario_profile`
- `difficulty`
- `seed`
- `department_hints`
- `title_hint`
- `main_goal_hint`
- `company_type_hint`
- `complexity_profile`

### 4.3 `case_world.json`

这是当前 builder 的 canonical world。

后续：

- `characters`
- `plan`
- `story`
- `timeline`
- `target-gold`

都只读它，不再去读 resolved `case_spec`。

当前字段：

- `title`
- `company_type`
- `departments`
- `main_goal`
- `organization_background`
- `external_pressure`
- `stakeholders`
- `conflict_axes`
- `hidden_constraints`
- `reversal_points`
- `selected_topics`
- `complexity_profile`

### 4.4 `characters.json`

这是角色画像。

每个角色至少包含：

- `person_id`
- `name`
- `department`
- `role`
- `stance`
- `risk_preference`
- `information_access_level`
- `default_channels`
- `simulated_open_id`

规则固定：

```text
simulated_open_id = ou_sim_<person_id>
```

### 4.5 `actor_registry.json`

这是运行时身份映射表。

它由 `characters.json` 派生，后续：

- `collect`
- `gold`
- `validate`
- `adapt`

都消费它，而不是自己临时拼角色身份。

### 4.6 `conversation_plan.json`

这是多 session、多 topic、多轮会话计划。

当前主要字段：

- `topic_registry`
- `sessions`
- `turns`

它定义了：

- 有哪些 topic
- topic 在哪些 session 中推进
- 每轮是谁说
- 这轮支持哪类 event
- 哪些轮次会触发状态演化

### 4.7 `command_plan.jsonl`

这是逻辑动作层。

每条记录表示一个“准备执行的飞书动作”。

当前记录至少包含：

- `step_id`
- `source_type`
- `channel_scope`
- `topic_key`
- `turn_purpose`
- `speaker_ref`
- `lark_cli_command`
- `expected_effect`
- `depends_on_step_ids`
- `gold_intent_refs`

### 4.8 `execution_plan.json`

这是运行层。

它把 `command_plan.jsonl` 编译成执行器可以直接消费的结构化动作计划。

### 4.9 `collected_messages.jsonl`

这是 collect 后的 canonical 评测层数据。

每条记录同时保留：

- `actual_sender`
- `simulated_speaker`
- `normalized_actor_id`

这层的作用是把“真实单用户执行”和“多角色 benchmark 语义”分开。

### 4.10 `openclaw_message_ingress.jsonl`

这是 replay 层输入。

它只保留 `openclaw-lark` 真正消费的标准 Feishu 字段。

关键点：

- `simulated_open_id` 会映射到 `sender.sender_id.open_id`
- 文本前缀 `【部门/姓名】` 会被剥掉
- 不再保留 `actual_sender`、`simulated_speaker` 这类 builder 内部扩展字段

## 5. 配置入口

当前可改的数量和复杂度配置集中在：

- `feishu_builder_agent/builder_settings.yml`

虽然扩展名是 `.yml`，但当前内容使用 JSON 语法。原因是仓库没有引入 `PyYAML`，而 YAML 1.2 兼容 JSON。

当前这里控制：

- `default_difficulty`
- `department_pool`
- `department_count`
- `topic_count`
- `character_count_min`
- `character_count_max`
- `session_blueprint`
- `complexity_profile`

例如如果要提高 `hard` 的复杂度，改这里：

- 增加 `department_count`
- 增加 `topic_count`
- 增加 `session_blueprint`
- 提高 `message_count_target`
- 提高 `state_transition_target`

规则优先级：

1. 命令行显式传 `--difficulty hard`
2. `case_spec.json` 中已有 `difficulty`
3. `feishu_builder_agent/builder_settings.yml` 中的 `defaults.default_difficulty`

当前所有 builder prompt 统一集中在：

- `feishu_builder_agent/prompt_templates.py`

其中：

- `spec-generation`
- `case-world`
- `characters`
- `plan`

这四个结构层阶段会直接把 `builder_settings.yml` 的难度约束注入 live prompt，包括：

- `department_pool`
- `department_count`
- `topic_count`
- `character_count_min / max`
- `session_count_target`
- `message_count_target`
- `thread_reply_depth_target`
- `state_transition_target`

其余阶段也已经迁移到同一个 prompt 模块，但当前主要是集中维护语义展开 prompt，没有额外引入新的 yml 结构字段。

## 6. 当前命名规则

当前 case 命名不再信任模型自由输出，统一由系统规范化。

规则：

```text
task_id   = FEISHU-<digits>
case_id   = case_feishu_<digits>_example
open_id   = ou_sim_<person_id>
```

这样做的原因：

- 目录名必须稳定
- 运行日志和产物路径必须可预测
- 避免模型输出 `CASE-001`、`case_001`、`task_001` 这种脏命名

## 7. LLM 与 fallback 的边界

当前 builder 所有主要阶段都采用同一策略：

- 优先尝试 LLM
- 如果模型请求失败、结构不合法、后处理失败，则回退 fallback

`llm_mode` 的语义：

- `live`
  模型输出被采纳
- `fallback`
  最终没有采纳模型输出
- `mixed`
  多个阶段混合

重要点：

日志里出现：

```text
[llm] 模型请求成功返回 JSON 内容
```

并不代表最终一定使用了模型结果。

如果后续校验失败，仍然会切到 fallback。

当前 `spec-generation` 已经会明确输出回退原因，例如：

```text
模型输出未通过 case_spec 校验，回退 fallback。reason=department_hints must be a list
```

## 8. 各阶段伪代码

### 8.1 `spec-generation`

```python
def generate_case_spec(scenario_profile, difficulty, seed, user_hint):
    normalized_seed = normalize_seed(seed)
    fallback_task_id = f"FEISHU-{normalized_seed}"
    fallback_case_id = f"case_feishu_{normalized_seed}_example"
    fallback = {
        "case_id": fallback_case_id,
        "task_id": fallback_task_id,
        "department_hints": select_departments_from_hint(user_hint),
        "title_hint": user_hint or f"{fallback_task_id} 发布窗口协调",
        "main_goal_hint": user_hint or f"围绕 {fallback_task_id} 形成真实、可执行的跨部门协作口径",
        "scenario_profile": scenario_profile,
        "difficulty": difficulty,
        "seed": normalized_seed,
        "title": "",
        "company_type": "",
        "main_goal": "",
    }

    if llm_unavailable():
        return validate_case_spec(fallback), "fallback"

    payload = llm_generate_json(...)
    normalized_task_id = normalize_task_id(payload["task_id"], normalized_seed)
    normalized_case_id = normalize_case_id(payload["case_id"], normalized_task_id)
    normalized_departments = normalize_department_hints(payload["department_hints"])
    merged = merge(payload, fallback)
    merged["task_id"] = normalized_task_id
    merged["case_id"] = normalized_case_id
    merged["department_hints"] = normalized_departments
    return validate_case_spec(merged), "live"
```

### 8.2 `case-world`

```python
def generate_case_world(case_seed):
    difficulty_settings = resolve_difficulty_settings(case_seed["difficulty"])
    fallback_departments = select_departments(
        pool=builder_settings.department_pool,
        hints=case_seed["department_hints"],
        count=difficulty_settings["department_count"],
        seed=case_seed["seed"],
    )

    fallback = {
        "case_id": case_seed["case_id"],
        "task_id": case_seed["task_id"],
        "title": case_seed["title_hint"] or f"{task_id} 发布窗口协调推进",
        "company_type": case_seed["company_type_hint"] or "企业级 SaaS 公司",
        "departments": fallback_departments,
        "main_goal": case_seed["main_goal_hint"] or default_goal(task_id),
        "organization_background": ...,
        "external_pressure": ...,
        "stakeholders": ...,
        "conflict_axes": ...,
        "hidden_constraints": ...,
        "reversal_points": ...,
        "selected_topics": build_topic_templates(...),
        "complexity_profile": case_seed["complexity_profile"],
    }

    if llm_unavailable():
        return validate_case_world(fallback), "fallback"

    payload = llm_expand_world(...)
    merged = merge(payload, fallback)
    return validate_case_world(merged), "live"
```

### 8.3 `characters`

```python
def generate_characters(case_world):
    if llm_available():
        payload = llm_generate_characters(case_world)
        normalized = validate_characters(payload)
    else:
        normalized = build_fallback_characters(case_world.departments)

    for actor in normalized["characters"]:
        actor["simulated_open_id"] = f"ou_sim_{actor['person_id']}"

    actor_registry = build_actor_registry(normalized)
    return normalized, actor_registry
```

### 8.4 `plan`

```python
def generate_conversation_plan(case_world, characters):
    story = generate_story(case_world, characters)
    timeline = generate_timeline(case_world, story, characters)

    if llm_available():
        payload = llm_generate_plan(case_world, characters)
        plan = validate_conversation_plan(payload)
    else:
        plan = build_fallback_plan(
            selected_topics=case_world.selected_topics,
            session_blueprint=difficulty_settings.session_blueprint,
            characters=characters,
        )

    assert plan_has_at_least_3_sessions(plan)
    assert plan_has_at_least_3_topics(plan)
    assert plan_has_at_least_18_turns(plan)
    return plan
```

### 8.5 `target-gold`

```python
def generate_target_gold(conversation_plan):
    return {
        "case_id": conversation_plan["case_id"],
        "expected_topics": derive_topics(conversation_plan),
        "expected_block_targets": derive_block_targets(conversation_plan),
        "expected_current_state_targets": derive_current_state_targets(conversation_plan),
        "required_event_coverage": derive_event_coverage(conversation_plan),
    }
```

### 8.6 `command-plan`

```python
def generate_command_plan(case_seed, conversation_plan, characters, target_state):
    if llm_available():
        payload = llm_generate_command_plan(...)
        rows = validate_command_plan(payload)
    else:
        rows = build_fallback_command_plan(...)

    execution_plan = build_execution_plan_from_command_plan(rows)
    return rows, execution_plan
```

### 8.7 `execute`

```python
def execute_case(case_dir, dry_run=False):
    plan = read_json("execution_plan.json")
    resume_result = read_json_if_exists("execution_result.json")
    if resume_result and resume_result["status"] != "success":
        resume_result = None
    result = execute_plan(plan, dry_run=dry_run, resume_result=resume_result)
    write_json("execution_result.json", result)
    return result
```

### 8.8 `collect`

```python
def collect_case(case_dir):
    actor_registry = read_json("input/actor_registry.json")
    command_plan = read_jsonl("input/command_plan.jsonl")
    execution_plan = read_json("execution_plan.json")
    execution_result = read_json("execution_result.json")

    fetch_records = collect_fetch_records(execution_plan, execution_result)
    collected_messages = build_collected_messages(
        command_plan=command_plan,
        fetch_records=fetch_records,
        actor_registry=actor_registry,
    )

    # 每条消息保留 actual_sender，同时映射 simulated_speaker
    write_jsonl("lark_fetch_records.jsonl", fetch_records)
    write_jsonl("data/collected_messages.jsonl", collected_messages)
```

### 8.9 `gold`

```python
def generate_gold(case_dir):
    target_state = read_json("gold/target_state.json")
    conversation_plan = read_json("input/conversation_plan.json")
    collected_messages = read_jsonl("data/collected_messages.jsonl")

    events = generate_expected_events(
        target_state=target_state,
        conversation_plan=conversation_plan,
        collected_messages=collected_messages,
    )
    blocks = build_expected_memory_blocks(events)
    current_state = build_expected_current_state(events)

    write_jsonl("gold/expected_events.jsonl", events)
    write_json("gold/expected_memory_blocks.json", blocks)
    write_json("gold/expected_current_state.json", current_state)
```

### 8.10 `validate`

```python
def validate_case(case_dir):
    complexity_report = build_complexity_report(...)
    dataset_validation_report = build_dataset_validation_report(...)

    # 这里不重跑上游生成
    # 这里只审计：
    # - plan 是否完整
    # - command-plan 是否覆盖
    # - collect 是否成功
    # - gold 是否能回到真实 evidence
    # - ingress open_id 是否能回溯到 actor_registry

    write_json("checks/conversation_complexity_report.json", complexity_report)
    write_json("checks/dataset_validation_report.json", dataset_validation_report)
```

### 8.11 `adapt`

```python
def adapt_case(case_dir):
    case_seed = read_json("input/case_seed.json")
    actor_registry = read_json("input/actor_registry.json")
    fetch_records = read_jsonl("lark_fetch_records.jsonl")
    collected_messages = read_jsonl("data/collected_messages.jsonl")
    execution_result = read_json("execution_result.json")

    ingress = adapt_fetch_records(
        case_seed=case_seed,
        actor_registry=actor_registry,
        fetch_records=fetch_records,
        collected_messages=collected_messages,
        execution_result=execution_result,
    )

    # 最终写入 openclaw-lark 标准字段
    # sender.sender_id.open_id = simulated_open_id
    write_jsonl("openclaw_message_ingress.jsonl", ingress)
```

## 9. `CASE-001` 这类目录为什么会出现

根因是：

- 早期 `spec-generation` 允许模型直接决定 `case_id`
- 模型可能输出 `CASE-001`
- `cli.py` 会直接用 `case_spec.case_id` 创建目录
- 所以落盘成了 `cases/CASE-001/`

当前实现已经修正：

- `task_id` 统一规范化
- `case_id` 统一规范化
- `case_spec` 校验也要求：
  - `case_id` 必须是 lower snake case，并以 `case_` 开头
  - `task_id` 必须是大写短横线形式，例如 `FEISHU-231`

## 10. 当前仍保留的内部 helper

当前仍保留：

- `feishu_builder_agent/story_generator.py`
- `feishu_builder_agent/timeline_planner.py`

但它们只是内部 helper，不是公开阶段，也不是 canonical 数据层。

规则：

- 它们只能读 `case_world.json`
- 不能再回头要求 `case_spec.json` 已被“补全”

## 11. 当前哪些地方需要改

如果你后续要继续调 builder，优先改这几个位置：

1. 案例生成方向
   - `feishu_builder_agent/spec_generator.py`
2. 世界复杂度和数量控制
   - `feishu_builder_agent/builder_settings.yml`
3. world fallback 语义
   - `feishu_builder_agent/case_world_generator.py`
4. 角色画像 fallback
   - `feishu_builder_agent/character_generator.py`
5. 多轮计划 fallback
   - `feishu_builder_agent/conversation_plan_generator.py`
6. gold 对齐
   - `feishu_builder_agent/gold_generator.py`
   - `feishu_builder_agent/target_gold_generator.py`
7. replay 到 `openclaw-lark`
   - `feishu_builder_agent/adapter.py`

## 12. 当前真实实现边界

当前已经做到：

- spec-first
- case-world canonical
- characters 产出模拟 open_id
- command-plan 先于 execute
- collect 后保留真实 sender 和模拟角色
- adapt 最终写标准 Feishu sender 字段

当前还不是最终形态的点：

- live LLM 输出仍依赖外部网络环境
- `gold/expected_events.jsonl` 虽然已经靠近 Layer 2，但仍然是 builder 自己的 gold 产物，不是直接运行 Layer 2 extractor 的结果
- `story` / `timeline` 还保留为内部 helper，后续可以继续瘦身

## 13. 脚本入口

当前推荐统一使用：

- `amem_docs/scripts/feishu-builder-agent-run.sh`

最常用的命令：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase spec
amem_docs/scripts/feishu-builder-agent-run.sh --phase case-world
amem_docs/scripts/feishu-builder-agent-run.sh --phase full
```

如果不显式传 `--case-spec`：

- `spec` 会先生成新的 `case_spec.json`
- `case-world` 和 `full` 也会先补这一步

中间阶段默认接最近一次生成的 case：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase characters
amem_docs/scripts/feishu-builder-agent-run.sh --phase plan
amem_docs/scripts/feishu-builder-agent-run.sh --phase command-plan
```

## 14. 结论

当前 builder 的主心智应该固定成三句话：

1. `case_spec.json` 是最小控制输入，不是世界对象。
2. `case_world.json` 是后续所有生成阶段的 canonical world。
3. `openclaw_message_ingress.jsonl` 是最终给 `openclaw-lark` 的标准 Feishu replay 输入。

后续如果要继续扩复杂度，优先调：

- `spec_generator.py`
- `builder_settings.yml`
- `case_world_generator.py`
- `conversation_plan_generator.py`

不要再回到“把更多 resolved 字段塞进 `case_spec.json`”这条路。
