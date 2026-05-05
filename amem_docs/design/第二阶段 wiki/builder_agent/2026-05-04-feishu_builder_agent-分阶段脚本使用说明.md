# 2026-05-04 `feishu_builder_agent` 分阶段脚本使用说明

## 1. 脚本位置

- 脚本：`amem_docs/scripts/feishu-builder-agent-run.sh`
- 默认数据根：`amem_docs/ds/feishu_im_dataset_v2`
- 默认示例 case spec：`amem_docs/dataset_v1/case_specs/feishu_builder_case_example.json`

## 2. 当前 V2 主链

当前 Builder 的公开阶段已经收成：

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

这条链路的核心语义是：

- 前半段先定义 world / characters / conversation / target state
- `command-plan` 再把这些目标收成可执行的 `lark-cli` 动作
- `execute` 负责真实执行
- `collect` 负责把真实飞书消息拉回本地
- `gold` 负责把 target state 绑定到真实证据
- `validate` 负责做跨阶段一致性审计

## 3. 每个阶段在干什么

### 3.1 `--phase case-world`

生成：

- `input/case_seed.json`
- `input/case_world.json`

这一阶段的作用：

- 定义 case 的业务背景
- 定义组织结构、冲突轴、外部压力、隐藏约束、反转点
- 先确认这个 case 值不值得往后做

适合单独跑的场景：

- 只想先判断案例世界观是否合理
- 想先看复杂度方向对不对

### 3.2 `--phase characters`

生成：

- `input/characters.json`

这一阶段的作用：

- 给角色补职责、立场、风险偏好、信息掌握差异
- 为每个角色生成稳定的 `simulated_open_id`
- 把“谁会推动、谁会反对、谁会收口”定义清楚

这里的 `simulated_open_id` 可以理解成这套 benchmark 里的“模拟工号”：

- 它不等价于真实飞书用户 open_id
- 它由规则稳定生成：`ou_sim_<person_id>`
- 后续 `collect` 和 `adapt` 只能消费这张角色映射表，不能自行再拼 synthetic id

适合单独跑的场景：

- 只想检查角色画像是否像真实企业协作
- 想刷新角色映射和模拟工号

### 3.3 `--phase plan`

生成：

- `input/conversation_plan.json`

这一阶段的作用：

- 定义 topic、session、turn、状态演化、跨 source 修正
- 决定这是不是一个真正多轮、多 topic、会产生 current state 演化的 case

适合单独跑的场景：

- 只想检查会话结构是否满足评测强度

### 3.4 `--phase target-gold`

生成：

- `gold/target_state.json`

这一阶段的作用：

- 先定义这个 case 期望形成哪些 topic、Memory Block、current state
- 让 gold 不再只是“事后把结果抄一遍”

适合单独跑的场景：

- 先看评测目标是否清楚

### 3.5 `--phase command-plan`

生成：

- `input/command_plan.jsonl`
- `execution_plan.json`

这一阶段的作用：

- 把 conversation plan 变成真正要执行的飞书动作
- LLM 负责决定消息内容和动作意图
- 程序负责把动作编译成可执行 `lark-cli` 参数

适合单独跑的场景：

- 已经有 case 和 target gold，只想重新生成执行动作

### 3.6 `--phase execute`

生成：

- `execution_result.json`

这一阶段的作用：

- 执行 `execution_plan.json`
- 真正把消息发到飞书

适合单独跑的场景：

- 只想验证执行链是否正常

### 3.7 `--phase collect`

生成：

- `lark_fetch_records.jsonl`
- `data/collected_messages.jsonl`

这一阶段的作用：

- 拉取真实飞书消息
- 把真实 message/thread/chat 元数据整理回 dataset
- 把单一真实 sender 抬升成可评测的多角色语义
  - 保留 `actual_sender`
  - 生成 `simulated_speaker`
  - 生成 `normalized_actor_id`
  - 标记 `speaker_resolution_mode`
  - 其中 `simulated_speaker.open_id` 必须来自 `input/characters.json` 中的 `simulated_open_id`

适合单独跑的场景：

- 已经执行过了，只想重新拉取真实证据
- 想检查消息前缀和 `command_plan.speaker_ref` 是否一致

### 3.8 `--phase gold`

生成：

