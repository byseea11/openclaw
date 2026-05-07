# case-world

## 职责

这个 skill 负责为 `case-world` 阶段提供企业业务场景约束，让当前 family 在真实协作里自然发生，并物化为 `input/case_world.json`。

## 硬规则

- 必须生成：
  - `organization`
  - `team`
  - `business_goal`
  - `scenario_summary`
  - `family_fit_explanation`
- 场景必须天然满足 capability brief 的 `required_case_structure`。
- 必须解释为什么这个 family 会在该场景里自然发生。
- `scenario_summary` 只负责业务化，不负责写消息节奏。
- 必须把“组织”理解成部门拓扑和协作结构，而不是显式多公司数量。
- 必须与当前 difficulty 的 `department_count` 和 `recommended_session_count` 保持一致，默认是多部门协作，而不是单小组单线对话。
- 必须显式消费 runtime 注入的数字目标，把部门规模和侧向 source 数量体现在 `organization`、`team`、`scenario_summary` 与 `required_case_structure` 的业务化描述里。
- 默认 `hard` 必须按企业版口径生成：多部门、多线程、多来源，不得退化成几个核心角色的小组讨论。
- session 类型语义、外部上下文类型和侧向 source 的含义都由 skills 定义，不由 yml 注入。
- 必须吸收旧 builder 的 case world 语义：
  - 为什么信息会分散在主群、线程和侧向补充对话里。
  - 为什么协作方会使用模糊、保守或未完成承诺的措辞。
  - 为什么旧状态会被后续证据 supersede。
  - 为什么干扰上下文会自然出现，而不是人造噪声。
  - 为什么客户同步、供应商依赖、风险评审或高层同步会形成侧向 source。

## 禁止

- 不要开始写 message beats。
- 不要开始写最终 probe wording。
- 不要把 message beat、完整 turn 或 command plan 内容揉到 case world。
- 不要重新定义 family 或 capability brief。
- 不要把 distractor 写成正式并列任务清单。
- 不要引入 `company_count` 之类的显式多公司数量字段。

## JSON 示例

下面是最终 `case_context.json` 中企业场景部分的片段示例：

```json
{
  "organization": "Globex Corporation",
  "team": "Platform Engineering",
  "business_goal": "确保项目计划和调度数据始终反映最新决策，避免因旧口径残留导致交付延迟。",
  "scenario_summary": "在复杂多任务环境中，项目经理先后通过飞书消息更改了某个关键任务的负责人和交付截止日期，要求系统准确识别当前有效信息。",
  "family_fit_explanation": "该场景需要处理多个按时间顺序发生的状态更新，并有明确的 supersede 关系，属于 contradiction_update 范畴。"
}
```

## 槽位联动说明

- 上面的 JSON 示例只展示字段形状，不代表当前 difficulty 的最终人数、部门数或 session 规模。
- 实际生成时，必须以 runtime 注入的 `Resolved Slot Contract` 为准，把 actors、departments 和 sessions 扩展到对应档位。

## V3 Phase 1 对接位置

在细分 Phase 1 链路里，`case-world` 读取 `case_context`、`task-actor-layout` 和当前 family context skill，把结构化 family 机制翻译成自然企业协作世界。

它必须解释：

- 为什么这些人会在真实企业协作中讨论目标任务。
- 为什么信息会分散到主群、线程和侧向 source。
- 为什么某些表达会模糊、保守或未完成承诺。
- 为什么旧状态会被后续消息修正。
- 为什么干扰上下文自然出现，而不是人为噪声。

`case-world` 产出的 source session 和业务背景会被 `story-beats`、`conversation-plan` 和 `command-plan` 继续引用，后续阶段不能重新发明 session 语义。
