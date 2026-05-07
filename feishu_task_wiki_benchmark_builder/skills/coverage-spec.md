# coverage-spec

## 职责

这个 skill 负责把 family required structure 转成可审计的落地检查要求。它不写故事，也不写完整消息，只定义哪些 evidence、beat、state 和 probe 必须出现在 observed data 中。

## 读取

- `case_context.json` 或等价 case control
- `input/task_actor_layout.json`
- `input/state_trajectory.json`
- 当前 family context skill

## 输出

- `input/coverage_spec.json`

## 如何生成

- 从 `capability-brief.md` 读取能力目标、probe 策略和 required case structure。
- 从 family context skill 读取必须落地的 role/context/dependency/revision 槽位。
- 从 `state_trajectory.json` 读取必须能被验证的 state field 和 transition。

## 下游作用

- `story-beats` 根据 coverage spec 安排 beat skeleton。
- `pre-annotation-validate` 根据 coverage spec 检查真实 observed messages 是否覆盖关键证据。
- Phase 2 annotation gold 根据 coverage spec 避免漏标关键事件。

## 禁止

- 不要生成自然语言对话。
- 不要新增 actor 或 session。
- 不要把 coverage 写成泛泛“应该复杂”，必须能对应到 evidence、state、beat 或 probe。
