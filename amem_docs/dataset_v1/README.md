# Dataset V1

## 1. 目标

这个目录现在只保留一个目标：

- 定义并逐步构造“这个项目最完整的单个飞书数据集”长什么样

这里的“完整”不是指 OpenClaw 已经原生直连所有飞书对象，而是指：

- 所有关键业务域都至少被模拟一遍
- 每个业务域都至少有一个真实对象
- 每个业务域的关键信息都尽量被同步进主对话流

这样我们就能同时得到：

1. 原始飞书对象抓取
2. 已进入 OpenClaw 主对话流的消息数据
3. 后续做 channel ingress、graph index、eval 的统一输入范围

---

## 2. 当前保留的文件

本目录现在只保留：

- 这一份说明文档：`amem_docs/dataset_v1/README.md`
- 所有 `raw_*` 抓取文件

其中：

- `raw_*`
  - 是当前真实 `lark-cli` 抓回来的原始数据
  - 暂时不删，作为事实底稿保留

另外补一条非常重要的区分：

- `raw_feishu_fetches_2026-04-26.jsonl`
- `raw_feishu_fetches_2026-04-26-sync.jsonl`

这两份才是最接近“直接从 `lark-cli` 原样抓回来的记录”。

而下面这些文件已经是为了对齐实验额外整理过的中间文件：

- `raw_dataset_v0.jsonl`
  - 从多份 raw 抓取里抽取并重组出来的跨域总表
- `raw_channel_im_v0.jsonl`
  - 从 raw 抓取里抽出来的 `IM / thread` 子集
- `channel_dialogue_l1.jsonl`
  - 再往前一步整理后的主对话流版本

所以如果你问：

> 哪个文件是“最直接的 lark-cli 原始输出”？

答案是：

- `raw_feishu_fetches_2026-04-26.jsonl`
- `raw_feishu_fetches_2026-04-26-sync.jsonl`

如果你问：

> 哪个文件是“为了和 OpenClaw channel ingress 对齐而整理出来的最小输入”？

答案是：

- `raw_channel_im_v0.jsonl`

---

## 3. 当前最小数据集到底是什么

如果当前目标是：

> 判断我从飞书抓回来的原始数据，能不能和 OpenClaw 的 Feishu channel 入口对齐

那么当前最小数据集不是 docs / base / sheet / wiki 本体，而是：

- `IM 主群消息`
- `thread 回复`
- `必要时的 side 群消息`

也就是一份：

- `lark_normalized_im_v0.jsonl`

这份文件的定位是：

- 输入来自最原始的 `lark-cli` 抓取：
  - `raw_feishu_fetches_2026-04-26.jsonl`
  - `raw_feishu_fetches_2026-04-26-sync.jsonl`
- 输出是一份“Lark 归一化消息集”
- 它还不是 OpenClaw ingress event
- 但它已经是当前最小、最稳定、最适合做 channel 对齐判断的数据集

为什么它是最小数据集：

- OpenClaw 当前 Feishu channel 主链直接消费的是消息事件
- 不是文档对象、Base 记录、Sheet 单元格、Task 本体、Wiki 节点本体
- 这些对象只有在“同步成消息”后，才进入这条入口

所以当前最小数据集应该回答的是：

> 一条群消息 / thread 回复，在保留 sender、message_id、thread_id、mentions、content_text 之后，是否已经足够接近 OpenClaw 的 Feishu 入口？

答案就是这份：

- `amem_docs/dataset_v1/lark_normalized_im_v0.jsonl`

---

## 4. OpenClaw ingress 抓包

如果当前目标是：

> 先验证 OpenClaw 在最外层到底收到了什么 Feishu 消息

那么现在已经有一条最小抓包方案了，而且这条方案直接复用 OpenClaw 现有 Feishu 入口，不额外发明新的解析层。

### 4.1 现在会抓哪两层

OpenClaw Feishu 插件现在可以同时落两层：

- `FeishuMessageEvent`
  - 也就是最外层的 channel event
- `FeishuMessageContext`
  - 也就是 `parseFeishuMessageEvent(...)` 之后的标准化结果

对应代码位置：

