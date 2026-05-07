# Lark CLI 第一版手动验证清单

## 1. 文档目标

这份文档用于手动跑通第一版飞书企业协作数据集构造流程。

目标不是一次性自动化，而是先验证：

1. 3 个用户是否可以稳定协作
2. 群、thread、文档、任务、日历这些对象是否能创建
3. 文档、任务、日历中的关键事实能否被同步到对话里
4. 对话消息能否被稳定回读
5. 回读字段是否足够支持后续：
   - Feishu channel ingress dataset
   - raw mirror dataset
   - canonical office dataset
   - oracle truth / gold query

建议第一版只覆盖：

- Contact
- IM
- Docs
- Task
- Calendar

但要注意第一版真正进入 OpenClaw 主链的是：

- 主群消息
- thread 回复
- 侧边群消息

Docs / Task / Calendar 在第一版里仍然创建，但它们的角色是：

- 产生真实业务事实
- 再通过消息同步进入对话

审批先不作为阻塞项。

---

## 2. 第一版场景范围

第一版只做一个最小可运行项目场景：

- 1 个项目主群
- 1 个侧边协作群
- 1 条主线程
- 1 篇项目决策文档
- 1 篇运维/上线 checklist 文档
- 1 个 tasklist
- 2 到 3 个任务
- 1 个会议或日历事件

建议先用 3 个真实用户分别作为场景角色：

- `cjy`
- `wcy`
- `xzy`

第一版默认做法：

- 所有命令都由当前已经登录的 `lark-cli` 用户身份执行
- 不要求 3 个账号分别登录终端发送
- 但群成员、任务负责人、参会人尽量使用这 3 个真实用户
- 消息文本中显式保留角色标签，例如 `【cjy】`、`【wcy】`、`【xzy】`

也就是说，第一版优先验证：

- 飞书对象是否能被创建
- 对象字段是否能被稳定回读
- 文档/任务/日历中的事实是否能同步进对话
- OpenClaw 是否可以把这些同步消息当成真实 channel 输入

而不是先验证“3 个账号分别独立操作终端”或“OpenClaw 直接吃对象型数据”。

---

## 3. 是否需要 10 轮消息

需要，而且我认为第一版手动验证里：

- 大约 8 到 12 轮消息最合适

太少会导致：

- 没有状态变化
- 没有 blocker 演进
- 没有多条 evidence

太多会导致第一轮手工验证成本太高。

所以第一版建议固定为：

- 主群 6 到 7 条
- thread 2 到 3 条
- 侧边群 1 到 2 条
- 其中至少 3 条承担“把对象事实同步回对话”的职责

总计约 10 轮。

---

## 4. 前置准备

在执行任何写入操作前，先确认：

1. `lark-cli` 已安装
2. 已完成 `config init`
3. 已完成 `auth login`
4. 当前账号具备：
   - IM
   - Docs
   - Task
   - Calendar
   的相关 scope

建议先执行：

```bash
lark-cli auth status
```

你当前已经确认的登录用户信息可以作为第一版基准：

```text
CURRENT_LOGIN_USER = 许祝愿
CURRENT_LOGIN_OPEN_ID = ou_7488779f2769b648358fca04a3e1919f
```

如果还没有完成配置，先做：

```bash
lark-cli config init --new
```

以及按需要补授权：

```bash
lark-cli auth login --scope "im:chat:create_by_user"
lark-cli auth login --scope "im:message"
lark-cli auth login --scope "im:message.send_as_user"
lark-cli auth login --scope "docx:document"
lark-cli auth login --scope "task:task:write"
lark-cli auth login --scope "task:tasklist:write"
lark-cli auth login --scope "calendar:calendar.event:create"
lark-cli auth login --scope "calendar:calendar.event:update"
```

---

## 5. 第一步：确认 3 个用户信息

先把 3 个用户的 `open_id` 确认下来。

## 5.1 搜索用户

```bash
lark-cli contact +search-user --query "许祝愿"
lark-cli contact +search-user --query "陈嘉怡"
lark-cli contact +search-user --query "王程羽"
```

