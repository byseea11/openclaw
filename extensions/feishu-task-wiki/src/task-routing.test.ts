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
    expect(bindingIndex.list()).toHaveLength(1);
  });
});
