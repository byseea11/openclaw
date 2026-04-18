# Eval

`eval/` 现在只做一件事：

`把 benchmark 原始样本适配成发给 OpenClaw 的原始输入，再把 OpenClaw 输出映射回 benchmark 官方 scorer 需要的格式。`

这里不要在 `eval/` 侧提前拆 memory，也不要在 `eval/` 侧替 OpenClaw 做 ingest。

正确边界应该是：

`benchmark raw sample`
-> `benchmark input adapter`
-> `OpenClaw raw input`
-> `OpenClaw ingest / memory / context`
-> `OpenClaw output`
-> `benchmark scorer`

也就是说：

- `eval/` 只负责 benchmark 适配和实验脚本
- `openclaw-main/` 负责真正的 memory 存储、更新、检索和 context assemble
- `Feishu` 是真实业务里的消息入口、消息出口和原始事件来源，但不是 memory 本身

---

## 一、统一设计原则

四个 benchmark 的统一抽象不要落到 `MemoryEvidence`。

更合适的统一层是：

```text
benchmark sample
    ↓
benchmark input adapter
    ↓
openclaw eval client
    ↓
benchmark-specific scorer
```

这里的关键是：

1. `benchmark input adapter`
   - 只把 benchmark 原始样本转成“按什么顺序把原始输入送进 OpenClaw”
   - 不在 `eval/` 侧提前替 OpenClaw 做 memory 拆分

2. `openclaw eval client`
   - 统一调 OpenClaw Gateway `POST /v1/responses`
   - 统一管理 `session_key`、`previous_response_id`、`message_channel`

3. `scorer`
   - 只关心 benchmark 官方输出格式
   - 不耦合 OpenClaw 内部实现

统一之后，四个 benchmark 的区别只剩三件事：

- 原始样本怎么读
- 原始样本怎么按顺序喂给 OpenClaw
- OpenClaw 输出怎么回写成 benchmark scorer 要的格式

---

## 二、当前已落地的基础骨架

目前 `eval/` 里已经先落了最小公共层：

```text
eval/
  README.md
  __init__.py
  base.py
  openclaw_client.py
  adapters/
    __init__.py
    locomo.py
    longmemeval.py
    tau2.py
    toolsandbox.py
  scorers/
    __init__.py
    common.py
    locomo.py
    longmemeval.py
    tau2.py
    toolsandbox.py
  scripts/
    run_locomo.py
    run_longmemeval.py
    run_tau2.py
    run_toolsandbox.py
```

其中：

- `base.py`
  - `BenchAdapter`
  - `MemAdapter`
  - `ToolAdapter`
  - `BenchmarkScorer`
  - `InputStep`
  - `ToolAdapterResult`

- `openclaw_client.py`
  - `OpenClawEvalClient`
  - `OpenClawEvalResponse`
  - `OpenClawToolCall`

这版基础骨架只做三件事：

1. 定义 benchmark 输入适配接口
2. 定义和 OpenClaw Gateway 通信的统一 client
3. 定义 benchmark scorer 接口

这里没有额外引入新的重型 orchestration 抽象。

LoCoMo / LongMemEval / tau2 / ToolSandbox 的循环控制，后续直接放在各自脚本里即可。

目前已经落地的文件对应关系是：

- `adapters/locomo.py`
  - `LoCoMoAdapter`
- `adapters/longmemeval.py`
  - `LongMemEvalAdapter`
- `adapters/tau2.py`
  - `Tau2Adapter`
  - `make_openclaw_tau2_agent_factory`
  - `make_openclaw_tau2_solo_agent_factory`
- `adapters/toolsandbox.py`
  - `ToolSandboxAdapter`
  - `build_toolsandbox_role`

- `scorers/locomo.py`
  - `LoCoMoScorer`
- `scorers/longmemeval.py`
  - `LongMemEvalScorer`
- `scorers/tau2.py`
  - `Tau2Scorer`
- `scorers/toolsandbox.py`
  - `ToolSandboxScorer`

- `scripts/run_locomo.py`
- `scripts/run_longmemeval.py`
- `scripts/run_tau2.py`
- `scripts/run_toolsandbox.py`

---

## 三、统一运行视角

建议统一把每个样本先转成一个“输入适配结果”：

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InputStep:
    kind: str
    input_items: list[dict[str, Any]]
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkInputAdapterResult:
    benchmark: str
    sample_id: str
    session_key: str
    message_channel: str
    setup_steps: list[InputStep]
    query_step: InputStep | None
    gold: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