- `extensions/feishu/src/monitor.account.ts`
  - 在 `im.message.receive_v1` 事件里拿到最原始 message event
- `extensions/feishu/src/bot.ts`
  - 在 `handleFeishuMessage(...)` 里产出 normalized context
- `extensions/feishu/src/trace.ts`
  - 现在负责把这两层按 JSONL 落盘

### 4.2 如何开启

设置一个目录型环境变量：

- `OPENCLAW_FEISHU_INGRESS_CAPTURE_DIR=/your/capture/dir`

只要这个变量存在，Feishu 插件在收到真实消息后就会自动写出：

- `feishu_message_events.jsonl`
- `feishu_message_contexts.jsonl`

### 4.3 这两份文件分别看什么

- `feishu_message_events.jsonl`
  - 用来回答：
    - 飞书 webhook / websocket 最外层消息到底长什么样
    - 用户发的是普通 text、post、merge_forward，还是别的 message type
    - 链接、mentions、thread_id、root_id 在 raw event 里到底怎么出现

- `feishu_message_contexts.jsonl`
  - 用来回答：
    - OpenClaw 解析后最终给后续逻辑的文本是什么
    - mention 是否被保留
    - 原始 content 和 parsed content 有什么差异

### 4.4 这一步想验证什么

这一步不是在验证 memory 或 graph。

这一步只验证：

- 当用户在群里贴 doc/wiki/sheet/base/task 链接时
- OpenClaw 最外层到底收到了什么
- 以及 `parseFeishuMessageEvent(...)` 之后到底还剩什么

这一步结束后，才能决定：

- 现有 chat ingress 是否已经足够
- 还是需要补一条 `lark-cli` / OpenAPI 的对象解析 sidecar

## 4. 单个完整数据集的基本形态

我建议这一版最终收口成一个“单项目、多域、双层”的数据集。

### 3.1 L0：对象层

这一层保存：

- 真实飞书对象
- 但它们本身还没有直接进入 OpenClaw 主对话流

建议文件名：

- `supporting_objects_l0.jsonl`

典型内容：

- 文档对象
- 云空间文件 / 评论 / 知识库节点
- Base 表、字段、记录
- Sheet 表格
- Task / tasklist / comment
- Mail thread / draft / reply
- Meeting / minutes / recording summary
- Approval instance / task
- OKR objective / key result

### 3.2 L1：主对话流

这一层保存：

- 已经进入主群 / side 群 / thread / 转发消息 / 卡片文本的内容
- 这是第一版真正贴近 OpenClaw Feishu channel ingress 的主数据集

建议文件名：

- `channel_dialogue_l1.jsonl`

典型内容：

- 群消息
- thread 回复
- 系统消息
- 对象事实同步消息

一句话：

- 不进主对话流的，先留在 `L0`
- 进了主对话流的，进入 `L1`

---

## 5. 这几个功能在数据集里的位置

你列的这些功能，我建议全部先纳入 V1 范围，但区分它们先进哪一层。

### 4.1 直接进入 L1 的

- `即时通讯`

原因：

- 它本来就是 OpenClaw Feishu channel 的天然输入

这一层建议至少覆盖：

- 创建群
- 发消息
- 回复 thread
- 查看聊天记录
- 搜索消息

如果媒体下载有素材，也可以补：

- 图片 / 文件消息

### 4.2 先进入 L0，再尽量同步进 L1 的

- `云文档`
- `云空间`
- `多维表格`
- `电子表格`
- `任务`
- `知识库`
- `邮箱`
- `视频会议`
- `审批`
- `OKR`

也就是说，这些域在 V1 里都要做两件事：

1. 先有一个真实对象
2. 再有一条同步消息把关键事实带进对话

---

## 6. 每个域在 V1 里最少要模拟什么

这里先追求“完整覆盖”，不追求复杂流程。

### 5.1 即时通讯

至少要有：

- 1 个主群
- 1 个侧边群
- 1 条 thread
- 8 到 12 条消息
- 至少 3 条“对象事实同步消息”

### 5.2 云文档

至少要有：

- 1 篇项目决策文档
- 1 次更新
- 1 条文档结论同步消息进入主群

### 5.3 云空间

至少要有：

