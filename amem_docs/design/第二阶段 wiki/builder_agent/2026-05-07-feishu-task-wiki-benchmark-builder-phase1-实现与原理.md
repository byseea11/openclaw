# Feishu Task Wiki Benchmark Builder Phase 1 实现与原理

## 阶段目标

Phase 1 的目标不是“编故事”。

它要生成一个可以真实执行、可以从飞书回收 observed data、可以进入 OpenClaw Task Wiki replay 的企业协作数据集。

这个数据集要同时满足三件事：

- 有明确的目标任务和评测 family。
- 有真实可发送、可 fetch、可追踪的企业消息。
- 有足够多的重要信息、相似信息、私有信息、正式文件信息和上下文噪声，让原生个人记忆或摘要式记忆容易混淆，但 Task Wiki 可以依靠任务结构、证据和 current-state 投影胜出。

Phase 1 的输出不是最终分数。

它输出的是评测所需的真实输入层：

- `input/*`：生成计划、人物、状态、coverage、对话和执行计划。
- `runtime/executed_commands.jsonl`：真实执行记录。
- `data/collected_messages.jsonl`：从飞书回收的 observed messages。
- `data/openclaw_message_ingress.jsonl`：给 OpenClaw Task Wiki replay 的标准输入。
- `checks/pre_annotation_validation_report.json`：进入 gold 前的落地检查。

## 正式 Family

当前正式数据集方向只有四类。

每个 case 默认只选择一个 family。批量数据集通过多个 case 覆盖四类 family，而不是在单个 case 里混合多个正式 family。

### `anti_interference`

这一类测试抗干扰能力。

数据构造会让目标任务附近出现相似措辞、共享角色、相近状态和跨 session 噪声。原生记忆容易把其他上下文的 owner、状态、日期或结论混进目标任务。

Task Wiki 应该通过 `task_id`、session trace、evidence quote 和当前状态投影，把目标任务事实和干扰内容分开。

### `contradiction_update`

这一类测试矛盾更新和 current-state 选择。

数据构造会让同一个字段经历 initial、historical、current 和 supersession。旧口径会真实出现，后续修正也会真实出现。

原生记忆容易记住早期明确表达，却忽略后续覆盖关系。Task Wiki 应该把历史值保留为 evidence，同时把最终有效值投影成 current state。

### `evidence_dependency_reasoning`

这一类测试证据依赖和影响传播。

数据构造会包含 verified、ambiguous、hearsay、upstream dependency、downstream impact 等证据梯度。某个上游事实是否成立，会影响目标任务的判断。

原生记忆容易把传闻、确认、影响范围混成同一个摘要。Task Wiki 应该区分证据强度，并把依赖链中真正被验证的事实投影到任务维度。

### `private_info_in_official_file`

这一类测试个人私有信息和正式任务事实的边界。

数据构造会把个人时间限制、偏好、私聊承诺或个人备注放进正式文件、纪要、上线 checklist 或风险登记表附近，并让聊天里出现引用、误读和纠正。

原生个人记忆容易把“某个人的私有信息”写成任务 current state。Task Wiki 应该只把与目标任务有关、且有正式 evidence 支撑的信息投影成任务事实，个人私有信息只能作为 context 或 evidence。

## Phase 1 主链路

```text
spec-generation
-> family-selection
-> capability-brief
-> family context skill
-> task-actor-layout
-> case-world
-> characters
-> state-trajectory
-> coverage-spec
-> story-beats
-> conversation-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
```

`family context skill` 按 `family_id` 路由：

- `anti_interference` 使用 `anti-interference-context.md`
- `contradiction_update` 使用 `contradiction-update-context.md`
- `evidence_dependency_reasoning` 使用 `evidence-dependency-context.md`
- `private_info_in_official_file` 使用 `private-info-official-file-context.md`

## Stage-by-stage 实现表