```

这个结构里的重点是：

- `setup_steps`
  - 表示这条样本的历史、状态或工具结果应该如何按顺序送进 OpenClaw
- `query_step`
  - 表示最后的问题，或者下一步 observation
- `gold`
  - 只给 scorer 用，不写入 OpenClaw

它不是 memory 结构，只是输入顺序说明。

---

## 四、LoCoMo：一条样本如何处理

### 3.1 原始样本示例

LoCoMo 样本主字段是：

- `sample_id`
- `conversation`
- `qa`

其中一条 QA 大致像这样：

```json
{
  "sample_id": "conv_26",
  "conversation": {
    "speaker_a": "Alice",
    "speaker_b": "Bob",
    "session_1_date_time": "2023-07-01",
    "session_1": [
      {
        "dia_id": "D1:1",
        "speaker": "Alice",
        "text": "I will travel to Shanghai next Friday."
      },
      {
        "dia_id": "D1:2",
        "speaker": "Bob",
        "text": "Okay, remember to bring your laptop."
      }
    ]
  },
  "qa": [
    {
      "question": "Where will Alice travel next Friday?",
      "answer": "Shanghai",
      "evidence": ["D1:1"],
      "category": 4
    }
  ]
}
```

### 3.2 应该怎么处理

LoCoMo 本质上是：

- 长对话历史
- 最后提一个问题
- 看 OpenClaw 是否能通过自己的 memory/context 回答正确

所以 `eval/` 侧不应该先把它拆成 memory item。

应该做的是：

1. 读取一条 sample
2. 把 `conversation` 转成原始历史输入
3. 把 `qa.question` 作为最后的 query
4. 把 `answer/evidence/category` 留在 `gold`

### 3.3 为什么这样映射

因为 LoCoMo 测的是：

- 长对话记忆
- 事实召回
- 时间与多跳问答

而这些能力本质上应该落在 OpenClaw 的：

- ingest
- memory store
- retrieval
- context assemble

`eval/` 只需要保证“原始对话历史被正确送进 OpenClaw”。

### 3.4 输入适配示例

```python
result = BenchmarkInputAdapterResult(
    benchmark="locomo",
    sample_id="conv_26_q0",
    session_key="eval-locomo-conv_26-q0",
    message_channel="feishu",
    setup_steps=[
        InputStep(
            kind="history",
            input_items=[
                {"type": "message", "role": "user", "content": "Alice: I will travel to Shanghai next Friday."},
                {"type": "message", "role": "assistant", "content": "Bob: Okay, remember to bring your laptop."},
            ],
            metadata={"locomo_session": "session_1"},
        )
    ],
    query_step=InputStep(
        kind="query",
        input_items=[
            {"type": "message", "role": "user", "content": "Where will Alice travel next Friday?"}
        ],
    ),
    gold={
        "answer": "Shanghai",
        "evidence": ["D1:1"],
        "category": 4,
    },
)
```

这里 `message_channel="feishu"` 的意思不是说我们真的在跑飞书 API。

它的意思是：

- 让 OpenClaw 在和真实飞书场景更接近的 channel 语义下运行
- 真正的 memory/context 行为仍然发生在 OpenClaw 内部

### 3.5 LoCoMo 实验脚本伪代码

```python
def run_openclaw_locomo():
    args = parse_args()
    dataset = load_locomo_samples(args.input_path)
    client = OpenClawEvalClient(args.gateway_url, agent=args.agent)

    rows = []
    for sample in dataset:
        for qa_index, qa in enumerate(sample["qa"]):
            adapted = adapt_locomo_sample(sample, qa_index)

            for step in adapted.setup_steps:
                client.send(
                    session_key=adapted.session_key,
                    message_channel=adapted.message_channel,
                    input_items=step.input_items,
                    instructions=step.instructions,
                )

            response = client.send(
                session_key=adapted.session_key,
                message_channel=adapted.message_channel,
                input_items=adapted.query_step.input_items,
                instructions=adapted.query_step.instructions,
            )

            rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "qa_index": qa_index,
                    "prediction": response.text,
                    "gold_answer": adapted.gold["answer"],
                    "gold_evidence": adapted.gold["evidence"],
                    "raw": response.raw_payload,
                }
            )

    write_locomo_predictions(rows, args.output_path)
    score_locomo(rows)
