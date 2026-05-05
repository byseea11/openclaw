# 2026-05-05 Task Wiki V2 Dataset Eval Design

## 1. 设计目标

这份设计的目标是说明：

- Builder 应该生成什么
- Gold 应该如何绑定真实证据
- Task Wiki 评测应该如何落到可执行对象

当前真实前提是：

- Builder 已经切到纯 V2
- 主链已经是 `command_plan -> execute -> collect -> gold -> validate`
- 评测应围绕真实 collected evidence，而不是只围绕计划层

## 2. 当前主链

当前评测前的数据生成链是：

```text
case_spec
  -> case_seed
  -> case_world
  -> characters
  -> conversation_plan
  -> target_state
  -> command_plan
  -> execution_plan
  -> execution_result
  -> lark_fetch_records
  -> collected_messages
  -> expected_events
  -> expected_memory_blocks
  -> expected_current_state
  -> validation
```

## 3. 评测对象

当前建议固定比较：

- Baseline：OpenClaw 原始处理方式
- Method：OpenClaw + Task Wiki 三层链路

当前不把主要 baseline 写成 Raw RAG。

## 4. Gold 设计

### 4.1 target gold

`gold/target_state.json` 先定义：

- 预期 topic
- 预期 Memory Block
- 预期 current state

作用：

- 让 case 在执行前就有清晰评测目标

### 4.2 evidence-bound gold

执行与 collect 完成后，再生成：

- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`

要求：

- 每条 event 必须能回到真实 collected message
- 每个 block 必须由 backing event 支撑
- current state 必须来自真实 active/latest item

## 5. validate 设计

`validate` 不是替代本阶段校验。

当前设计固定为：

- 各阶段各自做本地 schema / prerequisite 校验
- `validate` 专门做跨阶段一致性审计

至少检查：

- plan 是否覆盖 command
- command 是否生成 execution
- execute / collect 是否真的拿回真实消息
- gold 是否回到 evidence
- complexity gate 是否通过

## 6. 当前后续工作

如果要把这套评测体系继续补完，当前优先级应是：

1. 批量 case 生成
2. complexity calibrator
3. baseline / Task Wiki 自动 scoring
4. gold review workflow

## 7. 一句话结论

当前 Task Wiki V2 dataset eval 的核心设计已经不是“消息先行”，而是：

> 先定义目标，再生成动作，再执行并回收真实证据，最后用 evidence-bound gold 评测 Task Wiki 的 state 维护能力。
