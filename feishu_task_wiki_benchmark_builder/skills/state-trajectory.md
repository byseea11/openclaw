# state-trajectory

## 职责

这个 skill 负责定义 Phase 1 的状态演进。它把 family-specific 的失败机制转成 current state、historical state、supersession、dependency impact 或干扰边界。

## 读取

- `case_context.json` 或等价 case control
- `input/task_actor_layout.json`
- `input/case_world.json`
- `input/characters.json`
- 当前 family context skill

## 输出

- `input/state_trajectory.json`

## 如何生成

- `anti_interference`：定义目标任务 current state，同时定义哪些 shared actor / parallel context 不能污染目标答案。
- `contradiction_update`：定义至少三段状态，区分 initial、historical、current，并记录 supersession clues。
- `evidence_dependency_reasoning`：定义 verified anchor、ambiguous/hearsay 信息和 downstream impact 如何传播到目标任务。

## 下游作用

- `coverage-spec` 用它生成必须落地的 state/evidence 检查项。
- `story-beats` 用它安排 state update、supersession、dependency impact 或 interference disambiguation beats。
- `conversation-plan` 用它约束 turn 中必须出现的 current-state 口径。
- Phase 2/3 eval 用它判断系统是否答对 current state，而不是只复述历史消息。

## 禁止

- 不要只给最终值，不给变化过程。
- 不要把 stale / historical / current 混成同一层。
- 不要把干扰上下文写成目标任务的 current state。