```

---

## 五、LongMemEval：一条样本如何处理

### 4.1 原始样本示例

LongMemEval 样本主字段是：

- `question_id`
- `question`
- `answer`
- `question_type`
- `haystack_session_ids`
- `haystack_dates`
- `haystack_sessions`
- `answer_session_ids`

示例：

```json
{
  "question_id": "q_1",
  "question": "What music does the user like now?",
  "answer": "jazz music",
  "question_type": "single-session-user",
  "question_date": "2024-01-01",
  "haystack_session_ids": ["s1", "s2"],
  "haystack_dates": ["2023-12-20", "2024-01-05"],
  "haystack_sessions": [
    [
      {"role": "user", "content": "I love rock music.", "has_answer": false}
    ],
    [
      {"role": "user", "content": "Actually I mostly listen to jazz music now.", "has_answer": true}
    ]
  ],
  "answer_session_ids": ["s2"]
}
```

### 4.2 应该怎么处理

LongMemEval 比 LoCoMo 更强调：

- 更新
- 旧信息覆盖
- 拒答
- 跨 session

但这里也不能在 `eval/` 侧先替 OpenClaw 造“新旧 memory 关系”。

正确做法仍然是：

1. 把 `haystack_sessions` 按时间顺序送进 OpenClaw
2. 让 OpenClaw 自己 ingest 和记住这些原始内容
3. 最后再发 `question`
4. `answer / answer_session_ids / question_type` 只用于评分

### 4.3 为什么这样映射

LongMemEval 正好用来测试：

- OpenClaw 内部是否能处理信息更新
- assemble prompt 时是否能优先使用最新有效信息

所以它测的是 OpenClaw 的 memory/update/context 能力，而不是 `eval/` 的预处理能力。

### 4.4 输入适配示例

```python
result = BenchmarkInputAdapterResult(
    benchmark="longmemeval",
    sample_id="q_1",
    session_key="eval-longmemeval-q_1",
    message_channel="feishu",
    setup_steps=[
        InputStep(
            kind="history",
            input_items=[
                {"type": "message", "role": "user", "content": "I love rock music."},
            ],
            metadata={"source_session_id": "s1", "source_date": "2023-12-20"},
        ),
        InputStep(
            kind="history",
            input_items=[
                {"type": "message", "role": "user", "content": "Actually I mostly listen to jazz music now."},
            ],
            metadata={"source_session_id": "s2", "source_date": "2024-01-05"},
        ),
    ],
    query_step=InputStep(
        kind="query",
        input_items=[
            {"type": "message", "role": "user", "content": "What music does the user like now?"}
        ],
    ),
    gold={
        "answer": "jazz music",
        "answer_session_ids": ["s2"],
        "question_type": "single-session-user",
    },
)
```

### 4.5 LongMemEval 实验脚本伪代码

```python
def run_openclaw_longmemeval():
    args = parse_args()
    dataset = load_longmemeval_samples(args.input_path)
    client = OpenClawEvalClient(args.gateway_url, agent=args.agent)

    rows = []
    for sample in dataset:
        adapted = adapt_longmemeval_sample(sample)

        for step in adapted.setup_steps:
            client.send(
                session_key=adapted.session_key,
                message_channel=adapted.message_channel,
                input_items=step.input_items,
                instructions=step.instructions,
            )

        response = client.send(
            session_key=adapted.session_key,
            message_channel=adapted.message_channel,
            input_items=adapted.query_step.input_items,
        )

        rows.append(
            {
                "question_id": sample["question_id"],
                "hypothesis": response.text,
                "gold_answer": adapted.gold["answer"],
                "gold_session_ids": adapted.gold["answer_session_ids"],
                "raw": response.raw_payload,
            }
        )

    write_longmemeval_jsonl(rows, args.output_path)
    score_longmemeval(rows)
