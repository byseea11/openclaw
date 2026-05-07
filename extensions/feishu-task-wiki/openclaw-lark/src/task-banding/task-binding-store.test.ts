import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
const storeSymbol = Symbol.for("openclaw.feishuTaskWiki.bindingStore");

type BindingStoreModule = {
  resolveTaskBindingForInbound: (params: Record<string, unknown>) => {
    task: { taskId: string; taskKey: string };
    binding: { taskId: string; chatId: string | null; threadId?: string | null; rootId?: string | null };
    reason: string;
    sourceScope: string;
    taskSessionKey: string | null;
    taskQueueKey: string;
  } | null;
};

function loadStoreModule(): BindingStoreModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- package subtree is CommonJS on purpose
  return require("./task-binding-store.js") as BindingStoreModule;
}

describe("task binding store", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-binding-store-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    delete (globalThis as Record<PropertyKey, unknown>)[storeSymbol];
  });

  afterEach(async () => {
    delete (globalThis as Record<PropertyKey, unknown>)[storeSymbol];
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("initializes one task per new thread and reuses it on the same thread", () => {
    const { resolveTaskBindingForInbound } = loadStoreModule();

    const first = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_123",
      chatId: "oc_chat_123",
      threadId: "omt_123",
      rootId: "om_root_123",
      rootMessageText: "我们先统一 FEISHU-231 的发布时间口径，目标先看 5 月 5 日。",
      allowInitialize: true,
    });

    const second = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_123",
      chatId: "oc_chat_123",
      threadId: "omt_123",
      rootId: "om_root_123",
      rootMessageText: "这个日期先别对外说死。",
      allowInitialize: true,
    });

    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    expect(first?.reason).toBe("initialized");
    expect(second?.reason).toBe("thread_id");
    expect(second?.binding.taskId).toBe(first?.binding.taskId);
    expect(second?.taskQueueKey).toBe(first?.taskQueueKey);
  });

  it("allows queue binding without forcing an agent-scoped session key", () => {
    const { resolveTaskBindingForInbound } = loadStoreModule();

    const result = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_999",
      chatId: "oc_chat_999",
      threadId: "omt_999",
      rootId: "om_root_999",
      rootMessageText: "先确认 FEISHU-999 这条 thread 对应哪个任务。",
      allowInitialize: true,
    });

    expect(result).not.toBeNull();
    expect(result?.taskQueueKey).toContain(":task:");
    expect(result?.taskSessionKey).toBeNull();
  });

  it("does not initialize a task when no explicit task key is present", () => {
    const { resolveTaskBindingForInbound } = loadStoreModule();

    const result = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_plain",
      chatId: "oc_chat_plain",
      rootMessageText: "这周先把发布时间和迁移窗口再对齐一下。",
      allowInitialize: true,
    });

    expect(result).toBeNull();
  });

  it("maps different chats with the same task key to one canonical task", async () => {
    const { resolveTaskBindingForInbound } = loadStoreModule();

    const first = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_a",
      chatId: "oc_chat_a",
      rootMessageText: "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      allowInitialize: true,
    });

    const second = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_b",
      chatId: "oc_chat_b",
      rootMessageText: "同步 FEISHU-231：迁移窗口风险还没收敛。",
      allowInitialize: true,
    });

    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    expect(first?.task.taskId).toBe("task:FEISHU-231");
    expect(second?.task.taskId).toBe(first?.task.taskId);
    expect(second?.reason).toBe("task_key");

    const persisted = JSON.parse(
      await fs.readFile(path.join(stateDir, "feishu-task-wiki", "task-bindings.json"), "utf8"),
    ) as {
      tasks: Array<{ taskId: string; taskKey: string }>;
      bindings: Array<{ taskId: string; chatId: string | null }>;
    };
    expect(persisted.tasks).toHaveLength(1);
    expect(persisted.bindings).toHaveLength(2);
    expect(new Set(persisted.tasks.map((entry) => entry.taskId))).toEqual(new Set(["task:FEISHU-231"]));
    expect(new Set(persisted.tasks.map((entry) => entry.taskKey))).toEqual(new Set(["FEISHU-231"]));
    expect(new Set(persisted.bindings.map((entry) => entry.chatId))).toEqual(new Set(["oc_chat_a", "oc_chat_b"]));
  });

  it("adds a thread binding without deleting the original chat binding", async () => {
    const { resolveTaskBindingForInbound } = loadStoreModule();

    const chatBinding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_thread",
      chatId: "oc_chat_thread",
      rootMessageText: "创建任务 FEISHU-231：统一发布时间口径。",
      allowInitialize: true,
    });

    const threadBinding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_231",
      chatId: "oc_chat_thread",
      threadId: "omt_231",
      rootId: "om_root_231",
      rootMessageText: "同步 FEISHU-231：迁移窗口风险还没收敛。",
      allowInitialize: true,
    });

    const laterChatMessage = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_thread",
      chatId: "oc_chat_thread",
      rootMessageText: "这个日期先不要对外说死。",
      allowInitialize: true,
    });

    expect(chatBinding).not.toBeNull();
    expect(threadBinding).not.toBeNull();
    expect(laterChatMessage).not.toBeNull();
    expect(threadBinding?.task.taskId).toBe(chatBinding?.task.taskId);
    expect(laterChatMessage?.task.taskId).toBe(chatBinding?.task.taskId);
    expect(threadBinding?.reason).toBe("thread_backfill");

    const persisted = JSON.parse(
      await fs.readFile(path.join(stateDir, "feishu-task-wiki", "task-bindings.json"), "utf8"),
    ) as {
      tasks: Array<{ taskId: string }>;
      bindings: Array<{ taskId: string; chatId: string | null; threadId: string | null; rootId: string | null }>;
    };
    expect(persisted.tasks).toHaveLength(1);
    expect(persisted.bindings).toHaveLength(2);
    expect(persisted.bindings.filter((entry) => entry.chatId === "oc_chat_thread")).toHaveLength(2);
    expect(persisted.bindings.some((entry) => entry.threadId === "omt_231")).toBe(true);
  });
});
