# 企业长期记忆评测实验方案
这份文档的目标不是只列命令，而是把 4 套 benchmark 的实现方法、伪代码、实验输出和当前结果解释清楚，方便后续直接写实验章节或复现实验。

## 1. 评测分成两条路线

不要把下面两件事混在一起：

1. `官方格式 baseline`
   - 目标：尽量保持 benchmark 原生输入输出格式，测 OpenClaw 的原始能力。
   - 特点：不先统一转成 `MemoryEvalDataset`。

2. `统一 harness ablation`
   - 目标：横向比较不同 memory 策略，例如 query-aware retrieval、时间冲突消解、压缩、重排。
   - 特点：同一批样本、同一套指标、多方法可比。

本轮工作优先做第一条：把 4 套 benchmark 全部接上 OpenClaw 的官方或准官方运行链路。

## 2. 当前范围

本阶段不先构造 `demo_data/feishu_mock`。先用仓库内已经存在的 benchmark 数据把 OpenClaw 官方 baseline 跑通，再进入企业办公专属数据阶段。

## 3. 四个 benchmark 的角色

| Benchmark | 主要评测能力 | OpenClaw 集成方式 | 当前状态 |
| --- | --- | --- | --- |
| LoCoMo | 长对话、多 session QA、时间推理、对抗/no-answer | 原生 conversation 渲染成 `MEMORY.md`，输出 LoCoMo 风格 prediction JSON | 已完成，已有实测结果 |
| LongMemEval | 更新、跨 session 推理、时间一致性、拒答 | 原生 JSON 渲染成 session markdown，输出官方 JSONL | 已完成 runner 与测试 |
| tau2-bench | 动态环境里的任务完成率、policy 遵守、多轮工具决策 | 实现 `OpenClawTau2Agent`，复用 tau2 evaluator | 已完成 adapter 与测试 |
| ToolSandbox | stateful tool use、隐式依赖、错误参数、轨迹相似度 | 实现 `OpenClawToolSandboxRole`，复用 ToolSandbox evaluator | 已完成 adapter 与测试 |

## 4. Phase 1：OpenClaw 官方 baseline

### 4.1 LoCoMo

#### 实现说明

LoCoMo 的核心是保持原始 sample/qa 结构不变，只把 conversation 渲染成 OpenClaw 可索引的记忆文件。

实现路径：

1. 读取 `locomo/data/locomo10.json`。
2. 每个 sample 创建独立 workspace/state。
3. 用 `render_locomo_memory()` 把 conversation 变成带 `session_id`、`turn_id` 的 `MEMORY.md`。
4. 调 `openclaw memory index` 建索引。
5. 对每个 QA 运行两种模式之一：
   - `memory-search-snippet`
   - `agent`
6. 将结果写回 LoCoMo 官方风格 JSON。

关键代码：

- [locomo.py](/Users/byseea/programscoding/nanobot/eval/openclaw/official/locomo.py)
- [run_openclaw_locomo_official.py](/Users/byseea/programscoding/nanobot/eval/scripts/run_openclaw_locomo_official.py)

#### 伪代码

```text
samples = load_json(locomo10.json)
for sample in samples:
    workspace = make_workspace(sample_id)
    write(MEMORY.md, render_locomo_memory(sample))
    write(openclaw.json, config_for_workspace(workspace))
    openclaw("memory index")

    for qa in sample.qa:
        if answer_mode == "memory-search-snippet":
            results = openclaw("memory search")
            prediction = top_snippet(results)
            context_ids = extract_dialog_ids(results)
        else:
            prediction = openclaw("agent --message <qa question>")
            context_ids = []

        qa.prediction = prediction
        qa.recall = recall(qa.evidence, context_ids)
        qa.f1 = locomo_f1(qa.answer, prediction)
```

#### 运行命令

```bash
.venv/bin/python -m eval.scripts.run_openclaw_locomo_official \
  locomo/data/locomo10.json \
  --max-samples 1 \
  --max-qas-per-sample 5 \
  --output outputs/openclaw_official/locomo/locomo1x5_predictions.json \
  --stats-output outputs/openclaw_official/locomo/locomo1x5_stats.json
```

#### 当前实测结果

结果文件：

- [locomo1x5_stats.json](/Users/byseea/programscoding/nanobot/outputs/openclaw_official/locomo/locomo1x5_stats.json)
- [smoke_stats.json](/Users/byseea/programscoding/nanobot/outputs/openclaw_official/locomo/smoke_stats.json)
- [agent_smoke_stats.json](/Users/byseea/programscoding/nanobot/outputs/openclaw_official/locomo/agent_smoke_stats.json)

结果摘要：

| 运行 | 模式 | sample_count | qa_count | average_f1 | average_recall | average_latency_ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `locomo1x5` | `memory-search-snippet` | 1 | 5 | 0.0082 | 0.2 | 12355.39 |
| `smoke` | `memory-search-snippet` | 1 | 1 | 0.0 | 1.0 | 13033.301 |
| `agent_smoke` | `agent` | 1 | 1 | 0.0 | 0.0 | 19164.833 |