```

---

## 六、tau2-bench：一条任务如何处理

### 5.1 原始任务示例

tau2 不是静态 QA 数据，而是动态任务。

可以抽象成：

```json
{
  "task_id": "retail_task_42",
  "domain": "retail",
  "user_goal": "Check order 123 and update the shipping address to Shanghai.",
  "tools": [
    {"name": "get_order_status", "parameters": {"type": "object"}},
    {"name": "update_address", "parameters": {"type": "object"}}
  ]
}
```

### 5.2 应该怎么处理

tau2 的核心不是历史 QA，而是：

- 当前 observation
- OpenClaw 决定下一步 action
- 环境执行
- 工具结果继续回喂

所以它不应该被适配成“预先写入 memory，再最后问问题”的结构。

它应该被适配成：

- `step 0`: 用户目标进入 OpenClaw
- `step 1..n`: 工具结果通过 `function_call_output` 回喂
- 每一步都依赖同一个 `session_key` 和 `previous_response_id`

### 5.3 为什么这样映射

tau2 测的是：

- agent policy
- action selection
- 多轮 session continuity
- 工具使用正确性

这里最关键的是 OpenClaw 的：

- 多轮会话连续性
- client tool 调用
- 观察到行动的闭环

### 5.4 输入适配示例

第一步：

```python
InputStep(
    kind="observation",
    input_items=[
        {
            "type": "message",
            "role": "user",
            "content": "Check order 123 and update the shipping address to Shanghai."
        }
    ],
    tools=[
        {
            "type": "function",
            "name": "get_order_status",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
            "strict": True,
        },
        {
            "type": "function",
            "name": "update_address",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "address": {"type": "string"}
                }
            },
            "strict": True,
        },
    ],
)
```

工具结果回喂：

```python
InputStep(
    kind="tool_result",
    input_items=[
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "{\"status\": \"shipped\"}"
        }
    ],
)
```

### 5.5 tau2 实验脚本伪代码

```python
def run_openclaw_tau2():
    args = parse_args()
    tasks = load_tau2_tasks(args)
    client = OpenClawEvalClient(args.gateway_url, agent=args.agent)

    for task in tasks:
        session_key = make_session_key("tau2", task.id)
        previous_response_id = None
        observation = env.reset(task)

        for _ in range(args.max_steps):
            response = client.send(
                session_key=session_key,
                message_channel="tau2",
                input_items=convert_tau2_observation_to_input_items(observation),
                tools=convert_tau2_tools(task.tools),
                previous_response_id=previous_response_id,
            )
            previous_response_id = response.response_id

            action = parse_tau2_action(response)
            observation, done, info = env.step(action)
            if done:
                break
```

---

## 七、ToolSandbox：一条任务如何处理

### 6.1 原始任务示例

ToolSandbox 也不是普通 QA。

它更像：

```json
{
  "scenario_name": "calendar_booking",
  "instruction": "Schedule a meeting with Alice next Tuesday at 3 PM and confirm whether she is available.",
  "tools": [
    "calendar.check_availability",
    "calendar.create_event"
  ]
}
```

### 6.2 应该怎么处理

ToolSandbox 的流程是：

- 用户发 instruction
- OpenClaw 选择工具
- sandbox 执行工具
- 工具结果回喂 OpenClaw
- 直到返回 final answer 或任务结束

所以它和 tau2 一样，核心是“循环”，不是“先准备 memory 再问答”。

### 6.3 为什么这样映射

它重点测试：

- 工具名是否正确
- 参数是否正确
- 多轮状态是否维护正确
- 最终轨迹是否接近 benchmark 期望

因此 adapter 要做的只是：

- 把 scenario 变成一组 user/system/tool 轮次
- 统一交给 OpenClaw Gateway

### 6.4 输入适配示例

```python
InputStep(
    kind="observation",
    input_items=[
        {
            "type": "message",
            "role": "user",
            "content": "Schedule a meeting with Alice next Tuesday at 3 PM and confirm whether she is available."
        }
    ],
    tools=[
        {
            "type": "function",
            "name": "calendar.check_availability",
            "parameters": {"type": "object"},
            "strict": True,
        },
        {
            "type": "function",
            "name": "calendar.create_event",
            "parameters": {"type": "object"},
            "strict": True,
        },
    ],
)
```

如果模型先调用了 `calendar.check_availability`，下一轮回喂：

```python
InputStep(
    kind="tool_result",
    input_items=[
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "{\"available\": true}"
        }
    ],
)
```

### 6.5 ToolSandbox 实验脚本伪代码

```python
def run_openclaw_toolsandbox():
    args = parse_args()
    scenarios = load_toolsandbox_scenarios(args)
    client = OpenClawEvalClient(args.gateway_url, agent=args.agent)

    for scenario in scenarios:
        session_key = make_session_key("toolsandbox", scenario.name)
        previous_response_id = None
        pending_input_items = [
            {"type": "message", "role": "user", "content": scenario.instruction}
        ]

        for _ in range(args.max_steps):
            response = client.send(
                session_key=session_key,
                message_channel="toolsandbox",
                input_items=pending_input_items,
                tools=convert_toolsandbox_tools(scenario.tools),
                previous_response_id=previous_response_id,
            )
            previous_response_id = response.response_id

            parsed = parse_toolsandbox_response(response)
            if parsed.type == "final":
                save_final_answer(parsed.answer)
                break

            tool_result = sandbox.call(parsed.tool_name, parsed.arguments)
            pending_input_items = [
                {
                    "type": "function_call_output",
                    "call_id": parsed.call_id,
                    "output": tool_result,
                }
            ]
