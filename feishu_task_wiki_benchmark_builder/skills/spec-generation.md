# spec-generation

## 职责

这个 skill 负责生成 Phase 1 的最小 case control。它只决定 benchmark 控制字段，不写企业故事、不写角色、不写消息。

## 读取

- 显式用户输入的 `family_id`
- `difficulty`
- `seed`
- `comparison_target`
- `family-selection.md`

## 输出

- `case_id`
- `task_id`
- `family_id`
- `difficulty`
- `seed`
- `comparison_target`

这些字段进入后续 `case_context.json` 或等价 case control artifact。

## 如何生成

- 如果用户显式指定 `family_id`，必须服从。
- 如果用户未指定，按 deterministic seed policy 从三类 family 中选择。
- `case_id` 和 `task_id` 是 system-owned control fields，不由故事 prompt 决定。
- `difficulty` 只控制规模和复杂度，不改变三类 family 集合。

## 下游作用

- `family_id` 决定后续进入哪个 family context skill。
- `difficulty` 决定 actor、department、session、context block 和 evidence 覆盖密度。
- `comparison_target` 决定后续 value eval 的对照系统。

## 禁止

- 不要写 `scenario_summary`。
- 不要写 actor roster。
- 不要写 message beats。
- 不要把多个 family 混进单个 case，除非明确在批量生成层做覆盖。
