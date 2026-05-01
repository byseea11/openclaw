# Feishu Task Wiki

这个扩展包用于承接 **Feishu/Lark 按 task 聚合上下文** 的三阶段实现，当前重点是第一阶段
`task binding`。

## 当前目标

这里不是简单做一组工具函数，而是把后续要改的 **task-first session routing**、event 抽取入口、
以及 `feishu_task_wiki` 投影能力，先收敛到一个 repo 内可维护的位置。

当前已经落下来的内容主要是：

- 新 `thread/root` 的 task 语义初始化
- `thread_id -> root_id -> chat_id -> source_id` 的绑定匹配优先级
- task-scoped session key 生成
- “命中 binding 就进 task session，否则保留 conversation session”的路由决策 helper

## 目录说明

### 1. 我们自己维护的 source-of-truth helper

- `src/task-binding.ts`
  - task profile 初始化
  - task 绑定记录结构
  - 绑定匹配优先级
  - in-memory binding index
- `src/task-routing.ts`
  - task-first route 决策
  - task session key 构造
  - “已绑定 / 初始化新 task / 保留原会话” 三种路径
- `src/task-routing.test.ts`
  - 第一阶段的核心约束测试

### 2. 从 live `openclaw-lark` runtime 同步进来的参考源码

这部分是为了让后面改 runtime 时，**不用再回头依赖外部已安装插件目录**。

当前已经同步进来的关键文件有：

- `runtime/openclaw-lark/src/channel/event-handlers.js`
- `runtime/openclaw-lark/src/channel/chat-queue.js`
- `runtime/openclaw-lark/src/messaging/inbound/dispatch-context.js`
- `runtime/openclaw-lark/src/messaging/inbound/dispatch.js`
- `runtime/openclaw-lark/src/messaging/inbound/handler.js`

这些文件目前的角色是：

- 作为 **live runtime 的对齐基线**
- 帮助我们看清现在真正的 queue key / route.sessionKey / threadSessionKey / dispatch 链路
- 方便后续把 task-first 路由真正接进去

## 非常重要：后续修改时的对齐原则

后续如果继续做 Feishu/Lark runtime 的 task-first 改造，需要优先对齐这里同步进来的 runtime
源码，而不是只看仓库里其他历史实现。

原因是：

- 真实在线行为最接近当前 live `openclaw-lark`
- queue key、dispatch context、effective session key 这些逻辑，不是在一个文件里决定的
- 如果只改 helper，不对照 runtime 链路，最后会出现“task binding 有了，但消息还是进老 session”的问题

所以这份包现在的定位是：

1. `src/` 下面放我们自己的规则和新逻辑
2. `runtime/openclaw-lark/` 下面放当前 live runtime 的参考基线
3. 后面真正接 runtime 时，以这两层一起推进

## 当前第一阶段约束

V1 的 task 语义处理方式是：

- 一个新 `thread/root` 第一次进入时，初始化一个 task
- 生成内部 `task_id`
- 把这个 `task_id` 和 `thread_id/root_id/chat_id/source_id` 绑定
- 后续同一个 `thread/root` 的消息，直接查表复用
- **一个 thread/root 默认只服务一个 task**
- thread 内后续如果讨论不同工作面，不再新建 task，而是交给后续 `memory_block` 处理

## 目前还没做的部分

当前还没有完成：

- 把这套 helper 真正接进 Feishu/Lark runtime 的消息入口
- 第二阶段 8 类 typed event 抽取主链
- 第三阶段 `session_wiki.md / index.md / task_wiki.md` 投影

也就是说，现在这份包已经是一个清晰的第一阶段起点，但还不是完整闭环。