```

---

## 八、统一 OpenClaw Eval Client 应该长什么样

既然四个 benchmark 都要统一走 OpenClaw Gateway，建议先写一个最小 client：

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class OpenClawEvalResponse:
    response_id: str | None
    text: str
    tool_calls: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    latency_ms: float | None = None


class OpenClawEvalClient:
    def __init__(
        self,
        gateway_url: str,
        agent: str = "main",
        timeout_seconds: float = 180.0,
    ):
        ...

    def send(
        self,
        *,
        session_key: str,
        message_channel: str,
        input_items: list[dict[str, Any]],
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
        max_output_tokens: int | None = None,
    ) -> OpenClawEvalResponse:
        ...
```

统一请求原则：

- 全部走 `POST /v1/responses`
- 统一传 `x-openclaw-agent-id`
- 统一传 `x-openclaw-session-key`
- 统一传 `x-openclaw-message-channel`
- 多轮循环用 `previous_response_id`

---

## 九、这些设计和 OpenClaw memory/context 的关系

这里最重要的是边界不要搞混。

### 8.1 `eval/` 负责什么

`eval/` 负责：

- 读取 benchmark 原始样本
- 生成输入适配结果
- 调用 OpenClaw
- 保存结果
- 调 benchmark scorer

### 8.2 `openclaw-main/` 负责什么

`openclaw-main/` 负责：

- 接收原始输入
- ingest 成内部 memory
- 做 memory update
- 做 retrieval
- assemble 上下文
- 决定最终回答或工具调用

### 8.3 为什么不能在 `eval/` 侧先拆 memory

因为如果 `eval/` 侧提前替 OpenClaw 做了真正的 memory 拆分，那么测到的就不再是 OpenClaw 的 memory 能力，而是：

- benchmark adapter 的预处理能力
- 我们手工定义的 memory schema

这样实验边界会变脏。

所以 benchmark 输入应该尽量保持“原始历史 / 原始 observation / 原始工具结果”的形态。

---

## 十、Feishu 在这里是什么角色

Feishu 在真实系统里主要有三个角色：

1. 原始消息入口
2. 原始消息出口
3. 原始事件来源和 provenance 来源

但 Feishu 不是 memory 本身。

真正的 memory 实现应该在 OpenClaw 里。

更准确的理解是：

`Feishu 提供原始事件，OpenClaw 负责把这些原始事件 ingest 成 memory，并在回答时 assemble 成 context。`

所以如果后面要按照 `memory.md` 扩展，扩展重点应该放在：

- OpenClaw 的 event ingest
- OpenClaw 的 memory store
- OpenClaw 的 temporal update
- OpenClaw 的 context engine

而不是把 benchmark 数据集或 Feishu 出入站 payload 直接写成最终 memory 结构。

---

## 十一、推荐的真实开发顺序

### 第一步

先写统一的 `OpenClawEvalClient`

- 统一 Gateway 请求
- 统一 session 管理
- 统一 tool loop 接口

### 第二步

先改 `LoCoMo`

原因：

- 最接近“历史输入 + 最后问一个问题”
- 最容易验证“adapter 只负责输入适配，不负责 memory 拆分”的边界

### 第三步

再改 `LongMemEval`

原因：

- 可以复用 LoCoMo 的输入方式
- 只是在样本结构上多了“session 更新”和“拒答”

### 第四步

再改 `ToolSandbox`

原因：

- 开始验证统一 client 的工具循环能力

### 第五步

最后改 `tau2-bench`

原因：

- 环境交互和 agent loop 最复杂
- 应该在统一 client 和工具循环稳定之后再接

---

## 十二、最小目录方向