| Stage | 做什么 | 怎么生成 | 为什么需要它 | 下游如何使用 |
| --- | --- | --- | --- | --- |
| `spec-generation` | 生成最小 case control。 | 根据 difficulty、seed、comparison target 和显式 family 生成 `case_id`、`task_id`、`family_id`。 | 先固定评测对象和可复现身份，避免后续阶段自行发明任务。 | 后续所有 artifact 都继承同一个 case/task/family。 |
| `family-selection` | 确定本 case 的正式 family。 | 如果用户显式指定则服从，否则按 seed policy 在四类 family 中选一个。 | family 是失败机制来源，决定这个 case 要测哪种能力。 | 路由到对应 family context skill，并约束 capability、layout、state、coverage 和 transcript。 |
| `capability-brief` | 把 family 翻译成能力约束。 | 读取 family context 和 difficulty minima，生成能力、失败原因、生成规则、required structure 和 probe strategy。 | 它把抽象 family 变成可执行的生成条件。 | 约束 layout、state trajectory、coverage spec 和后续 probe。 |
| `family context skill` | 提供 family-specific 结构语义。 | 由当前 family 的 skill 定义角色、证据、状态变化、干扰或私有信息边界。 | 同一条生成链可以覆盖不同 failure mechanism，但不会丢掉 family 细节。 | 被 capability、layout、world、state、beats、conversation 共同引用。 |
| `task-actor-layout` | 定义角色槽位和协作结构。 | 读取 case control、capability brief 和 family context，生成 actor roster、shared actors、context blocks、overlap。 | 企业协作失败通常来自角色重叠和信息分散，不是单条消息。 | characters 实例化人物；conversation-plan 引用角色槽位。 |
| `case-world` | 定义企业世界和 source sessions。 | 把 layout 翻译成部门、会话、文件、协作背景和信息分布原因。 | 它解释为什么这些消息会自然发生，而不是硬塞 trap。 | characters、state、beats 和 conversation 使用同一套企业背景。 |
| `characters` | 把角色槽位实例化成人。 | 根据 actor roster 生成 `characters.json`，并生成 `actor_registry.json`。 | 需要稳定人物身份，才能把真实单 operator 执行映射成多人物 replay。 | command-plan、collect 和 OpenClaw ingress 都依赖 actor registry。 |
| `state-trajectory` | 定义状态演进。 | 按 family 生成 current、historical、supersession、dependency impact、干扰边界或私有信息边界。 | 评测不是只看消息存在，而是看系统能否理解状态变化。 | coverage-spec 和 semantic gold 都依赖这些 expected state relations。 |
| `coverage-spec` | 定义必须落地的检查项。 | 把 capability、state 和 family requirements 转成 evidence、beat、state、probe coverage。 | 它是 Phase 1 的落地验收标准，防止 LLM 生成漂亮但不可评测的对话。 | pre-annotation-validate 用它检查 observed data 是否合格。 |
| `story-beats` | 定义关键 beat skeleton。 | 把 required roles、context blocks、state requirements 映射到 session 和 benchmark role。 | beat 是“必须出现的关键证据点”，不是全量消息。 | conversation-plan 把 beat 扩展成完整企业 transcript。 |
| `conversation-plan` | 生成完整企业对话。 | LLM 读取 layout、world、characters、state、beats、official file plan 和 difficulty scale，生成完整 turns。 | 真实企业感来自多角色、多 session、追问、误读、纠偏、ack 和跨 session 转述，不能靠模板刷屏。 | command-plan 把每个 turn 编译成真实 action；annotation 只标注 target turns。 |
| `command-plan` | 生成真实 `lark-cli` action rows。 | 读取 conversation plan、characters、actor registry，生成 create/send/reply/fetch action、dependency、output ref 和 command preview。 | 它把自然对话变成可审查、可执行、可回收的操作计划。 | execute 按 dependency graph 调用真实 `lark-cli`。 |
| `execute` | 执行 action plan。 | 做 auth/preflight 后，按 dependency graph 调用 `lark-cli`，记录 stdout、stderr、returncode 和 resource ids。 | 只有真实执行，后续 observed data 才不是 planned text。 | collect 使用真实 chat/message/thread ids fetch 消息。 |
| `collect` | 回收 observed messages。 | 根据 execution result 调用 chat/thread fetch，把真实飞书消息写成 benchmark observed data。 | 它把计划消息替换成真实 message_id、真实时间和真实会话位置。 | Phase 2 gold、runtime replay 和评分全部只信 observed data。 |
| `pre-annotation-validate` | 做进入 gold 前的落地检查。 | 基于 coverage spec、conversation plan、command plan、collected messages 和 OpenClaw ingress 检查落地情况。 | 它防止没有实际证据的 case 进入评测。 | 通过后 Phase 2 才能生成可靠 gold。 |

## 关键原理

Phase 1 可以生成有效数据，是因为它不是一次性让模型输出完整 benchmark。

它把生成拆成四层控制：

- `family` 定义失败方向。
- `capability-brief` 定义生成约束和 probe 策略。
- `coverage-spec` 定义必须落地的证据和状态。
- `conversation-plan` 用 LLM 把这些约束变成完整企业 transcript。

这四层让 LLM 负责自然语言和企业协作复杂度，但不让 LLM 自由决定评测边界。

随后 `command-plan -> execute -> collect` 把计划落成真实飞书消息。Phase 2 不读取“理想计划文本”作为事实，只读取 collected observed messages。

这也是为什么 Phase 1 的数据能用于评分：评分对象看到的是 replay 输入和真实 message evidence，而不是 builder 的内部想象。

## 身份与 OpenClaw 对齐

真实飞书执行可以由同一个 operator 完成，但 benchmark 需要模拟多个协作者。

当前链路是：

```text
characters
-> actor_registry
-> simulated_open_id
-> command-plan prefix
-> collect speaker resolution
-> openclaw_message_ingress
```

`characters.json` 定义人物资料。

`actor_registry.json` 定义稳定 actor registry，并为每个人生成 `simulated_open_id`。

`command-plan` 发送消息时在正文前加 `【department/name】` 前缀，帮助 collect 阶段把真实 fetch 回来的消息解析回 benchmark speaker。

`collected_messages.jsonl` 同时保留两套身份：

- `actual_sender`：飞书真实 sender。
- `simulated_speaker`：benchmark 语义人物。

`openclaw_message_ingress.jsonl` 会剥掉文本前缀，并把 sender open id 写成 `simulated_open_id`。

这样 OpenClaw replay 看到的是多人物企业协作，而不是单 operator 自言自语。

## 质量边界

`pre_annotation_validation_report.json` 是 Phase 1 的质量闸门。

它至少要检查：

- 总消息数是否满足 difficulty 规模。
- source session 分布是否足够。
- family-required evidence 是否真的出现在 observed messages。
- state transition、supersession、dependency impact、interference boundary 或 private-info boundary 是否落地。
- `annotation_target` 和 `event_bearing` 是否能对应真实 message。
- official file / private info 引用是否实际进入 transcript。
- `openclaw_message_ingress.jsonl` 是否覆盖所有真实协作消息。

如果这些检查不通过，Phase 2 不应该把这个 case 当作有效评测样本。

## Phase 3 边界

Phase 3 属于后续 baseline、value comparison 和 benchmark report。

本文只解释 Phase 1 如何生成可评测 observed data。