#### 结果分析

1. `memory-search-snippet` 是检索代理指标，不是最终答案生成指标。
   - 它直接把首条片段当答案。
   - 所以即使召回对了，F1 也可能很低。

2. `smoke` 里 `recall = 1.0` 而 `F1 = 0.0`，说明检索把金证据捞到了，但答案抽取/压缩没做好。

3. `locomo1x5` 中 `average_recall = 0.2` 说明当前 stock memory search 的 top-k 覆盖还不稳定，尤其在跨 session、时间问题上容易漂移。

4. `agent_smoke` 的失败主要来自模型鉴权：
   - 错误信息指向 `openai/gpt-5.4` 缺少 `OPENAI_API_KEY`。
   - 当前环境更适合切到 `openai-codex/gpt-5.4`。
   - 这说明 agent 模式还没有得到公平评测，下一步应先修正运行配置再比较。

### 4.2 LongMemEval

#### 实现说明

LongMemEval 关注多 session 记忆、知识更新、拒答和时间一致性。这里没有把它压成统一 schema，而是保留原始字段：

- `question_id`
- `question`
- `answer`
- `haystack_session_ids`
- `haystack_dates`
- `haystack_sessions`
- `answer_session_ids`

实现路径：

1. 读取 LongMemEval 原始 JSON。
2. 用 `render_longmemeval_memory()` 渲染出 session markdown。
3. 调 OpenClaw 建索引。
4. 用 `memory-search-snippet` 或 `agent` 回答。
5. 生成官方 JSONL：

```json
{"question_id": "...", "hypothesis": "..."}
```

6. 同时写 detail JSON，方便本地分析召回、拒答和时延。

关键代码：

- [longmemeval.py](/Users/byseea/programscoding/nanobot/eval/openclaw/official/longmemeval.py)
- [run_openclaw_longmemeval_official.py](/Users/byseea/programscoding/nanobot/eval/scripts/run_openclaw_longmemeval_official.py)

#### 伪代码

```text
samples = load_json(longmemeval.json)
for sample in samples:
    write(MEMORY.md, render_longmemeval_memory(sample))
    openclaw("memory index")

    if answer_mode == "agent":
        hypothesis = openclaw("agent --message <prompt>")
        retrieved_session_ids = []
    else:
        results = openclaw("memory search")
        hypothesis = first_clean_snippet(results)
        retrieved_session_ids = extract_session_ids(results)

    write_jsonl({"question_id": sample.question_id, "hypothesis": hypothesis})
    details.append({
        "evidence_recall": recall(sample.answer_session_ids, retrieved_session_ids),
        "abstention_correct": check_abstention(sample, hypothesis),
        "latency_ms": latency
    })
```

#### 运行命令

```bash
.venv/bin/python -m eval.scripts.run_openclaw_longmemeval_official \
  LongMemEval/data/your_split.json \
  --output outputs/openclaw_official/longmemeval/predictions.jsonl \
  --detail-output outputs/openclaw_official/longmemeval/details.json
```

#### 当前结果解读

仓库内当前还没有 LongMemEval 的正式结果文件，但 runner 与单元测试已经齐。

现阶段可以先得出两个结论：

1. 官方提交格式已经打通，不需要再临时写转换脚本。
2. detail JSON 里已经预留了 `evidence_recall`、`abstention_correct`、`latency_ms`，后续实验章节可以直接复用。

### 4.3 tau2-bench

#### 实现说明

tau2-bench 测的是“动态环境里的 agent 任务完成率”，重点不是单条 QA，而是多轮环境交互。

这里的接法是：

1. 保留 tau2 自己的 task set、环境和 user simulator。
2. 让 `OpenClawTau2Agent` 实现 tau2 的 `HalfDuplexAgent`。
3. 用 Gateway `/v1/responses` 把 OpenClaw 当成可调用的 agent。
4. 把 tau2 的工具 schema 转成 OpenAI function schema。
5. 再把 OpenClaw 的 tool call 转回 tau2 的 `ToolCall`。

关键代码：

- [tau2_agent.py](/Users/byseea/programscoding/nanobot/eval/openclaw/agents/tau2_agent.py)
- [run_openclaw_tau2_eval.py](/Users/byseea/programscoding/nanobot/eval/scripts/run_openclaw_tau2_eval.py)
- [openresponses_client.py](/Users/byseea/programscoding/nanobot/eval/openclaw/openresponses_client.py)

#### 伪代码

```text
register_agent_factory(
    name="openclaw_tau2_agent",
    factory=OpenClawTau2Agent(...)
)

for tau2_turn in conversation:
    if input is user_message:
        openresponses_input = [{"type": "message", "role": "user", "content": text}]
    else if input is tool_message:
        openresponses_input = [{"type": "function_call_output", ...}]

    response = gateway.responses.create(
        input=openresponses_input,
        tools=tau2_tool_schemas,
        previous_response_id=state.previous_response_id
    )

    if response has tool_calls:
        return AssistantMessage(tool_calls=...)
    else:
        return AssistantMessage(content=response.text)
```