```text
eval/
  README.md
  base.py
  openclaw_client.py
  adapters/
    locomo_adapter.py
    longmemeval_adapter.py
    toolsandbox_adapter.py
    tau2_adapter.py
  scripts/
    run_openclaw_locomo.py
    run_openclaw_longmemeval.py
    run_openclaw_toolsandbox.py
    run_openclaw_tau2.py
  scorers/
    locomo.py
    longmemeval.py
```

这里：

- `adapter`
  - 只做 benchmark sample -> OpenClaw 原始输入适配
- `base.py`
  - 只放通用 adapter / scorer 抽象
- `openclaw_client.py`
  - 只做 OpenClaw Gateway 调用
- `scorers/`
  - 只做 benchmark 官方格式写回和评分

这才是后面继续重构的干净起点。

---

## 十三、当前联调状态

到 2026-04-15 为止，`eval/` 这套新链路已经完成了四部分验证：

1. 本地代码侧已经跑通
   - `LoCoMoAdapter`
   - `LongMemEvalAdapter`
   - `OpenClawEvalClient`
   - `run_locomo.py`
   - `run_longmemeval.py`
   都已经通过语法检查和最小样本加载检查

2. 本地端口连通性已经验证
   - 在提升权限后，`eval` 脚本已经可以真正向 `127.0.0.1:18789` 发请求
   - 当前需要通过 Gateway operator token 访问 OpenAI 兼容端点

3. 最小 smoke run 已经通过
   - `python3 -m eval.scripts.run_longmemeval --input eval/fixtures/longmemeval_smoke.json --max-samples 1`
   - `python3 -m eval.scripts.run_locomo --input locomo/data/locomo10.json --max-samples 1`
   - 两条命令都已经能通过本地 Gateway 拿到 OpenClaw 响应，并完成 scorer 输出

4. 交互型 benchmark 最小 case 已经接通
   - `tau2`:
     - `tau2-bench/.venv/bin/python -m eval.scripts.run_tau2 --domain mock --solo-mode --num-tasks 1`
     - benchmark 执行链路已完整跑完并落盘 summary
     - 当前 smoke 结果为 `avg_reward = 0.0`、`pass_hat_1 = 0.0`
     - 这说明 `tau2 env -> OpenClaw -> env` 链路已接通，但 agent 行为还需要继续调
   - `ToolSandbox`:
     - `ToolSandbox/.venv312/bin/python -m eval.scripts.run_toolsandbox --scenario wifi_off --user-type DeepSeek`
     - 已完成单场景运行并得到非零分数
     - 当前 smoke 结果为 `average_similarity = 0.7702`

当前已确认的运行前提是：

- Gateway 端口是 `http://127.0.0.1:18789`
- 需要 `Authorization: Bearer <OPENCLAW_TOKEN>`
- `/v1/responses` 已可用
- 建议模型名使用 `openclaw/default`

为了减少手工参数，`eval` 脚本现在已经支持自动读取项目根目录 `.env`：

- 优先使用 `--gateway-token`
- 若命令行未传，则回退到 `.env` / 环境变量中的 `OPENCLAW_TOKEN`

也就是说，现在下面这类命令可以直接跑：

```bash
python3 -m eval.scripts.run_longmemeval \
  --input eval/fixtures/longmemeval_smoke.json \
  --output outputs/openclaw_eval/longmemeval/smoke_predictions.jsonl \
  --max-samples 1
```

以及：

```bash
python3 -m eval.scripts.run_locomo \
  --input locomo/data/locomo10.json \
  --output outputs/openclaw_eval/locomo/smoke_predictions.json \
  --max-samples 1
```

当前 smoke 指标只用于链路验证，不代表 benchmark 最终效果：

- LongMemEval smoke:
  - `exact_match = 0.0`
  - `average_f1 = 0.2105`
- LoCoMo smoke:
  - `average_exact_match = 0.0`
  - `average_f1 = 0.0`
- tau2 smoke:
  - `avg_reward = 0.0`
  - `pass_hat_1 = 0.0`
- ToolSandbox smoke:
  - `average_similarity = 0.7702`
  - `average_milestone_similarity = 0.7702`
  - `average_minefield_similarity = 0.0`

这说明当前阶段已经验证了：

- adapter -> OpenClaw client -> Gateway -> model -> scorer

但还没有开始做真正的 prompt / memory / retrieval 效果优化。
