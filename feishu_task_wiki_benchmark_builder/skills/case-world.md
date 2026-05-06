# case-world

## 职责

这个 skill 负责为 `case-context` 阶段提供企业业务场景约束，让当前 family 在真实协作里自然发生。它不单独落文件，而是约束最终 `case_context.json` 的企业场景部分。

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
- 必须与当前 difficulty 的 `department_count` 和 `session_blueprint` 保持一致，默认是多部门协作，而不是单小组单线对话。
- 必须吸收旧 builder 的 case world 语义：
  - 为什么信息会分散在主群、线程和侧向补充对话里。
  - 为什么协作方会使用模糊、保守或未完成承诺的措辞。
  - 为什么旧状态会被后续证据 supersede。
  - 为什么干扰上下文会自然出现，而不是人造噪声。
  - 为什么客户同步、供应商依赖、风险评审或高层同步会形成侧向 source。

## 禁止

- 不要开始写 message beats。
- 不要开始写最终 probe wording。
- 不要把 story-plan 内容揉到 case-context。
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
