import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const storeSymbol = Symbol.for("openclaw.feishuTaskWiki.bindingStore");

function loadBindingModule() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("../task-banding/task-binding-store.js") as {
    resolveTaskBindingForInbound: (params: Record<string, unknown>) => Record<string, unknown> | null;
  };
}

function loadSessionModule() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("../task-events/session-ingest.js") as {
    maybeIngestTaskSourceSession: (params: Record<string, unknown>) => Promise<{ sessionDir?: string; sourceSessionId?: string }>;
  };
}

function loadProjectorModule() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("./projector.js") as {
    updateTaskWikiFromVerifiedEvents: (params: { sessionDir: string }) => Promise<Record<string, unknown>>;
  };
}

function loadForgettingModule() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("./forgetting.js") as {
    revokeSourceSession: (params: { taskRootDir: string; sourceSessionId: string; reason?: string }) => Promise<Record<string, unknown>>;
    invalidateSessionEvent: (params: { taskRootDir: string; eventId: string; reason?: string }) => Promise<Record<string, unknown>>;
    supersedeSessionEvents: (params: { taskRootDir: string; supersedingEventId: string; supersededEventIds: string[]; reason?: string }) => Promise<Record<string, unknown>>;
  };
}

function makeVerifiedEvent(params: {
  eventId: string;
  sourceSessionId: string;
  eventType: "conclusion_event" | "time_event";
  claim: string;
  eventTime: string;
  chatId: string;
}) {
  const base = {
    event_id: params.eventId,
    task_ref: "FEISHU-231",
    task_id: "task:FEISHU-231",
    source_session_id: params.sourceSessionId,
    ingest_version: 1,
    event_type: params.eventType,
    claim: params.claim,
    core_entry_id: `${params.eventId}_core`,
    evidence_quote: params.claim,
    context_quotes: [],
    participants: ["林晨"],
    event_time: params.eventTime,
    source: {
      source_type: "chat",
      source_id: `chat:${params.chatId}`,
      chat_id: params.chatId,
      thread_id: null,
      root_id: null,
      locator: null,
    },
    confidence: 0.95,
    verification: {
      verdict: "verified",
    },
  } satisfies Record<string, unknown>;
  if (params.eventType === "conclusion_event") {
    return {
      ...base,
      conclusion: params.claim,
      target: "发布时间口径",
    };
  }
  return {
    ...base,
    time_target: "发布时间口径",
    time_value: params.claim,
    certainty: "暂定",
  };
}

