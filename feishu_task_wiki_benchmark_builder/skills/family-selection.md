# family-selection

## 职责

这个 skill 负责为 `case-context` 阶段提供 formal family 选择约束。它不单独落文件，而是约束最终 `case_context.json` 里的 `family_id` 和对应 benchmark 口径。

## 硬规则

- 只能在 `anti_interference`、`contradiction_update`、`evidence_dependency_reasoning` 三类中选择。
- 单 case 默认只选 `1` 个 family。
- 如果用户显式指定 `family_id`，必须服从。
- 如果用户没有显式指定，按 deterministic seed policy 选择。
- `效能指标验证` 是横向评测维度，不是 formal family。
- family 选择只决定 failure mechanism，不决定去生成多个正式 task。
- difficulty/profile 只负责复杂度控制，不改变 formal family 集合。
- 一旦 family 确定，后续阶段必须满足该 family 在 `builder_settings.yml` 中定义的最低复杂度条件。
- family 一旦确定，后续阶段必须同时服从：
  - runtime 注入的 numeric minima
  - 当前 family skill 中定义的 role/context/dependency 语义
- 不要开始设计企业场景、角色或消息节奏。

## 禁止

- 不要发明新的 family。
- 不要把 family 选择写成独立 artifact。
- 不要提前写 capability brief 或 case world 的细节。

## JSON 示例

下面是最终 `case_context.json` 中与 family 选择相关的片段示例：

```json
{
  "family_id": "contradiction_update",
  "benchmark_requirement_name": "矛盾更新测试",
  "benchmark_requirement_summary": "当先后输入冲突口径时，系统能够理解时间顺序，让新指令覆盖旧指令。",
  "report_display_name": "矛盾更新测试"
}
```

## V3 Phase 1 对接位置

在当前三类 family 版本里，`family-selection` 是 Phase 1 的第一层 failure-oriented 控制面。它接在 `spec-generation` 之后，决定后续引用哪一个 family context skill。

- `anti_interference` 后续必须引用 `anti-interference-context.md`。
- `contradiction_update` 后续必须引用 `contradiction-update-context.md`。
- `evidence_dependency_reasoning` 后续必须引用 `evidence-dependency-context.md`。

单 case 默认只选一个 family。批量数据集可以通过多 case 覆盖三类 family，但不要在一个 case 内混合多个正式 family。
