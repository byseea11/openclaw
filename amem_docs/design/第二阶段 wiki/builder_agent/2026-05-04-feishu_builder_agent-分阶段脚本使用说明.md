# 2026-05-04 `feishu_builder_agent` 分阶段脚本使用说明

## 1. 脚本位置

当前用于运行 `feishu_builder_agent` 的分阶段脚本在：

- `amem_docs/scripts/feishu-builder-agent-run.sh`

当前默认输出目录：

- `amem_docs/ds/feishu_im_dataset_v2`

当前默认示例 case spec：

- `amem_docs/dataset_v1/case_specs/feishu_builder_case_example.json`

## 2. 设计目的

当前脚本对应的是 **纯 V2 Builder**，不是旧式 case 编译器包装器。

它的职责是把下面两层统一成一个入口：

1. V2 生成层
   - `case_seed`
   - `case_world`
   - `conversation_plan`
   - `utterance_plan`
   - `realized_messages`
   - `gold`
   - `checks`
2. 执行层
   - `execution_plan`
   - `execute`
   - `collect`
   - `adapt`

这样可以避免：

- 数据根目录写错
- case 目录推导错误
- V2 中间产物没有落全
- 只想重跑某一阶段时手工拼命令出错

## 3. 支持的阶段

### 3.1 `--phase case-world`

生成：

- `input/case_seed.json`
- `input/case_world.json`

适合：

- 先检查世界观、外部压力、冲突轴、反转点是否合理

### 3.2 `--phase plan`

生成：

- `input/conversation_plan.json`

适合：

- 先检查 source session、topic、turn、supersession 设计是否合理

### 3.3 `--phase utterance`

生成：

- `input/utterance_plan.jsonl`

适合：

- 先检查每轮消息计划是否覆盖了需要的 event family

### 3.4 `--phase realize`

生成：

- `data/realized_messages.jsonl`

适合：

- 先检查真实中文消息文本是否像企业协作对话

### 3.5 `--phase gold`

生成：

- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`

适合：

- 先检查这批数据打算如何评测 Task Wiki

### 3.6 `--phase validate`

生成：

- `checks/conversation_complexity_report.json`
- `checks/dataset_validation_report.json`

适合：

- 判断当前 case 是否达到复杂度门槛
- 判断 gold 是否都能回链到消息

### 3.7 `--phase compile`

一次性完成：

- `input/*`
- `data/realized_messages.jsonl`
- `gold/*`
- `checks/*`
- `execution_plan.json`

这是最常用的“生成一个完整 V2 case”的入口。

### 3.8 `--phase execute`

读取已有的：

- `execution_plan.json`

并调用 `lark-cli` 执行真实飞书动作，生成：

- `execution_result.json`

### 3.9 `--phase collect`

读取：

- `execution_plan.json`
- `execution_result.json`

拉回真实消息，生成：

- `lark_fetch_records.jsonl`

### 3.10 `--phase adapt`

读取：

- `case_spec.json`
- `execution_result.json`
- `lark_fetch_records.jsonl`

生成：

- `openclaw_message_ingress.jsonl`
- `adapter_report.json`
- `build_report.json`

### 3.11 `--phase full`

一次性执行：

```text
compile -> execute -> collect -> adapt
```

如果只想演练，不真实发飞书消息：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase full --dry-run --skip-auth
```

## 4. 常用参数

| 参数 | 说明 | 适用阶段 |
| --- | --- | --- |
| `--case-spec` | 输入 case spec JSON 路径 | 生成层 / compile / full |
| `--dataset-root` | 输出根目录，默认 `amem_docs/ds/feishu_im_dataset_v2` | 全部 |
| `--case-dir` | 已存在 case 目录 | execute / collect / adapt |
| `--dry-run` | execute/full 时不真实发飞书消息 | execute / full |
| `--skip-auth` | 跳过 `lark-cli auth status` 检查 | execute / collect / full |
| `--resume` | 不先清理旧文件，复用现有产物 | 全部 |

## 5. 推荐执行顺序

### 第一步：先看 V2 case 是否合格

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase compile
```

重点检查：

- `input/case_world.json`
- `input/conversation_plan.json`
- `input/utterance_plan.jsonl`
- `data/realized_messages.jsonl`
- `gold/*`
- `checks/*`

### 第二步：先 dry-run

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase full --dry-run --skip-auth
```

重点检查：

- `execution_plan.json`
- `execution_result.json`

### 第三步：真实跑飞书链路

先确认：

```bash
lark-cli auth status
```

再执行：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase full
```

## 6. 当前 case 目录结构

一个 case 当前位于：

- `amem_docs/ds/feishu_im_dataset_v2/cases/<case_id>/`

标准结构：

```text
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

## 7. 当前已验证内容

当前已经验证过：

- `--phase compile`
- `--phase validate`
- `--phase full --dry-run --skip-auth`

并且当前示例 case 已经真实落到：

- `amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example`

## 8. 当前边界

当前脚本的边界是：

1. 还是 IM-only。
2. 当前 live 执行还是单 operator + 文本前缀角色模式。
3. `comment / doc` 还没进入 Builder 第一批 live 执行面。
4. 批量评测和 baseline scoring 还没接进这个脚本。

## 9. 一句话结论

当前脚本已经是：

> 一个面向 `amem_docs/ds/feishu_im_dataset_v2`、能够分阶段生成 V2 case、并可继续真实执行飞书链路的统一入口。
