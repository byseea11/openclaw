# Task Wiki V2 Builder 与数据集评测完整实现计划

## 1. 当前 V2 基线

当前 `feishu_builder_agent` 已经不是旧的：

```text
story -> timeline -> execution_plan
```

而是新的：

```text
case_spec
  -> case_seed
  -> case_world
  -> characters
  -> conversation_plan
  -> target_state
  -> command_plan
  -> execution_plan
  -> execute
  -> collect
  -> collected_messages
  -> expected_events / expected_memory_blocks / expected_current_state
  -> validation / adapt
```

默认数据根目录：

- `amem_docs/ds/feishu_im_dataset_v2`

## 2. V2 的核心目标

V2 Builder 的目标不是只生成一组聊天记录，而是生成一套可以同时用于：

1. 真实飞书执行
2. OpenClaw ingest / replay
3. Task Wiki 评测
4. baseline 对比

的数据样本。

因此，V2 必须同时满足两条要求：

- **内容层**：要有真实的多轮、多 topic、跨 source、会演化的企业协作对话
- **评测层**：要有 target gold、evidence-bound gold、复杂度门槛、跨阶段一致性校验

## 3. 当前 canonical 对象

当前 V2 应以这些对象作为主契约：

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

`utterance_plan.jsonl` 和 `realized_messages.jsonl` 不再是 V2 的公开主契约。

其中 `input/characters.json` 还承担一层稳定映射职责：

- `person_id` 是角色主键
- `simulated_open_id` 是模拟工号
- 当前规则固定为 `ou_sim_<person_id>`
- `collect` 和 `adapt` 都必须消费这张映射表，而不是临时生成 open_id

## 4. 当前评测语义

### 4.1 target gold

`gold/target_state.json` 的作用是：

- 先定义这个 case 想要形成哪些 topic
- 先定义想要形成哪些 Memory Block
- 先定义最终 current state 应该是什么

这样 gold 不再是“把执行结果抄一遍”。

### 4.2 evidence-bound gold

`gold/expected_events.jsonl`、`gold/expected_memory_blocks.json`、`gold/expected_current_state.json` 的作用是：

- 把 target state 绑定到真实 collected evidence
- 确保评测能回到真实 message_id 和真实 source session

### 4.3 validate

`validate` 的职责是：

- 不重跑上游生成
- 只做跨阶段一致性审计

它至少要回答：

- `conversation_plan` 是否真的被 `command_plan` 覆盖
- `command_plan` 是否真的变成了 `execution_plan`
- `collect` 是否真的拿回了预期 source session
- `gold` 是否真的绑定到 collected evidence
- complexity gate 是否达标

## 5. 还需要继续补的内容

当前代码已经具备单 case 主链，但如果要真正形成“Task Wiki V2 数据集与评测方案”，还需要继续补这几块：

### 5.1 批量 case 生成

当前已经能稳定生成单个 case，但还需要：

- 多 case 批处理入口
- dataset 级 manifest 和 batch report
- 批量失败重试

### 5.2 complexity calibrator

需要把 `locomo` 等参考数据的复杂度分布转成：

- session 数
- topic 数
- cross-source revision 数
- supersession 数
- thread 深度

等 builder 可执行的复杂度 profile。

### 5.3 scoring

需要正式形成：

- baseline（OpenClaw 原始处理方式）
- Task Wiki 三层链路

之间的对比打分，包括：

- event recall / precision
- block coverage
- current-state accuracy
- traceability completeness

### 5.4 gold review

还需要补：

- gold draft 的人工修订入口
- 修订痕迹保留
- 冻结版 gold 与实验版 gold 的区分

## 6. 一句话结论

当前 Builder 已经具备了：

- 纯 V2 数据对象
- `command_plan` 优先的执行链
- `collect -> collected_messages` 的真实证据回收
- target gold + evidence-bound gold
- validate 跨阶段审计

后续需要补的重点，不再是“从 V1 升级到 V2”，而是：

- 批量 case 生成
- complexity calibrator
- scoring
- gold review workflow

## 7. 已有一条真实评测样本链路

当前已经有一条真实飞书环境跑通的样本：

- `amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example`

这条样本已经完成：

```text
command-plan
-> execute
-> collect
-> gold
-> validate
-> adapt
```

它的意义不是“又生成了一份 demo”，而是说明当前 builder 已经具备：

1. 真实飞书动作执行能力
2. 真实证据拉回能力
3. target gold 到 evidence-bound gold 的绑定能力
4. builder -> OpenClaw replay 输入转换能力

### 7.1 当前这条真实样本的关键结果

- `execution_result.json`
  - `status = success`
  - `25` 个动作全部成功
- `data/collected_messages.jsonl`
  - `20` 条 builder 主链关心的文本消息
- `checks/conversation_complexity_report.json`
  - `passed = true`
- `checks/dataset_validation_report.json`
  - `passed = true`
- `openclaw_message_ingress.jsonl`
  - `20` 条 ingress 事件

### 7.2 这条真实样本证明了什么

它已经证明 builder 当前可以稳定支持这种评测设定：

- 真实执行身份只有 1 个飞书用户
- 通过 `collect` 后的 speaker normalization，把消息恢复成多角色 benchmark 语义
- `gold/expected_events.jsonl` 能携带 `normalized_actor_id`
- `validate` 能同时看到：
  - `unique_actual_senders = 1`
  - `unique_normalized_actors = 6`

这说明当前方法已经能区分：

- 执行层真实性
- 评测层多角色语义

### 7.3 对后续评测计划的影响

这条真实样本意味着后续 scoring 与 dataset 批量化设计，应直接以这套对象为基线：

- `execution_result.json`
- `lark_fetch_records.jsonl`
- `data/collected_messages.jsonl`
- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`
- `checks/*`
- `openclaw_message_ingress.jsonl`

而不是再回到旧的：

- `story.json`
- `timeline.json`
- `realized_messages.jsonl`

这类不再是当前 V2 主契约的对象。