#### 运行命令

```bash
.venv/bin/python -m eval.scripts.run_openclaw_tau2_eval \
  --domain mock \
  --user-model openai/gpt-4.1-mini \
  --gateway-base-url http://127.0.0.1:18789 \
  --openclaw-agent-id main \
  --num-trials 1 \
  --num-tasks 3
```

#### 当前结果解读

仓库里目前还没有提交 tau2 的正式跑分结果，但接口层已经具备：

1. 独立 agent 工厂注册。
2. Gateway 响应转 `AssistantMessage` / `ToolCall`。
3. 官方 evaluator 继续负责 `avg_reward` 和 `pass^1`。

这意味着后续真实实验时，瓶颈主要不在适配层，而在模型配置、环境依赖和具体 domain。

### 4.4 ToolSandbox

#### 实现说明

ToolSandbox 关注 stateful tool use，不是只看“有没有调用工具”，而是看：

- 工具顺序对不对
- 参数对不对
- 是否利用了前面轮次的隐式状态
- 与参考轨迹的 milestone / minefield 相似度

实现路径：

1. 保留 ToolSandbox 的 scenario、execution environment 和 evaluator。
2. 用 `OpenClawToolSandboxRole` 实现 agent 角色。
3. 把 ToolSandbox 的 user/system/tool 消息转成 OpenResponses 输入。
4. 如果 OpenClaw 发起函数调用，则转成 ToolSandbox execution environment 能执行的 Python 代码。
5. 由 ToolSandbox evaluator 返回 summary。

关键代码：

- [toolsandbox_role.py](/Users/byseea/programscoding/nanobot/eval/openclaw/agents/toolsandbox_role.py)
- [run_openclaw_toolsandbox_eval.py](/Users/byseea/programscoding/nanobot/eval/scripts/run_openclaw_toolsandbox_eval.py)

#### 伪代码

```text
for scenario in scenarios:
    roles = {
        USER: user_factory(),
        EXECUTION_ENVIRONMENT: ExecutionEnvironment(),
        AGENT: OpenClawToolSandboxRole(...)
    }

    result = scenario.play_and_evaluate(roles=roles)
    summary.append({
        "similarity": result.similarity,
        "milestone_similarity": result.milestone_similarity,
        "minefield_similarity": result.minefield_similarity
    })
```

#### 运行命令

```bash
.venv/bin/python -m eval.scripts.run_openclaw_toolsandbox_eval \
  --gateway-base-url http://127.0.0.1:18789 \
  --openclaw-agent-id main \
  --scenario single_tool_call_scenarios
```

#### 当前结果解读

仓库里当前还没有 ToolSandbox 的正式 benchmark 结果文件，但已经能输出统一的 `result_summary.json`，包含：

- `average_similarity`
- `average_milestone_similarity`
- `average_minefield_similarity`
- `categories`
- `results`

所以后续真实实验只需准备完整 ToolSandbox 运行环境，不需要再改结果汇总逻辑。

## 5. Phase 2：统一 harness ablation

当 4 个 benchmark 官方 baseline 稳定后，再进入统一 harness 比较。建议比较的方法：

1. `openclaw_stock_memory_search`
2. `openclaw_active_memory`
3. `enterprise_selector`
4. `enterprise_selector_temporal_resolver`
5. `enterprise_selector_temporal_compressor`
6. `enterprise_full_query_aware_context`

建议统一指标：

- Recall@k
- MRR
- Gold evidence in final prompt
- Answer F1
- Prompt tokens
- Latency
- Abstention accuracy
- Temporal/update accuracy

## 6. 当前实验结论

基于仓库内已有结果和当前实现状态，可以先写出下面几条结论：

1. OpenClaw 的 benchmark 原生接入已经不再只停留在 LoCoMo。
   - LoCoMo、LongMemEval、tau2-bench、ToolSandbox 四条链路都已经有代码入口。

2. 真正已经落盘的实测结果目前主要来自 LoCoMo。
   - 这套结果表明 stock memory search 能在部分问题上召回金证据，但“把片段直接当答案”的策略会显著拉低 F1。

3. 当前最值得优先推进的不是再加新 benchmark，而是：
   - 跑通 LoCoMo `agent` 模式；
   - 产出 LongMemEval 正式结果；
   - 再向交互型 benchmark（tau2、ToolSandbox）推进。

4. 另外 3 个 benchmark 当前处于“实现完成、等待外部完整运行环境”的阶段。
   - 这不是“还没做”，而是“代码接入已经完成，但正式实验还没全部出数”。

## 7. 后续补数建议

推荐按下面顺序补齐正式实验：

1. 修正 LoCoMo `agent` 模式模型配置，得到第一组可比结果。
2. 跑 LongMemEval 小样本 smoke，先验证 `exact_match`、`evidence_recall`、`abstention_accuracy`。
3. 跑 tau2 `mock` domain，先拿到 `avg_reward` 和 `pass^1`。
4. 跑 ToolSandbox 的单场景 smoke，再扩到多场景。