如果你想查看当前登录用户：

```bash
lark-cli contact +get-user
```

如果已经知道 `open_id`，可以获取详情：

```bash
lark-cli contact +get-user --user-id ou_xxx
```

建议先手工整理一份最小员工映射表：

```text
cjy -> ou_cjy_xxx
wcy -> ou_wcy_xxx
xzy -> ou_xzy_xxx
```

---

## 6. 第二步：创建两个群

## 6.1 创建项目主群

```bash
lark-cli im +chat-create \
  --name "OpenClaw-P0-Launch-Main" \
  --users "ou_cjy_xxx,ou_wcy_xxx,ou_xzy_xxx" \
  --as user
```

建议记录返回的：

- `chat_id`
- `name`

## 6.2 创建侧边协作群

```bash
lark-cli im +chat-create \
  --name "OpenClaw-P0-Launch-Side" \
  --users "ou_cjy_xxx,ou_wcy_xxx,ou_xzy_xxx" \
  --as user
```

建议记录：

- `MAIN_CHAT_ID=oc_xxx`
- `SIDE_CHAT_ID=oc_xxx`

---

## 7. 第三步：发送约 10 轮消息

第一版建议消息脚本如下。

注意这里的原则已经变成：

- 不只是“发几条项目消息”
- 而是要让文档、任务、日历中的关键事实回流进对话

这样这些事实才会真正进入 OpenClaw 的 Feishu channel 主链。

## 7.1 主群消息 1

```bash
lark-cli im +messages-send \
  --chat-id "$MAIN_CHAT_ID" \
  --text "【cjy】创建任务 FEISHU-231：Q2 发布准备启动，目标发布时间暂定 5 月 5 日，请研发和运维一起评估。" \
  --as user
```

## 7.2 主群消息 2

```bash
lark-cli im +messages-send \
  --chat-id "$MAIN_CHAT_ID" \
  --text "【wcy】研发评估完成，FEISHU-231 代码改动不大，但需要先确认灰度方案。" \
  --as user
```

## 7.3 主群消息 3

```bash
lark-cli im +messages-send \
  --chat-id "$MAIN_CHAT_ID" \
  --text "【xzy】运维侧先提醒一下，若 5 月 5 日上线，需要先完成数据迁移和回滚预案。" \
  --as user
```

## 7.4 主群消息 4

```bash
lark-cli im +messages-send \
  --chat-id "$MAIN_CHAT_ID" \
  --text "【cjy】我刚更新了项目决策文档：当前版本仍先按 5 月 5 日推进，但这个日期还依赖迁移窗口。" \
  --as user
```

## 7.5 主群消息 5

```bash
lark-cli im +messages-send \
  --chat-id "$MAIN_CHAT_ID" \
  --text "【wcy】同步任务进展：如果灰度和数据迁移都准备不完，发布时间可能要顺延到 5 月 8 日。" \
  --as user
```

## 7.6 主群消息 6

```bash
lark-cli im +messages-send \
  --chat-id "$MAIN_CHAT_ID" \
  --text "【xzy】同步运维 checklist 状态：我建议先不要在主群里把 5 月 5 日说死，运维 checklist 还没齐。" \
  --as user
```

## 7.7 在主群里挑 1 条消息开 thread

先读主群消息，找到你要回复的那条消息 `message_id`：

```bash
lark-cli im +chat-messages-list --chat-id "$MAIN_CHAT_ID" --sort asc --page-size 20 --format json
```

假设你选中第 1 条消息的 `message_id=om_xxx`，然后在线程里回复：

```bash
lark-cli im +messages-reply \
  --message-id "om_xxx" \
  --text "【Thread/wcy】研发侧补充：任务 FEISHU-231 的真正 blocker 不是代码，而是数据迁移窗口未确认。" \
  --reply-in-thread \
  --as user
```