- 1 个上传文件或可被引用的云空间对象
- 1 条消息说明这个文件/素材的用途或结论

### 5.4 多维表格

至少要有：

- 1 张表
- 2 到 3 个字段
- 2 到 3 条记录
- 1 条把表里关键状态同步到群里的消息

适合放：

- 项目状态表
- 风险表
- blocker 表

### 5.5 电子表格

至少要有：

- 1 个 sheet
- 1 次写入或追加
- 1 条同步消息说明表里结论

适合放：

- 发布排期
- owner / due 对照表

### 5.6 任务

至少要有：

- 1 个 tasklist
- 2 到 5 个任务
- 1 次 comment 或 update
- 1 条任务状态同步消息进入主群或 thread

### 5.7 知识库

至少要有：

- 1 个 wiki space 或 node
- 1 个知识库页面
- 1 条知识库更新同步消息

### 5.8 邮箱

至少要有：

- 1 封邮件或 1 个邮件线程
- 1 次回复 / 转发 / 草稿动作
- 1 条邮件结论同步消息

适合放：

- 外部客户反馈
- 法务 / 安全回复
- 对外通知草稿

### 5.9 视频会议

至少要有：

- 1 次会议对象或会议纪要
- 1 条会后结论同步消息

这里第一版不要求把录制全文吃进 OpenClaw，只要求：

- 会议事实存在
- 会议结论被同步到对话

### 5.10 审批

至少要有：

- 1 个审批对象或审批任务
- 1 条审批状态同步消息

适合放：

- 已通过
- 被驳回
- 待审批
- 当前卡点原因

### 5.11 OKR

至少要有：

- 1 个 objective
- 1 到 2 个 key result
- 1 次更新
- 1 条 OKR 变化同步消息

---

## 7. 单个完整数据集应该包含哪些字段

## 8. 当前真正要对齐的 OpenClaw 接口

这一步不要直接看 memory，也不要直接看 graph。

当前这版数据集要先对齐的是 Feishu channel 刚进入 OpenClaw 时的两层结构：

- `extensions/feishu/src/event-types.ts`
  - `FeishuMessageEvent`
- `extensions/feishu/src/types.ts`
  - `FeishuMessageContext`

它们之间的转换入口是：

- `extensions/feishu/src/bot.ts`
  - `parseFeishuMessageEvent(...)`

所以当前最小闭环应该是：

```text
lark-cli raw
  -> 适配成 FeishuMessageEvent
  -> parseFeishuMessageEvent(...)
  -> FeishuMessageContext
```

注意：

- 真正直接走这条链的是 `即时通讯 / thread / system message / 同步消息`
- `文档 / Base / Sheet / Task / Wiki` 这些对象本体不直接走 Feishu channel ingress
- 它们是先作为 supporting object 存在，再通过“同步消息”进入主对话流

这也是为什么当前要重点看：

- `raw_channel_im_v0.jsonl`

而不是直接拿全部 `raw_dataset_v0.jsonl` 去喂 OpenClaw channel。

## 9. Lark CLI raw 和 OpenClaw 期待结构哪里没对齐

当前 `lark-cli` 导出的原始消息，和 OpenClaw Feishu 插件真正期待的 webhook/event 结构，并不是 1:1 一样。

### 8.1 外层 envelope 不一样

`lark-cli` 当前是一行一个：

```json
{
  "source_platform": "feishu",
  "chat_id": "oc_xxx",
  "message_scope": "main_chat",
  "raw_message": { ... }
}
```

但 OpenClaw Feishu 插件期待的是：

```json
{
  "sender": {
    "sender_id": { "open_id": "ou_xxx" },
    "sender_type": "user",
    "tenant_key": "..."
  },
  "message": {
    "message_id": "om_xxx",
    "root_id": "...",
    "parent_id": "...",
    "thread_id": "omt_xxx",
    "chat_id": "oc_xxx",
    "chat_type": "group",
    "message_type": "text",
    "content": "{\"text\":\"...\"}",
    "create_time": "...",
    "mentions": [...]
  }
}
```

也就是说：

- `lark-cli` 的行级包装，要改成 `sender + message`
- `raw_message` 里的字段，要下沉进 `message`

### 8.2 `content` 形态不一样

