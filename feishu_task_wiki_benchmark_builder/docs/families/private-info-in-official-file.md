# private_info_in_official_file

## 目标

构造个人私有信息混入正式文件、纪要或 checklist 的企业协作场景，测试系统能否区分：

- 正式文件中的任务结论。
- 个人偏好、个人时间限制、私聊承诺。
- 聊天对正式文件的引用、误读和纠偏。

## OpenClaw 原生容易失败的点

个人中心或摘要式记忆可能会把“某人的个人安排”压成任务事实，或者把“私聊承诺”当成正式 owner / blocker 变更。

## Task Wiki 应该做对什么

Task Wiki 只把与目标 task state/evidence 有关的信息投影到任务维度。个人私有信息可以作为 context 或 evidence，但不能污染 current task answer。

## 对后续阶段的帮助

### capability-brief

- 强调必须同时存在正式文件权威性、个人私有背景和 task relevance boundary。
- 强调个人私有信息不能成为目标任务 current state。

### story-beats / conversation-plan

- 强调 message beats 必须覆盖正式文件引用、私有信息暴露、误读、纠偏和最终结论。
- 强调 planned probe 必须逼系统区分正式任务事实与个人背景。

### conversation-plan

- 强调完整 transcript 要包含多人引用、误读和纠正文档内容，而不是单条文件摘要。

## 有效 probe

- 询问目标任务当前正式结论是什么，并要求排除个人私有信息。
- 追问某条个人备注是否能改变任务 current state，并要求说明证据边界。

## 无效 probe

- 只问文件标题或谁发了消息。
- 只问个人安排本身，不要求判断它是否能成为任务事实。