```bash
lark-cli im +messages-reply \
  --message-id "om_xxx" \
  --text "【Thread/xzy】是的，而且回滚脚本还没有最终验收，所以会议前文档里写的 5 月 5 日只是乐观日期。" \
  --reply-in-thread \
  --as user
```

```bash
lark-cli im +messages-reply \
  --message-id "om_xxx" \
  --text "【Thread/cjy】收到，那我会在文档里保留 5 月 5 日目标，但会在群里同步标注存在 blocker。" \
  --reply-in-thread \
  --as user
```

## 7.8 侧边协作群 2 条消息

```bash
lark-cli im +messages-send \
  --chat-id "$SIDE_CHAT_ID" \
  --text "【Side/wcy】研发内部判断：如果迁移今天不能锁窗，正式发布时间大概率改到 5 月 8 日，主群里先不要把这个说死。" \
  --as user
```

```bash
lark-cli im +messages-send \
  --chat-id "$SIDE_CHAT_ID" \
  --text "【Side/xzy】运维内部结论：在 checklist 完整前，对外口径不要说已经 ready，后面要同步到主群。" \
  --as user
```

这样总数大约就是 10 轮左右，已经足够支撑第一版：

- deadline 冲突
- blocker 演进
- 主群与 side 群口径不一致
- thread 里出现 buried evidence

---

## 8. 第四步：创建两篇文档

文档在第一版里的角色不是“直接喂给 OpenClaw”，而是：

- 作为真实协作对象存在
- 再由群消息把其结论同步进对话

这里建议创建：

- 1 篇项目决策文档
- 1 篇运维/上线 checklist 文档

## 8.1 创建项目决策文档

```bash
lark-cli docs +create --api-version v2 --content '
<title>FEISHU-231 项目决策记录</title>
<h1>项目目标</h1>
<p>目标：推动 FEISHU-231 在 5 月上旬上线。</p>
<h1>当前口径</h1>
<p>主目标日期暂定为 5 月 5 日。</p>
<h1>已知风险</h1>
<ul>
  <li>数据迁移窗口未最终确认</li>
  <li>回滚预案尚未验收</li>
</ul>
'
```

建议记录：

- `DECISION_DOC_TOKEN`
- `DECISION_DOC_URL`

## 8.2 创建运维 / 上线 checklist 文档

```bash
lark-cli docs +create --api-version v2 --content '
<title>FEISHU-231 上线 Checklist</title>
<h1>上线前检查</h1>
<ul>
  <li>确认灰度方案</li>
  <li>确认数据迁移窗口</li>
  <li>确认回滚脚本</li>
</ul>
<h1>当前状态</h1>
<p>当前仍有 blocker，暂未达到可直接发布状态。</p>
'
```

建议记录：

- `CHECKLIST_DOC_TOKEN`
- `CHECKLIST_DOC_URL`

## 8.3 更新项目决策文档，制造“旧目标 + 新说明”

这一步很重要，因为它能制造：

- 文档里保留旧目标日期
- 同时追加新的 blocker 说明

```bash
lark-cli docs +update \
  --api-version v2 \
  --doc "$DECISION_DOC_TOKEN" \
  --command append \
  --content '
<h1>补充说明</h1>
<p>虽然项目目标日期仍写为 5 月 5 日，但研发和运维均指出，若迁移窗口无法锁定，实际发布时间可能顺延至 5 月 8 日。</p>
'
```

---

## 9. 第五步：创建 tasklist 和任务

任务在第一版里的角色也是：

- 产生 owner / blocker / due 等真实对象状态
- 再通过主群或 thread 把这些状态同步给 OpenClaw

建议第一版创建：

- 1 个 tasklist
- 3 个任务

## 9.1 创建 tasklist

```bash
lark-cli task +tasklist-create \
  --name "FEISHU-231 Launch Checklist" \
  --member "ou_cjy_xxx,ou_wcy_xxx,ou_xzy_xxx"
```

建议记录：

- `TASKLIST_GUID`

如果你希望一次性批量加任务，也可以：

