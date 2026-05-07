# pre-annotation-validate

## 职责

这个 skill 负责在 annotation gold 之前检查 Phase 1 数据是否真的可用于评测。它基于 observed data，而不是只看 planned turns。

## 读取

- `input/coverage_spec.json`
- `input/conversation_plan.json`
- `input/command_plan.jsonl`
- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`
- 当前 family context skill

## 输出

- `checks/pre_annotation_validation_report.json`

## 如何检查

- 检查 family-required evidence 是否出现在真实消息里。
- 检查 state transition、supersession、dependency impact 或 interference disambiguation 是否落地。
- 检查 planned beat 是否能对应到 observed message。
- 检查 probe 所需证据是否足够。
- 检查 fetch/execute 是否留下可追踪的 message id、thread id 和 session id。

## Family 重点

- `anti_interference`：检查干扰上下文真的进入消息，且目标 current state 与干扰内容可区分。
- `contradiction_update`：检查 initial、historical、current 和 supersession clues 都落地。
- `evidence_dependency_reasoning`：检查 verified、ambiguous、hearsay、downstream impact 的证据梯度都落地。

## 下游作用

- 只有通过本阶段，annotation gold 才有可靠 observed data 可标。
- 本阶段发现的问题应显式暴露，不允许静默进入 Phase 2。

## 禁止

- 不要只检查 JSON schema。
- 不要只看 planned message。
- 不要把未发送成功的 planned turn 当作 observed evidence。
