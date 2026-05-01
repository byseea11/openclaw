# 2026-05-01 `feishu_builder_agent` 当前实现说明

## 1. 当前定位

`feishu_builder_agent` 当前实现的是一个 **独立的 Python 离线数据集构建器**。

它的目标不是直接参与 OpenClaw 在线对话，而是把一个企业协作 case 编译成：

1. 一组结构化的故事、角色、冲突时间线
2. 一组可以通过 `lark-cli` 真实执行的 IM 动作
3. 一批从飞书真实拉回的 raw message records
4. 一批可以被 OpenClaw 消费的 message ingress 事件

当前它的边界非常明确：

- 严格 IM-only
- 一个 case 一个目录
- 不兼容旧 `eval_old`
- 不产出 query set / golden answer
- 主要面向飞书群聊 / thread 消息数据集构建
- 当前默认执行模式是：
  - `operator_identity = "user"`
  - `delivery_mode = "prefixed_single_operator"`

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
  story_generator.py
  character_generator.py
  timeline_planner.py
  plan_mapper.py
  executor.py
  collector.py
  adapter.py
  build_report.py
  prompts/
  templates/
  tests/
```

这套结构已经可以独立运行，不依赖 OpenClaw 主链内部模块。

## 3. 当前实现的整体流程

当前 Builder 的主流程是：

```text
case_spec.json
  -> compile-case
  -> execute-case
  -> adapt-case
  -> build_report.json
```

对应到代码：

- `feishu_builder_agent/cli.py`
  - 对外入口
- `feishu_builder_agent/story_generator.py`
  - 生成 `story.json`
- `feishu_builder_agent/character_generator.py`
  - 生成 `characters.json`
- `feishu_builder_agent/timeline_planner.py`
  - 生成 `conflict_timeline.json`
- `feishu_builder_agent/plan_mapper.py`
  - 生成 `execution_plan.json`
- `feishu_builder_agent/executor.py`
  - 真实执行飞书动作
- `feishu_builder_agent/collector.py`
  - 拉取 raw message records
- `feishu_builder_agent/adapter.py`
  - 转成 OpenClaw ingress
- `feishu_builder_agent/build_report.py`
  - 输出最后的构建报告

## 4. 当前 case 产物结构

一个 case 当前会落到：

```text
feishu_im_dataset_v1/
  dataset_manifest.json
  cases/
    <case_id>/
      case_spec.json
      story.json
      characters.json
      conflict_timeline.json
      execution_plan.json
      execution_result.json
      lark_fetch_records.jsonl
      openclaw_message_ingress.jsonl
      adapter_report.json
      build_report.json
