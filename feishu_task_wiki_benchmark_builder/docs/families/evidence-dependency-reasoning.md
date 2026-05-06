# evidence_dependency_reasoning

## 本质

这类 family 测的是：系统能不能先区分 verified fact、转述和猜测，再用可信证据解释上游风险如何影响目标任务以及与之相关的下游影响。

## 为什么默认记忆系统容易失败

因为默认 summary 容易把不同强度的说法压成一句“结论”，或者只记住上游和下游片段，却没有把可信证据和影响链连起来。

## 失败原理

失败来自两层同时缺失：

- evidence strength 丢失
- impact chain 丢失

只有先判断哪条消息可信，后面的 blocker 和 dependency reasoning 才成立。

## 为什么这个 hard case 会难倒弱记忆系统

- 弱记忆系统常把 verified、hearsay、ambiguous 全压成一句“现在看起来问题不大/还是有风险”的 summary，丢掉证据强度。
- 上游正式确认和缓解传闻同时存在时，只做聚合的系统很容易错误地认为 blocker 已被解除。
- 即使系统答对了当前 blocker，也常常解释不出它为什么会传播成下游影响。

## 最容易误判的消息

- “我听别人说窗口差不多定了”这类 hearsay 缓解传闻。
- 目标负责人自己的模糊判断。
- 最终 summary 中依赖 verified anchor 才能成立的结论句。

## 对后续阶段的帮助

### capability-brief

- 强调必须同时存在 evidence strength gradient 和 impact chain

### case-world

- 强调场景要天然支持正式确认、传闻、模糊判断并存
- 强调场景还要天然支持 upstream -> target -> downstream 的依赖链，但正式 contract 里仍只有一个目标任务

### story-plan

- 强调 `task_actor_layout + state_changes + message_beats + planned_probe_queries` 都是重点
- 强调 `dependency_context_blocks` 必须区分 verified anchor、hearsay、ambiguous 和 downstream impact

## 有效 probe

- 要求系统说明依据来自谁、哪条消息
- 追问哪些说法只是 hearsay 或 ambiguous
- 要求系统解释该依据为什么会阻塞目标任务，以及它如何产生下游影响

## 无效 probe

- 只问“现在 blocker 是什么”，不要求证据归因
- 只问“谁说过什么”，不要求解释依赖传播
- 只问目标任务当前状态，不要求解释上下游影响

## Observed Validation / Eval 重点

- verified / hearsay / ambiguous 是否都真实落地
- 上游风险和下游影响是否都在 observed messages 中被明确说出
- query benchmark 是否真的同时考 evidence attribution 和 dependency reasoning
- `dependency_context_blocks` 是否都能在消息里映射到对应证据和影响链角色
