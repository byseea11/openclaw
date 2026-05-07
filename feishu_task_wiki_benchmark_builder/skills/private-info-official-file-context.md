# private-info-official-file-context

## 职责

这个 skill 负责定义 `private_info_in_official_file` family 的生成规则。它测试的是：当个人私有信息、正式文件结论和任务状态混在同一批企业协作消息里时，系统能否只把任务相关的正式结论投影成 Task Wiki current state。

## 失败机制

原生个人/摘要式记忆容易把三类东西混写：

- 某个人的私有偏好、临时限制、私聊承诺。
- 正式文件、纪要、上线 checklist 中的任务结论。
- 聊天里对正式文件的转述、误读和纠正。

如果系统以“人”为核心做摘要，它可能把“林晨只能周三参加评审”写成任务阻塞，或把“唐越私下答应补材料”写成正式 owner。Task Wiki 应该只把与目标任务状态有关、且有正式 evidence 的信息投影到任务维度。

## 必须出现的结构

- `official_file_reference`：至少一个正式文件、纪要、checklist、风险登记表或上线评审记录。
- `personal_private_context`：至少若干条个人私有信息，例如个人时间限制、偏好、私聊背景、个人承诺。
- `task_relevance_boundary`：明确说明哪些内容只是 evidence/context，不能成为任务 current state。
- `misread_or_overgeneralization`：至少一次有人把个人信息误读成任务事实，后续必须被纠正。
- `official_conclusion`：至少一条可作为任务状态依据的正式结论。

## Stage 接入

- `capability-brief`：把 family 转成 private context、official authority、task relevance boundary 三类约束。
- `task-actor-layout`：必须包含正式文件 owner、个人信息当事人、误读者、纠偏者和目标任务 owner。
- `case-world`：解释为什么个人信息会进入正式文件，例如复盘纪要、上线 checklist 或风险登记表把“个人备注”附在任务项旁边。
- `state-trajectory`：只把正式任务结论定义成 current state；个人信息只能作为 context 或 evidence，不得变成 current state。
- `story-beats`：定义正式文件引用、私有信息暴露、误读、纠偏、最终结论和 probe setup。
- `conversation-plan`：生成完整企业 transcript，必须包含多人对正式文件的引用、误读、追问、纠偏和总结。

## Conversation 约束

- 正式文件引用必须在多条消息中自然回流，不能只在结构化字段里声明。
- 私有信息必须足够像真实企业信息，但不能是敏感真实数据；使用虚构个人偏好、时间限制和承诺。
- 至少一部分消息要让 OpenClaw 容易把个人信息和任务状态混起来。
- 至少一部分消息要让 Task Wiki 能通过 evidence 和 task relevance boundary 纠正这种混淆。
- 每条消息都要像真实协作，不允许模板刷屏。

## Probe 方向

- 问目标任务当前结论是什么，要求不要把个人私有信息混入答案。
- 问正式文件里哪些内容能作为任务事实，哪些只是个人背景。
- 问某个个人限制是否会改变任务 current state，期望答案说明“不会，除非正式文件或 owner 明确把它提升为任务状态”。

## 好系统行为

- 能识别正式文件结论的权威性。
- 能把个人私有信息限制在 evidence/context 层。
- 能指出误读消息的问题，并回到正式文件与目标任务证据。
- 回答目标任务时不输出无关个人背景。