- `gold/expected_events.jsonl`
- `gold/expected_memory_blocks.json`
- `gold/expected_current_state.json`

这一阶段的作用：

- 把 `target_state` 绑定到真实 collected evidence
- 形成最终评测 gold

适合单独跑的场景：

- 已经 collect 完成，只想重建 gold

### 3.9 `--phase validate`

生成：

- `checks/conversation_complexity_report.json`
- `checks/dataset_validation_report.json`

这一阶段的作用：

- 做跨阶段一致性审计
- 检查：
  - `conversation_plan` 是否被 `command_plan` 覆盖
  - `command_plan` 是否真的执行成功
  - `collect` 是否拿回了真实 source session
  - `gold` 是否能回到真实 evidence
  - 复杂度是否达标

注意：

- 每个阶段结束后都会做**本阶段本地校验**
- `validate` 不是补做 schema 校验
- `validate` 的定位是**全链路一致性审计**

### 3.10 `--phase adapt`

生成：

- `openclaw_message_ingress.jsonl`
- `adapter_report.json`
- `build_report.json`

这一阶段的作用：

- 把真实飞书 fetch records 转成 OpenClaw 能消费的 ingress 产物
- 生成 replay/report
- 从 `execution_result` 和 fetch 命令参数里补回缺失的 `chat_id`
- 把 `characters.json` 中定义的 `simulated_open_id` 映射到最终 `sender.sender_id.open_id`

注意：

- `openclaw_message_ingress.jsonl` 里不会保留 `actual_sender` 或 `simulated_speaker` 这样的扩展顶层字段
- 最终只保留 `openclaw-lark` 真正会消费的标准 Feishu 事件字段
- 模拟身份通过标准字段 `sender.sender_id.open_id` 传入 OpenClaw

### 3.11 `--phase full`

作用：

- 从 `case_spec` 开始跑完整链路

适合单独跑的场景：

- 做一遍 end-to-end 演练

## 4. 常用示例

只想先确认 world 是否合理：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase case-world
```

已经有 conversation plan，只想重做可执行动作：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase command-plan --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
```

已经执行过飞书动作，只想重新 collect 和重建 gold：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase collect --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
amem_docs/scripts/feishu-builder-agent-run.sh --phase gold --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
```

只做最终一致性审计：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase validate --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
```

跑完整链路但不真的发飞书消息：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase full --dry-run --skip-auth
```

对真实 FEISHU-231 case 做 execute 之后，只想把后半段真实证据和 replay 刷新一遍：

```bash
amem_docs/scripts/feishu-builder-agent-run.sh --phase collect --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
amem_docs/scripts/feishu-builder-agent-run.sh --phase gold --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
amem_docs/scripts/feishu-builder-agent-run.sh --phase validate --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
amem_docs/scripts/feishu-builder-agent-run.sh --phase adapt --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
```

这一组命令适合：

- 执行动作已经发过，不想重复发消息
- 只想刷新真实 `collect / gold / checks / ingress`

## 5. 当前主契约

当前 V2 优先承诺的中间产物是：

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

`utterance_plan.jsonl` 和 `realized_messages.jsonl` 不再作为 V2 的公开主契约。

其中要特别注意：

- `data/collected_messages.jsonl`
  - 现在已经是 canonical 证据层对象
  - 它既包含真实 sender，也包含模拟 speaker
- `openclaw_message_ingress.jsonl`
  - 是 replay 给 OpenClaw 主链的直接输入

## 6. 真实 FEISHU-231 示例结果

当前示例 case：

- `amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example`

已经完成过一轮真实运行。当前结果是：

- `execution_result.json`
  - `status = success`
  - `25` 个动作全部成功
- `data/collected_messages.jsonl`
  - `20` 条文本消息
  - 每条带 `actual_sender + simulated_speaker + normalized_actor_id`
- `checks/dataset_validation_report.json`
  - `passed = true`
- `openclaw_message_ingress.jsonl`
  - `20` 条可 replay 的 ingress 事件

如果只是想人工 spot-check，建议按这个顺序看：

1. `execution_result.json`
2. `data/collected_messages.jsonl`
3. `gold/expected_events.jsonl`
4. `checks/dataset_validation_report.json`
5. `openclaw_message_ingress.jsonl`