这是最重要的不对齐点。

当前 `lark-cli` 里你抓回来的 `raw_message.content` 已经是**人类可读的纯文本**，例如：

```json
"content": "【cjy】文档同步：@陈嘉怡 ..."
```

但 OpenClaw Feishu 插件里的 `parseMessageContent(...)` 期待的，是更接近 Feishu webhook 原始结构的 `message.content`：

- `text` 消息通常是 JSON 字符串：

```json
"{\"text\":\"【cjy】文档同步：@陈嘉怡 ...\"}"
```

这意味着：

- 你当前 raw 里已经丢掉了一层原始包装
- 所以不能说“当前 raw 可以直接零改动喂给 OpenClaw”
- 正确做法是：先把纯文本重新包装成最小可用的 `{"text":"..."}` 形式

### 8.2.1 文档链接不会自动变成文档正文

这点要单独写清楚。

你现在主群里像这样的消息：

```text
【cjy】文档同步：@陈嘉怡 请确认项目决策文档 https://.../docx/Ujo6deWD7os0pRxdY6KcNr7onQd 当前结论：...
```

进入 OpenClaw Feishu channel 之后，默认会发生的是：

- 插件读取这条消息本身的 `message.content`
- `parseMessageContent(...)` 从中提取文本
- `parseFeishuMessageEvent(...)` 把它变成 `FeishuMessageContext.content`

也就是说，OpenClaw 默认拿到的是：

- 链接文本
- 你同步时附带写在消息里的摘要/结论

而不是：

- 自动把 `docx` 正文全文再抓下来

当前代码里，普通消息主链没有“看到 doc 链接就自动拉全文”的逻辑。和这条结论直接相关的代码点是：

- `extensions/feishu/src/bot.ts`
  - `parseFeishuMessageEvent(...)`
- `extensions/feishu/src/bot-content.ts`
  - `parseMessageContent(...)`

这里做的是：

- 解析 `text/post/share_chat/merge_forward`
- 处理 mention
- 处理媒体

但没有在普通聊天入站里做：

- “发现文档链接 -> 自动调用 Drive/Docs API -> 注入正文”

所以答案是：

- 对，你现在“同步后的消息”并不会自动把真实文档正文一起带进来
- OpenClaw 自己按当前这条 Feishu channel 主链处理，也基本是一样的

唯一要补一句的是：

- OpenClaw repo 里还有一些别的 Feishu 能力，例如 drive/wiki/doc/comment monitor
- 但那不是“普通聊天消息 ingress 自动带正文”
- 那是别的 tool / monitor / sidecar 路径

### 8.3 mention 结构不一样

当前 raw 里 mention 更像：

```json
{
  "id": "ou_xxx",
  "name": "王程羽"
}
```

但 Feishu event 里期待的是：

```json
{
  "key": "@_user_1",
  "id": {
    "open_id": "ou_xxx"
  },
  "name": "王程羽"
}
```

所以需要做一次重包裹。

### 8.4 `chat_type` 当前没有直接保留

`FeishuMessageEvent.message.chat_type` 是必需信息之一。

而当前 `raw_channel_im_v0.jsonl` 只有：

- `chat_id`
- `message_scope`

所以当前脚本采取的是最小规则：

- `oc_` 开头的 chat 先统一推断成 `group`

对这版数据集来说这个推断是成立的，因为当前都是群聊。

### 8.5 `system` 消息不一定等价于真实 inbound event

当前主群里有两条 `system` 消息：

- `Welcome to {group_type}`
- `invited ... to the chat`

它们确实存在于聊天记录里，但它们不一定等价于“Feishu bot webhook 会像普通 text message 一样推给 OpenClaw 的事件”。

所以这类消息虽然保留在原始数据里，但在“构造可喂给 OpenClaw 的 ingress event”时，默认应该跳过。

### 8.6 任务对象本体不直接走这个入口

这点也要写死：

- `task` 本体不直接走 Feishu channel ingress
- 走 ingress 的是“任务同步消息”

同理：

- `doc` 本体不直接走 channel
- `base` 本体不直接走 channel
- `sheet` 本体不直接走 channel
- `wiki` 本体不直接走 channel