```

这些文件的职责分别是：

- `case_spec.json`
  - 用户输入的最小 case 定义
- `story.json`
  - 业务背景和冲突故事
- `characters.json`
  - 角色 roster
- `conflict_timeline.json`
  - 可追踪的冲突时间线
- `execution_plan.json`
  - 确定性执行计划
- `execution_result.json`
  - 真实执行结果和资源映射
- `lark_fetch_records.jsonl`
  - 飞书 raw fetch records
- `openclaw_message_ingress.jsonl`
  - OpenClaw 可消费的事件流
- `adapter_report.json`
  - adapter 过程统计
- `build_report.json`
  - case 级最终报告

## 5. Compile 阶段：目前已经实现了什么

### 5.1 `case_spec.json`

当前 `case_spec` 至少包含：

- `case_id`
- `task_id`
- `title`
- `company_type`
- `departments`
- `main_goal`
- `difficulty`
- `seed`

当前校验逻辑在 `feishu_builder_agent/schemas.py`。

### 5.2 `story.json`

由 `feishu_builder_agent/story_generator.py` 生成。

当前支持两种来源：

- live LLM
- fallback scaffold

输出字段固定为：

- `case_id`
- `task_id`
- `title`
- `background`
- `business_pressure`
- `project_goal`
- `initial_assumption`
- `main_conflicts`
- `in_scope`
- `out_of_scope`

### 5.3 `characters.json`

由 `feishu_builder_agent/character_generator.py` 生成。

当前支持：

- live LLM
- fallback roster

每个角色至少有：

- `person_id`
- `name`
- `department`
- `role`
- `responsibility`
- `communication_style`
- `conflict_bias`

注意：

- `person_id` 是内部稳定 id，可以是英文 snake_case
- `name / department / role / responsibility` 等自然语言字段必须是中文

### 5.4 `conflict_timeline.json`

由 `feishu_builder_agent/timeline_planner.py` 生成。

当前每个 timeline event 固定包含：

- `timeline_id`
- `time_order`
- `event_type`
- `description`
- `actor_refs`
- `affected_topic`
- `state_effect`
- `should_surface_in_message`

当前 fallback timeline 是围绕：

- 早期目标
- blocker
- 风险 / 约束
- 对外口径修正

来构造的。

### 5.5 `execution_plan.json`

由 `feishu_builder_agent/plan_mapper.py` 生成。

这里有两个很关键的实现约束：

1. **当前 plan 是确定性产物，不由 LLM 直接生成**
2. **mapper 不创造新事实，只把 timeline 里的事实映射成消息动作**

当前 plan action types 只有：

- `create_chat`
- `send_message`
- `reply_in_thread`
- `fetch_chat_messages`
- `fetch_thread_messages`

这保证了 Builder 当前还是非常收敛的 IM-only 实现。

## 6. 执行身份模型：当前实际怎么做

当前 Builder 不是多账号 impersonation，而是：

- 一个真实 operator
- 通过消息前缀表达不同角色

当前默认固定：

- `operator_identity = "user"`
- `delivery_mode = "prefixed_single_operator"`

这意味着：

- 飞书里真正发消息的是同一个真实用户身份
- 角色差异通过消息文本表达，例如：
  - `【产品/林晨】`
  - `【研发/周宇】`
  - `【安全/陈雪】`

对应实现主要在：

- `feishu_builder_agent/plan_mapper.py`
- `feishu_builder_agent/executor.py`

## 7. 中文数据集约束：当前已经做成硬限制

这是当前 Builder 的一个**最强约束**：

> 最终产出的数据集自然语言内容必须是简体中文。

这不是单纯 prompt 提醒，而是三层硬约束：

### 7.1 Prompt 层

在：

- `feishu_builder_agent/story_generator.py`
- `feishu_builder_agent/character_generator.py`
- `feishu_builder_agent/timeline_planner.py`

里，live LLM prompt 已经明确要求：

- 所有自然语言字段必须使用简体中文

### 7.2 Schema 层

在 `feishu_builder_agent/schemas.py` 里，已经对这些字段做了中文校验：

- `case_spec.title/company_type/departments/main_goal`
- `story` 自然语言字段
- `characters` 的中文显示字段
- `timeline.description/affected_topic/state_effect`
- `execution_plan` 中：
  - `create_chat.name`
  - `send_message.content_text`
  - `reply_in_thread.content_text`

也就是说，只要这些字段不是中文，就会被视为无效输出。

### 7.3 Fallback 层

即使 live LLM 连通成功，如果返回：

- 英文自然语言
- 或结构非法

当前也不会把这份结果直接写进数据集，而是会自动回退到中文 fallback。

这已经在以下模块实现：

- `feishu_builder_agent/story_generator.py`
- `feishu_builder_agent/character_generator.py`
- `feishu_builder_agent/timeline_planner.py`

## 8. Live / Fallback 模式：当前已经可见

当前 `compile-case` 返回值里，已经增加了更细的生成模式标记。

现在除了原有结果，还会返回：

```json
{
  "llm_mode": "live | mixed | fallback",
  "generation_modes": {
    "story": "live | fallback",
    "characters": "live | fallback",
    "timeline": "live | fallback"
  }
}
```

语义是：

- `story`
  - 本段最终产物来自 live 还是 fallback
- `characters`
  - 本段最终产物来自 live 还是 fallback
- `timeline`
  - 本段最终产物来自 live 还是 fallback
- `llm_mode`
  - 上面三段的聚合值

这个实现现在在：

- `feishu_builder_agent/story_generator.py`
- `feishu_builder_agent/character_generator.py`
- `feishu_builder_agent/timeline_planner.py`
- `feishu_builder_agent/cli.py`

## 9. Executor：当前已经实现了什么

执行逻辑在 `feishu_builder_agent/executor.py`。

当前已经具备：

- `preflight`
  - 检查 `lark-cli` 是否可用
  - 检查 `auth status`
- action 拓扑排序
- `output_ref -> real resource id` 映射
- `thread_id_to_chat_id` 映射
- `dry-run`
- `resume`

当前真实命令构造已经覆盖：

- `lark-cli im +chat-create`
- `lark-cli im +messages-send`
- `lark-cli im +messages-reply`
- `lark-cli im +chat-messages-list`
- `lark-cli im +threads-messages-list`

当前 `execution_result.json` 里会保留：

- `created_resources`
- `thread_id_to_chat_id`
- `action_status`
- `preflight`

## 10. Collector：当前已经实现了什么

Collector 在 `feishu_builder_agent/collector.py`。

当前职责非常收敛：

- 只读取：
  - `execution_plan.json`
  - `execution_result.json`
- 只执行 fetch 类型 action
- 把结果写成 `lark_fetch_records.jsonl`

当前每条 fetch record 会记录：

- `record_id`
- `domain`
- `kind`
- `captured_at`
- `identity`
- `command`
- `response`
- `stderr`
- `returncode`

当前 Collector 仍然保持 raw 导向，不在这一层做 OpenClaw ingress 适配。

## 11. Adapter：当前已经实现了什么

Adapter 在 `feishu_builder_agent/adapter.py`。

它当前只做一件事：

> 把 `lark_fetch_records.jsonl` 中的 raw messages 适配成 OpenClaw 可消费的 message ingress 事件。

### 11.1 当前输入

Adapter 当前输入固定为：

- `case_spec.json`
- `execution_result.json`
- `lark_fetch_records.jsonl`

### 11.2 当前输出

当前输出：

- `openclaw_message_ingress.jsonl`
- `adapter_report.json`

### 11.3 当前适配规则

当前已经实现的规则包括：

- 只处理 `msg_type == "text"` 的消息
- `deleted=true` 跳过
- `thread_id` 优先使用消息自身字段
- 如果 thread fetch 的消息没有 `thread_id`，会保留 `root_id` fallback
- 如果 `chat_id` 缺失，会尝试从 `execution_result.thread_id_to_chat_id` 补齐
- `content` 会包装成 JSON string：

```json
{"text":"..."}
```

- `create_time` 会被转换成毫秒时间戳字符串
- 输出顺序会按时间和 `message_id` 排序，尽量保持稳定回放顺序

## 12. 非常重要：后续修改时要对齐哪个 runtime

这个点必须明确写死：

> 后续 Builder 的 Feishu ingress 形态，**需要对齐的是当前机器上实际安装并运行的 Lark 插件**，也就是：

`/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel`

而不是仓库里其他可能存在的旧实现、参考实现，或者未来可能发生变化的未安装源码副本。

这件事非常重要，因为后续如果你继续修改 Builder 的 adapter 或 runtime 对齐逻辑，真正影响线上行为的是：

- 已安装插件
- 当前用户环境里正在被 OpenClaw 实际加载的插件

不是仓库里某个名字相近的目录。

## 13. Adapter 目前参考的是哪些文件

这部分要写得非常清楚。

### 13.1 主参考：`src/channel/event-handlers.js`

当前最直接的 channel 入口参考是：

`/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/event-handlers.js`

Builder adapter 当前对齐它的几点是：

- channel 事件从 `event.message.*` 读取消息元数据
- queue 侧在 topic / thread 场景下，会优先看：
  - `thread_id`
  - 如果没有，再用 `root_id` fallback
- `handleMessageEvent()` 里对 reply/topic 的说明非常关键：
  - 在 topic 群里，reply event 可能只有 `root_id`，没有 `thread_id`
  - 这就是 Builder adapter 当前保留 `root_id` fallback 的直接原因

也就是说，Builder adapter 的这条逻辑：

- `thread_id` 优先
- `root_id` fallback

主要就是参考这个文件。

### 13.2 重要补充：`src/channel/chat-queue.js`

另一个必须一起看的文件是：

`/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/chat-queue.js`

这个文件决定了 runtime queue key 的语义：

- base key 是：
  - `<accountId>:<chatId>`
- 如果有 thread，再拼：
  - `:thread:<threadId>`

这意味着：

- 当前 live runtime 本质上还是 `chat + thread` 维度串行
- 后续如果要做 task-first session routing，就一定会碰到这里

虽然这个文件不是 Adapter 直接消费 message schema 的地方，但它决定了：

- thread 语义到底怎么参与运行时会话边界

所以后续 Builder 想进一步和 runtime 对齐，不能只看 event-handlers，还必须看这个文件。

### 13.3 实际下游消费：`src/messaging/inbound/handler.js`

虽然你特别强调的是 `src/channel`，这一点完全对，我也同意后续主对齐对象应该先看 `src/channel`。

但还要明确一个事实：

真正把 inbound event 往 agent dispatch 推下去的，是：

`/Users/byseea/.openclaw/extensions/openclaw-lark/src/messaging/inbound/handler.js`

这个文件不是 `src/channel` 目录下，但它是当前 message ingress 的真实下游消费方。

当前 Builder adapter 里这些字段设计，也是在兼顾这个文件的处理方式：

- `sender.sender_id.open_id`
- `message.message_id`
- `message.chat_id`
- `message.chat_type`
- `message.thread_id`
- `message.root_id`
- `message.content`
- `message.create_time`

所以现在可以这么理解：

- **主对齐入口**
  - `/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/event-handlers.js`
- **thread / queue 语义参考**
  - `/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/chat-queue.js`
- **真正的下游消费管道**
  - `/Users/byseea/.openclaw/extensions/openclaw-lark/src/messaging/inbound/handler.js`

如果只问“Adapter 当前最直接参考的是哪个文件”，答案应该是：

> **首先是 `event-handlers.js`，其次要结合 `handler.js` 看下游实际消费字段。**

## 14. 当前实现和 live runtime 之间的距离

当前 Builder 已经能构造出一个合理的 ingress 事件流，但它和 live runtime 仍然有一些距离：

### 14.1 已经对齐的部分

- `message_id`
- `chat_id`
- `thread_id`
- `root_id`
- `chat_type`
- `content`
- `create_time`
- `sender.sender_id.open_id`

### 14.2 还没有完全覆盖的部分

- comments / docs / wiki comment 类型事件
- reactions
- interactive card actions
- richer media payload
- mentions 结构
- quote / parent message 更细粒度语义
- 多种 sender enrichment 细节

所以当前 Adapter 可以认为是：

- **面向 IM 文本消息的最小可用适配器**
- 不是完整覆盖 live Lark channel 全部入站能力的适配器

## 15. 当前测试覆盖

当前 `feishu_builder_agent/tests/` 已经覆盖：

- `test_schemas.py`
  - schema 校验
- `test_mapper.py`
  - deterministic mapper
- `test_executor.py`
  - dry-run / resume
- `test_adapter.py`
  - `chat_id` 补齐、`root_id` fallback、`content` 包装
- `test_e2e.py`
  - compile + adapt smoke
- `test_live_language.py`
  - live LLM 输出非中文时自动 fallback

这意味着当前 Builder 的核心主链已经具备一条最小闭环测试：

- compile
- plan
- execute skeleton
- collect
- adapt

## 16. 当前可以继续改进的地方

这一部分是后续最值得继续做的增强点。

### 16.1 进一步对齐 live `openclaw-lark`

这是最重要的一点。

当前 Adapter 已经开始参考 live runtime，但还不够彻底。后续应该继续对齐：

- `/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/event-handlers.js`
- `/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/chat-queue.js`
- `/Users/byseea/.openclaw/extensions/openclaw-lark/src/messaging/inbound/handler.js`

尤其是：

- thread/topic 事件的真实形态
- quote / parent / mentions 的结构
- sender enrichment 之后的字段语义

### 16.2 Adapter 需要更明确区分“当前参考层级”

后续建议把 Adapter 内部注释写得更明确：

- 哪些字段是参考 `event-handlers.js`
- 哪些字段是为了兼容 `handler.js`
- 哪些字段是 Builder 自己的保守补齐逻辑

这样以后维护时不会误以为所有字段都来自同一个 runtime 文件。

### 16.3 `execution_result` 可以记录更多 trace

当前已经有：

- `created_resources`
- `thread_id_to_chat_id`
- `action_status`

后续可以补：

- 每个 `output_ref` 对应的真实命令摘要
- root message 到 thread 的更明确映射
- action 执行耗时
- 更细的 preflight 结果

### 16.4 `build_report.json` 还可以更细

当前 report 偏统计。

后续可以继续补：

- `generation_modes`
- 每段是否 live/fallback
- collect 阶段命中的 chat/thread 数量
- adapter 跳过消息的分类统计

### 16.5 timeline 到 message 的模板还比较少

当前 mapper 还是比较偏 V1 骨架：

- 主要是少量 event_type
- 少量中文模板

后续可以继续扩：

- 更多冲突类型
- 更多表达风格
- 主群消息 / thread 回复的更多模板分层

### 16.6 真实多账号模式还没做

当前 Builder 默认仍然是：

- 单一真实 operator
- 消息前缀扮演角色

这很稳，但也有明显局限：

- 不是真正的多账号协作轨迹
- sender 真实性有限

如果后面需要更像真实企业协作，下一步可以考虑：

- 多账号真实发送
- 更真实的 sender/source 组织方式

### 16.7 当前还没有把 task-first runtime session 接进去

Builder 现在解决的是数据集构建问题，不是 runtime task wiki routing。

后续如果要和 Task Wiki 主线继续贴合，还需要进一步考虑：

- 怎样让构造出来的 dataset 更自然地服务 task-first runtime session
- 怎样把 task binding、source boundary、thread boundary 一起组织起来

## 17. 一句话总结

当前 `feishu_builder_agent` 已经完成的是：

- 一个 **可运行的、IM-only、中文强约束、支持 live/fallback、能生成 OpenClaw ingress 的离线 Builder 骨架**

当前最重要的后续方向是：

- **继续对齐当前机器上实际安装的 `openclaw-lark` runtime，而不是只看仓库内的参考实现**

特别是后续再改 Adapter 时，优先看的文件应该是：

- `/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/event-handlers.js`
- `/Users/byseea/.openclaw/extensions/openclaw-lark/src/channel/chat-queue.js`
- `/Users/byseea/.openclaw/extensions/openclaw-lark/src/messaging/inbound/handler.js`

这三处基本决定了 Builder 产出的 ingress 事件，未来应该怎样继续收口到 live runtime 的真实消费方式上。