```bash
lark-cli task +tasklist-create \
  --name "FEISHU-231 Launch Checklist" \
  --member "ou_cjy_xxx,ou_wcy_xxx,ou_xzy_xxx" \
  --data '[{"summary":"确认灰度方案","assignee":"ou_wcy_xxx"},{"summary":"锁定迁移窗口","assignee":"ou_xzy_xxx"}]'
```

但第一轮我更建议分开建，便于观察返回值。

## 9.2 创建任务 1

```bash
lark-cli task +create \
  --summary "确认灰度方案" \
  --description "研发负责确认 FEISHU-231 的灰度发布策略。" \
  --assignee "ou_wcy_xxx" \
  --due "2026-05-02" \
  --tasklist-id "$TASKLIST_GUID"
```

## 9.3 创建任务 2

```bash
lark-cli task +create \
  --summary "锁定数据迁移窗口" \
  --description "运维负责确认迁移时间窗，并与上线计划对齐。" \
  --assignee "ou_xzy_xxx" \
  --due "2026-05-03" \
  --tasklist-id "$TASKLIST_GUID"
```

## 9.4 创建任务 3

```bash
lark-cli task +create \
  --summary "同步最新发布日期口径" \
  --description "产品负责同步 5 月 5 日与 5 月 8 日两种口径的风险说明。" \
  --assignee "ou_cjy_xxx" \
  --due "2026-05-03" \
  --tasklist-id "$TASKLIST_GUID"
```

建议记录每个任务返回的：

- `TASK_GUID_1`
- `TASK_GUID_2`
- `TASK_GUID_3`

## 9.5 给任务补 comment

```bash
lark-cli task +comment \
  --task-id "$TASK_GUID_2" \
  --content "当前 blocker 是迁移窗口尚未锁定，若今天无法确认，发布时间需要顺延。"
```

```bash
lark-cli task +comment \
  --task-id "$TASK_GUID_3" \
  --content "对外仍保留 5 月 5 日目标，但需明确说明存在运维 blocker。"
```

## 9.6 更新一个任务，制造状态变化

```bash
lark-cli task +update \
  --task-id "$TASK_GUID_2" \
  --summary "锁定数据迁移窗口（P0 blocker）"
```

---

## 10. 第六步：创建一个会议 / 日历事件

日历事件在第一版里主要用于：

- 生成一次真实会议对象
- 再通过消息把会议结论同步回主群

创建前，建议先阅读相关 workflow 说明，但第一版可以直接使用明确时间的最简单路径。

## 10.1 创建会议

```bash
lark-cli calendar +create \
  --summary "FEISHU-231 发布对齐会" \
  --description "确认 5 月 5 日目标是否继续保留，以及 5 月 8 日顺延方案。" \
  --start "2026-05-02T14:00+08:00" \
  --end "2026-05-02T15:00+08:00" \
  --attendee-ids ou_cjy_xxx,ou_wcy_xxx,ou_xzy_xxx
```

建议记录：

- `EVENT_ID`
- `CALENDAR_ID`

---

## 11. 第七步：回读所有对象

这一步最关键，因为它决定后面：

- Feishu channel ingress dataset 的字段长什么样
- raw dataset 的字段长什么样

## 11.1 回读主群消息

```bash
lark-cli im +chat-messages-list \
  --chat-id "$MAIN_CHAT_ID" \
  --sort asc \
  --page-size 50 \
  --format json
```

## 11.2 回读 thread

先从主群消息里拿到 `thread_id`，再：

```bash
lark-cli im +threads-messages-list \
  --thread "omt_xxx" \
  --sort asc \
  --page-size 50 \
  --format json
```

## 11.3 回读侧边群消息

```bash
lark-cli im +chat-messages-list \
  --chat-id "$SIDE_CHAT_ID" \
  --sort asc \
  --page-size 50 \
  --format json
```

## 11.4 回读两篇文档

```bash
lark-cli docs +fetch \
  --api-version v2 \
  --doc "$DECISION_DOC_TOKEN" \
  --detail with-ids
```