它们都要先被“说出来”，再进入 OpenClaw 主流。

## 10. 先做 Lark 归一化，再做 OpenClaw 对齐

我现在建议把脚本拆成两步，而不是一步直接硬转 OpenClaw：

### 10.1 第一步：`lark-cli raw -> lark normalized`

当前目录里新增了：

- `amem_docs/dataset_v1/larkcli_raw_to_lark_normalized.py`

它的输入是最原始的：

- `raw_feishu_fetches_2026-04-26.jsonl`
- `raw_feishu_fetches_2026-04-26-sync.jsonl`

它的输出是：

- `amem_docs/dataset_v1/lark_normalized_im_v0.jsonl`
- `amem_docs/dataset_v1/lark_normalized_im_report_v0.json`

如果当前目录里已经没有最初那两份：

- `raw_feishu_fetches_2026-04-26.jsonl`
- `raw_feishu_fetches_2026-04-26-sync.jsonl`

脚本会自动回退到：

- `raw_channel_im_v0.jsonl`
- `raw_dataset_v0.jsonl`

并在 `lark_normalized_im_report_v0.json` 里把 `fallback_mode: true` 写出来。

这一步只做：

- 把 main chat / thread reply 从最原始抓取里抽出来
- 统一成稳定字段
- 保留 `message_id / thread_id / parent_id / sender / mentions / content_text`
- 不引入 OpenClaw 特有包装

也就是说，这一步回答的是：

> 我从 lark-cli 原始抓取里，最小能稳定整理出什么？

### 10.2 第二步：`lark normalized -> OpenClaw ingress`

只有在你确认第一步的最小数据集合理后，才需要第二步：

- `amem_docs/dataset_v1/align_larkcli_to_openclaw_ingress.ts`

它做的是：

- 把 `lark_normalized_im_v0` 或 `raw_channel_im_v0` 再包装成更接近 `FeishuMessageEvent`
- 再用 OpenClaw 自己的 `parseFeishuMessageEvent(...)` 去看最终会变成什么 `FeishuMessageContext`

所以顺序应该是：

```text
lark-cli raw
  -> lark_normalized_im_v0
  -> openclaw ingress alignment
```

而不是一上来就问：

```text
lark-cli raw
  -> 能不能直接塞进 OpenClaw
```

## 11. 当前脚本怎么做最小对齐

当前目录里已经新增了脚本：

- `amem_docs/dataset_v1/align_larkcli_to_openclaw_ingress.ts`

它的输入是：

- `amem_docs/dataset_v1/raw_channel_im_v0.jsonl`

它会做 4 件事：

1. 过滤当前 raw 里的消息行
   - 保留 `main_chat` 和 `thread_reply`
   - 默认跳过 `system` 消息

2. 把 `raw_message` 适配成 `FeishuMessageEvent`
   - 包装成 `sender + message`
   - `text` 内容重新包装成 `{"text":"..."}` JSON 字符串
   - `mentions` 重包成 Feishu event 期待的结构
   - 对当前数据集把 `chat_type` 统一推断为 `group`

3. 直接复用 OpenClaw 里的：
   - `parseFeishuMessageEvent(...)`

4. 输出两份文件
   - `amem_docs/dataset_v1/feishu_channel_events_v0.jsonl`
   - `amem_docs/dataset_v1/feishu_message_contexts_v0.jsonl`

## 12. 当前脚本的边界

这不是“完整重建真实 Feishu webhook”的脚本，而是：

> 用当前已经抓回来的 `lark-cli` raw，构造一份最小可用的 OpenClaw ingress 适配版本。

它目前适用于：

- 普通 `text` 群消息
- `thread` 回复
- 带 mention 的文本消息

它目前不保证完全还原：

- bot mention 原始 `<at ...>` 标签字节级形态
- `post` 富文本消息
- `image/file/audio/video` 等媒体消息
- `merge_forward/share_chat` 这类特殊消息
- `system` 消息的真实 webhook 事件形态

所以这一步的目标不是“100% 复刻 Feishu webhook”，而是先回答：

> 当前这版数据集里，哪些 IM raw 已经足够接近 OpenClaw 的 Feishu channel 入口，能进入下一步实验？