describe("task wiki forgetting", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-wiki-forgetting-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER = "1";
    delete (globalThis as Record<PropertyKey, unknown>)[storeSymbol];
    delete process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_BASE_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.FEISHU_TASK_WIKI_MODEL;
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

  async function createSeedSession(chatId: string, text: string) {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();
    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: `chat:${chatId}`,
      chatId,
      rootMessageText: text,
      allowInitialize: true,
    });
    const ingest = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: `chat:${chatId}`,
      chatId,
      messageId: `om_${chatId}`,
      senderId: "ou_pm",
      senderName: "林晨",
      content: text,
      createTime: "2026-05-01T10:00:00.000Z",
    });
    return {
      sessionDir: ingest.sessionDir!,
      sourceSessionId: ingest.sourceSessionId!,
    };
  }

  it("revokes a source session and removes it from current task state", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const { revokeSourceSession } = loadForgettingModule();
    const seed = await createSeedSession("oc_forget_1", "创建任务 FEISHU-231：统一发布时间。");
    await fs.writeFile(
      path.join(seed.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedEvent({
        eventId: "evt_revoke_me",
        sourceSessionId: seed.sourceSessionId,
        eventType: "conclusion_event",
        claim: "先按 5 月 5 日推进。",
        eventTime: "2026-05-01T10:00:00.000Z",
        chatId: "oc_forget_1",
      }))}\n`,
      "utf8",
    );
    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });
    const taskRootDir = path.dirname(path.dirname(seed.sessionDir));

    await revokeSourceSession({
      taskRootDir,
      sourceSessionId: seed.sourceSessionId,
      reason: "source deleted",
    });

    const taskWiki = await fs.readFile(path.join(taskRootDir, "task_wiki.md"), "utf8");
    const sessionState = JSON.parse(
      await fs.readFile(path.join(seed.sessionDir, "session_wiki_state.json"), "utf8"),
    ) as {
      blocks: Record<string, { status: string }>;
    };
    const revocations = await fs.readFile(
      path.join(taskRootDir, "forgetting", "source_revocations.jsonl"),
      "utf8",
    );

    expect(taskWiki).not.toContain("先按 5 月 5 日推进。");
    expect(Object.values(sessionState.blocks).some((block) => block.status === "archived")).toBe(true);
    expect(revocations).toContain(seed.sourceSessionId);
  });

  it("invalidates an event and removes it from current task state", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const { invalidateSessionEvent } = loadForgettingModule();
    const seed = await createSeedSession("oc_forget_2", "创建任务 FEISHU-231：统一发布时间。");
    await fs.writeFile(
      path.join(seed.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedEvent({
        eventId: "evt_invalidate_me",
        sourceSessionId: seed.sourceSessionId,
        eventType: "conclusion_event",
        claim: "可以直接对外承诺 5 月 5 日。",
        eventTime: "2026-05-01T10:00:00.000Z",
        chatId: "oc_forget_2",
      }))}\n`,
      "utf8",
    );
    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });
    const taskRootDir = path.dirname(path.dirname(seed.sessionDir));

    await invalidateSessionEvent({
      taskRootDir,
      eventId: "evt_invalidate_me",
      reason: "claim not supported",
    });

    const taskWiki = await fs.readFile(path.join(taskRootDir, "task_wiki.md"), "utf8");
    const sessionWiki = await fs.readFile(path.join(seed.sessionDir, "session_wiki.md"), "utf8");

    expect(taskWiki).not.toContain("可以直接对外承诺 5 月 5 日。");
    expect(sessionWiki).toContain("[失效]");
  });

  it("supersedes an older event and keeps it historical in the old session wiki", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const { supersedeSessionEvents } = loadForgettingModule();
    const first = await createSeedSession("oc_forget_3a", "创建任务 FEISHU-231：统一发布时间。");
    const second = await createSeedSession("oc_forget_3b", "同步任务 FEISHU-231：发布时间更新。");
    await fs.writeFile(
      path.join(first.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedEvent({
        eventId: "evt_old_time",
        sourceSessionId: first.sourceSessionId,
        eventType: "time_event",
        claim: "5 月 5 日",
        eventTime: "2026-05-01T09:00:00.000Z",
        chatId: "oc_forget_3a",
      }))}\n`,
      "utf8",
    );
    await fs.writeFile(
      path.join(second.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedEvent({
        eventId: "evt_new_time",
        sourceSessionId: second.sourceSessionId,
        eventType: "time_event",
        claim: "5 月 8 日",
        eventTime: "2026-05-01T11:00:00.000Z",
        chatId: "oc_forget_3b",
      }))}\n`,
      "utf8",
    );
    await updateTaskWikiFromVerifiedEvents({ sessionDir: first.sessionDir });
    await updateTaskWikiFromVerifiedEvents({ sessionDir: second.sessionDir });
    const taskRootDir = path.dirname(path.dirname(first.sessionDir));

    await supersedeSessionEvents({
      taskRootDir,
      supersedingEventId: "evt_new_time",
      supersededEventIds: ["evt_old_time"],
      reason: "new launch date",
    });

    const oldSessionWiki = await fs.readFile(path.join(first.sessionDir, "session_wiki.md"), "utf8");
    const taskWikiState = JSON.parse(
      await fs.readFile(path.join(taskRootDir, "task_wiki_state.json"), "utf8"),
    ) as {
      sections: {
        time: Array<{ event_id: string; claim: string }>;
      };
    };

    expect(oldSessionWiki).toContain("[历史]");
    expect(oldSessionWiki).not.toContain("[当前] 5 月 5 日");
    expect(taskWikiState.sections.time).toHaveLength(1);
    expect(taskWikiState.sections.time[0]?.event_id).toBe("evt_new_time");
  });
});