```bash
lark-cli docs +fetch \
  --api-version v2 \
  --doc "$CHECKLIST_DOC_TOKEN" \
  --detail with-ids
```

## 11.5 回读 tasklist 和任务

由于 task 原生读命令依赖 `--params`，建议先看 schema：

```bash
lark-cli schema task.tasklists.get
lark-cli schema task.tasklists.tasks
lark-cli schema task.tasks.get
```

然后再调用：

```bash
lark-cli task tasklists get --params '{"tasklist_guid":"'"$TASKLIST_GUID"'"}' --format json
```

```bash
lark-cli task tasklists tasks --params '{"tasklist_guid":"'"$TASKLIST_GUID"'"}' --format json
```

```bash
lark-cli task tasks get --params '{"guid":"'"$TASK_GUID_1"'"}' --format json
```

```bash
lark-cli task tasks get --params '{"guid":"'"$TASK_GUID_2"'"}' --format json
```

```bash
lark-cli task tasks get --params '{"guid":"'"$TASK_GUID_3"'"}' --format json
```

如果你的本地 CLI schema 返回字段名不是 `guid` / `tasklist_guid`，以 `schema` 输出为准。

## 11.6 回读 calendar event

先看 schema：

```bash
lark-cli schema calendar.events.get
lark-cli calendar calendars primary --format json
```

然后调用：

```bash
lark-cli calendar events get \
  --params '{"calendar_id":"'"$CALENDAR_ID"'","event_id":"'"$EVENT_ID"'"}' \
  --format json
```

如果字段名和本地 schema 不同，以 `schema calendar.events.get` 为准。

---

## 12. 第一版人工记录建议

在手动执行时，建议同步维护一份记录表：

```text
USERS
- ou_cjy_xxx
- ou_wcy_xxx
- ou_xzy_xxx

CHATS
- MAIN_CHAT_ID=...
- SIDE_CHAT_ID=...

MESSAGES
- ROOT_MESSAGE_ID=...
- THREAD_ID=...

DOCS
- DECISION_DOC_TOKEN=...
- CHECKLIST_DOC_TOKEN=...

TASKS
- TASKLIST_GUID=...
- TASK_GUID_1=...
- TASK_GUID_2=...
- TASK_GUID_3=...

CALENDAR
- CALENDAR_ID=...
- EVENT_ID=...

SYNC MESSAGES
- DOC_SYNC_MESSAGE_ID=...
- TASK_SYNC_MESSAGE_ID=...
- MEETING_SYNC_MESSAGE_ID=...
```

这份记录后面可以直接喂给：

- channel ingress builder
- raw collector
- canonicalizer
- oracle builder

---

## 13. 第一版完成标准

如果以下条件都满足，就说明第一版手动 PoC 已经跑通：

1. 能找到 3 个用户的 `open_id`
2. 成功创建 2 个群
3. 成功发送约 10 轮消息
4. 成功创建并回读 1 条 thread
5. 成功创建并回读 2 篇文档
6. 成功创建并回读 1 个 tasklist 和 3 个任务
7. 成功创建并回读 1 个 calendar event
8. 所有对象都有稳定 ID 可追踪
9. 至少有 3 条消息承担“对象事实同步进对话”的职责

到这一步，就已经足够支撑你开始定义：

- `feishu_channel_events.jsonl`
- `feishu_channel_contexts.jsonl`
- `raw/feishu_raw_events.jsonl`
- `canonical/office_events.jsonl`
- `oracle/truth_timeline.json`

---

## 14. 下一步

手动验证成功后，再做自动化：

1. 把这里的命令序列转成 `execution_plan`
2. 用 planner agent 生成：
   - `world_spec`
   - `truth_timeline`
   - `surface_evidence_plan`
   - `conversation_sync_plan`
3. 用 materializer agent 调 `lark-cli`
4. 先生成 channel ingress dataset
5. 再统一回收 raw objects
6. 再进入 graph index / eval

第一版先手动是完全合理的，而且是最稳的路径。