## 13. 能不能直接把当前数据注入 OpenClaw

短答案：

- 不能直接零改动注入。

更准确地说：

- `lark-cli raw` 不是 OpenClaw 直接期待的事件格式
- `lark normalized` 也不是 OpenClaw 直接期待的事件格式
- OpenClaw 期待的是 `FeishuMessageEvent`

所以现在最合理的判断是：

1. 你当前最小数据集是：
   - `lark_normalized_im_v0.jsonl`
2. 你当前不能直接把它“不改一行”塞进 OpenClaw
3. 但你只需要再加一层很薄的 event wrapper，就可以接近真实 ingress

也就是：

```text
lark_normalized_im_v0
  + 薄 event wrapper
  -> FeishuMessageEvent
  -> OpenClaw parseFeishuMessageEvent(...)
```

## 14. 如何运行脚本

先跑第一步：

```bash
python3 amem_docs/dataset_v1/larkcli_raw_to_lark_normalized.py
```

然后如果你要继续做 OpenClaw 对齐，再跑第二步：

```bash
pnpm exec tsx amem_docs/dataset_v1/align_larkcli_to_openclaw_ingress.ts
```

第一步产物：

- `lark_normalized_im_v0.jsonl`
- `lark_normalized_im_report_v0.json`

第二步产物：

- `feishu_channel_events_v0.jsonl`
- `feishu_message_contexts_v0.jsonl`
- `feishu_alignment_report_v0.json`

我建议最终不是做成很多割裂的小文件，而是围绕一个统一项目 id 来组织。

### 6.1 顶层项目元信息

建议包含：

- `dataset_id`
- `workspace_id`
- `project_id`
- `project_name`
- `time_window`
- `actors`
- `domains_covered`

### 6.2 L0 对象记录

建议通用字段：

- `record_id`
- `domain`
- `kind`
- `object_id`
- `source_url`
- `captured_at`
- `raw_json`
- `sync_status`
- `sync_message_refs`

### 6.3 L1 对话记录

建议通用字段：

- `record_id`
- `chat_id`
- `thread_id`
- `message_id`
- `message_type`
- `sender_open_id`
- `sender_name`
- `content`
- `mentions`
- `linked_object_refs`
- `captured_at`

其中：

- `linked_object_refs`
  - 用来表达“这条消息是在同步哪个对象的事实”

---

## 7. 当前这个项目的 V1 最完整版本应该长什么样

如果按你现在的项目目标，我建议这个“单个完整数据集”至少覆盖：

### 7.1 当前已经有基础的

- `im`
- `docs`
- `task`
- `calendar`

### 7.2 下一批最值得补的

- `wiki`
- `approval`
- `okr`

### 7.3 条件允许再补的

- `mail`
- `meeting/minutes`
- `drive`
- `base`
- `sheets`

为什么这样排：

- `wiki / approval / okr`
  - 和“项目决策、状态、why、owner、blocker”最相关
- `mail / meeting`
  - 很有价值，但权限和流程通常更重
- `drive / base / sheets`
  - 也重要，但更像结构化补充层，可以在前面跑通后补

---

## 8. 这一版最重要的判断

你现在不是要证明：

- OpenClaw 已经原生支持所有飞书对象类型直连

而是要先证明：

- 这些飞书域都可以被纳入一个统一项目数据集
- 并且它们的关键事实可以通过同步消息进入主对话流

所以 V1 的成功标准不是“所有域都直连”，而是：

1. 每个域至少有一个真实对象
2. 每个域至少有一条同步消息
3. 这些同步消息能进入主群 / thread
4. 这些对话记录可以被适配成 OpenClaw Feishu channel ingress

---

## 9. 当前最建议的下一步

现在最合理的是按下面顺序继续：

1. 先基于现有 `raw_*` 文件生成：
   - `channel_dialogue_l1.jsonl`
   - `supporting_objects_l0.jsonl`
2. 再优先补 3 个新域：
   - `wiki`
   - `approval`
   - `okr`
3. 每补一个域，都同时补一条同步消息进入主群
4. 等到 6 到 8 个域都至少有：
   - 真实对象
   - 同步消息
     就可以认为这个项目的 V1 完整数据集基本成型了
