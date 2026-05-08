import { describe, expect, it } from "vitest";
import { InMemoryTaskBindingIndex } from "./task-binding.ts";
import { resolveTaskFirstRoute } from "./task-routing.ts";

describe("feishu task wiki routing", () => {
  it("initializes one task for a new thread and reuses it on later replies", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();

    const first = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_1",
        sourceType: "thread",
        sourceId: "thread:omt_123",
        chatId: "oc_chat_1",
        threadId: "omt_123",
        rootId: "om_root_1",
        rootMessageText: "我们先确定 FEISHU-231 的发布时间口径，目标先看 5 月 5 日。",
        replyTexts: ["研发需要先确认迁移窗口。"],
        chatTitle: "FEISHU-231 项目群",
      },
    });

    expect(first.kind).toBe("task_bound");
    if (first.kind !== "task_bound") {
      throw new Error("expected task-bound route");
    }
    expect(first.reason).toBe("initialized");
    expect(first.sessionKey).toContain(":feishu-task:");

    const second = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_1",
        sourceType: "thread",
        sourceId: "thread:omt_123",
        chatId: "oc_chat_1",
        threadId: "omt_123",
        rootId: "om_root_1",
        rootMessageText: "这个日期先别对外说死。",
      },
    });

    expect(second.kind).toBe("task_bound");
    if (second.kind !== "task_bound") {
      throw new Error("expected task-bound route");
    }
    expect(second.reason).toBe("thread_id");
    expect(second.sessionKey).toBe(first.sessionKey);
    expect(second.taskId).toBe(first.taskId);
  });

  it("falls back to root_id when the reply event does not carry thread_id", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();
    const initialized = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_2",
        sourceType: "thread",
        sourceId: "thread:omt_555",
        chatId: "oc_chat_2",
        threadId: "omt_555",
        rootId: "om_root_555",
        rootMessageText: "先确认 FEISHU-231 是否按 5 月 5 日推进。",
      },
    });

    const replyOnlyRoot = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_2",
        sourceType: "thread",
        sourceId: "thread:om_root_555",
        chatId: "oc_chat_2",
        rootId: "om_root_555",
        rootMessageText: "迁移窗口没锁定。",
      },
    });

    expect(initialized.kind).toBe("task_bound");
    expect(replyOnlyRoot.kind).toBe("task_bound");
    if (initialized.kind !== "task_bound" || replyOnlyRoot.kind !== "task_bound") {
      throw new Error("expected task-bound route");
    }
    expect(replyOnlyRoot.reason).toBe("root_id");
    expect(replyOnlyRoot.taskId).toBe(initialized.taskId);
  });

  it("keeps the original conversation session when there is no binding and no init context", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();
    const route = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:direct:ou_user_1",
        sourceType: "chat",
        sourceId: "chat:ou_user_1",
        chatId: "ou_user_1",
        allowInitialization: false,
      },
    });

    expect(route).toEqual({
      kind: "conversation",
      sessionKey: "agent:main:feishu:direct:ou_user_1",
    });
  });

  it("keeps the original conversation session when there is no explicit task key", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();
    const route = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_plain",
        sourceType: "chat",
        sourceId: "chat:oc_chat_plain",
        chatId: "oc_chat_plain",
        rootMessageText: "这周先把发布时间和迁移窗口再对齐一下。",
      },
    });

    expect(route).toEqual({
      kind: "conversation",
      sessionKey: "agent:main:feishu:group:oc_chat_plain",
    });
    expect(bindingIndex.listTasks()).toHaveLength(0);
    expect(bindingIndex.listBindings()).toHaveLength(0);
  });

  it("does not create a second task when the same thread discusses another work surface later", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();
    const first = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_3",
        sourceType: "thread",
        sourceId: "thread:omt_333",
        chatId: "oc_chat_3",
        threadId: "omt_333",
        rootId: "om_root_333",
        rootMessageText: "FEISHU-231 这周要先统一上线时间和对外口径。",
      },
    });

    const later = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_3",
        sourceType: "thread",
        sourceId: "thread:omt_333",
        chatId: "oc_chat_3",
        threadId: "omt_333",
        rootId: "om_root_333",
        rootMessageText: "另外运维这边也要看回滚预案。",
      },
    });

    expect(first.kind).toBe("task_bound");
    expect(later.kind).toBe("task_bound");
    if (first.kind !== "task_bound" || later.kind !== "task_bound") {
      throw new Error("expected task-bound route");
    }
    expect(later.taskId).toBe(first.taskId);
    expect(bindingIndex.listBindings()).toHaveLength(1);
  });

  it("reuses the same task across different chats when the task key is the same", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();

    const first = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_4",
        sourceType: "chat",
        sourceId: "chat:oc_chat_4",
        chatId: "oc_chat_4",
        rootMessageText: "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      },
    });

    const second = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_5",
        sourceType: "chat",
        sourceId: "chat:oc_chat_5",
        chatId: "oc_chat_5",
        rootMessageText: "同步 FEISHU-231：迁移窗口风险还没收敛。",
      },
    });

    expect(first.kind).toBe("task_bound");
    expect(second.kind).toBe("task_bound");
    if (first.kind !== "task_bound" || second.kind !== "task_bound") {
      throw new Error("expected task-bound route");
    }
    expect(first.taskId).toBe("task:FEISHU-231");
    expect(second.taskId).toBe(first.taskId);
    expect(second.reason).toBe("task_key");
    expect(second.sessionKey).toContain(":chat:oc_chat_5");
    expect(bindingIndex.listTasks()).toHaveLength(1);
    expect(bindingIndex.listBindings()).toHaveLength(2);
  });

  it("adds a thread binding while keeping the original chat binding", () => {
    const bindingIndex = new InMemoryTaskBindingIndex();

    const chatLevel = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_6",
        sourceType: "chat",
        sourceId: "chat:oc_chat_6",
        chatId: "oc_chat_6",
        rootMessageText: "创建任务 FEISHU-231：先统一对外发布时间口径。",
      },
    });

    const threadLevel = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_6",
        sourceType: "thread",
        sourceId: "thread:omt_666",
        chatId: "oc_chat_6",
        threadId: "omt_666",
        rootId: "om_root_666",
        rootMessageText: "同步 FEISHU-231：迁移窗口风险要继续评估。",
      },
    });

    const laterChatLevel = resolveTaskFirstRoute({
      bindingIndex,
      input: {
        agentId: "main",
        conversationSessionKey: "agent:main:feishu:group:oc_chat_6",
        sourceType: "chat",
        sourceId: "chat:oc_chat_6",
        chatId: "oc_chat_6",
        rootMessageText: "这个日期先不要对外说死。",
      },
    });

    expect(chatLevel.kind).toBe("task_bound");
    expect(threadLevel.kind).toBe("task_bound");
    expect(laterChatLevel.kind).toBe("task_bound");
    if (chatLevel.kind !== "task_bound" || threadLevel.kind !== "task_bound" || laterChatLevel.kind !== "task_bound") {
      throw new Error("expected task-bound route");
    }
    expect(threadLevel.taskId).toBe(chatLevel.taskId);
    expect(laterChatLevel.taskId).toBe(chatLevel.taskId);
    expect(threadLevel.reason).toBe("thread_backfill");
    expect(threadLevel.sessionKey).toContain(":thread:omt_666");
    expect(bindingIndex.listTasks()).toHaveLength(1);
    expect(bindingIndex.listBindings()).toHaveLength(2);
    expect(bindingIndex.listBindings().filter((binding) => binding.chatId === "oc_chat_6")).toHaveLength(2);
  });
});
