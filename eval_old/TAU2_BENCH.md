# OpenClaw 接入 tau2-bench 说明
这份文档专门解释 `tau2-bench` 这一项怎么接到 OpenClaw、怎么运行，以及结果应该怎么看。

## 1. 这个测试在测什么

`tau2-bench` 不是普通 QA benchmark，它测的是：

- 动态环境下的任务完成率
- 多轮交互中的工具选择与参数填写
- 对 domain policy 的遵守
- 在状态不断变化时是否还能保持一致行动

因此它特别适合验证 OpenClaw 在“长期协作 + 工具调用 + 环境变化”里的 agent 能力。

## 2. 当前接法

当前实现不是改 tau2 的 evaluator，而是只替换 agent：

1. tau2 继续负责：
   - task 选择
   - user simulator
   - environment tools
   - evaluator

2. OpenClaw 负责：
   - 生成 assistant 回复
   - 决定是否调用工具
   - 生成 tool call 参数

3. 中间桥接层：
   - `OpenClawTau2Agent`
   - `OpenClawOpenResponsesClient`

对应代码：

- [tau2_agent.py](/Users/byseea/programscoding/nanobot/eval/openclaw/agents/tau2_agent.py)
- [openresponses_client.py](/Users/byseea/programscoding/nanobot/eval/openclaw/openresponses_client.py)
- [run_openclaw_tau2_eval.py](/Users/byseea/programscoding/nanobot/eval/scripts/run_openclaw_tau2_eval.py)

## 3. 实现流程

### 3.1 输入怎么转

tau2 传进来的消息主要有两类：

- `UserMessage`
- `ToolMessage`

桥接层会把它们分别转成 OpenResponses 输入：

- 用户消息 -> `{"type": "message", "role": "user", "content": ...}`
- 工具返回 -> `{"type": "function_call_output", "call_id": ..., "output": ...}`

### 3.2 工具 schema 怎么转

tau2 里的工具本身已经有 OpenAI 风格 schema。桥接层只做一层补齐：

- 保留 `function` schema
- 补 `strict = true`

这样 OpenClaw 可以直接按函数调用格式请求工具。

### 3.3 输出怎么转回 tau2

OpenClaw Gateway `/v1/responses` 返回后：

1. 如果有 `function_call`
   - 转成 tau2 的 `ToolCall`
   - 返回 `AssistantMessage(tool_calls=...)`

2. 如果没有工具调用
   - 直接把文本转成 `AssistantMessage(content=...)`

## 4. 伪代码

```text
state = {
    session_key,
    previous_response_id,
    transcript
}

def generate_next_message(message, state):
    if message is UserMessage:
        input_items = [convert_user_message(message)]
    elif message is ToolMessage:
        input_items = [convert_tool_output(message)]

    response = openclaw_gateway.responses.create(
        input=input_items,
        instructions=system_prompt + domain_policy,
        tools=tau2_tools,
        previous_response_id=state.previous_response_id
    )

    state.previous_response_id = response.id

    if response has tool_calls:
        return AssistantMessage(tool_calls=convert_tool_calls(response)), state
    return AssistantMessage(content=response.text), state
```

## 5. 如何运行

最小 smoke：

```bash
.venv/bin/python -m eval.scripts.run_openclaw_tau2_eval \
  --domain mock \
  --user-model openai/gpt-4.1-mini \
  --gateway-base-url http://127.0.0.1:18789 \
  --openclaw-agent-id main \
  --num-trials 1 \
  --num-tasks 3
```

带模型覆盖：

```bash
.venv/bin/python -m eval.scripts.run_openclaw_tau2_eval \
  --domain mock \
  --user-model openai/gpt-4.1-mini \
  --gateway-base-url http://127.0.0.1:18789 \
  --openclaw-agent-id main \
  --model-override openai-codex/gpt-5.4 \
  --num-trials 1 \
  --num-tasks 3
```

## 6. 输出怎么看

脚本会打印：

- `run_name`
- `gateway_base_url`
- `openclaw_agent_id`
- `evaluation_type`
- `avg_reward`
- `pass^1`
- `results_dir`

建议的解读方式：

1. `avg_reward`
   - 更接近整体任务完成质量。

2. `pass^1`
   - 更接近一次尝试内能否做对。

3. `results_dir`
   - 里面保留了 tau2 官方结果结构，后续可以继续用 tau2 自带分析工具看失败轨迹。

## 7. 当前状态与实验结论

当前仓库还没有提交 tau2 的正式 benchmark 结果文件，但这并不表示 tau2 接入还没做。

目前已经完成的是：

1. OpenClaw agent 工厂注册。
2. 消息与工具 schema 转换。
3. Gateway 调用封装。
4. 脚本级单元测试。

也就是说，tau2 这部分现在缺的是“外部完整运行环境下的正式跑分”，不是缺实现。

## 8. 当前局限

- 只支持 text / half-duplex 路径。
- 结果仍然依赖 tau2 的外部依赖与 user simulator 模型配置。
- 如果模型配置不合适，跑分反映的会是“模型/权限问题”，不一定是桥接层问题。

## 9. 推荐下一步

1. 先用 `mock` domain 跑小样本 smoke。
2. 确认 `avg_reward` 和 `pass^1` 能稳定产出。
3. 再扩到 `airline`、`retail`、`telecom` 等 domain。
