import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import YAML from "yaml";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const storeSymbol = Symbol.for("openclaw.feishuTaskWiki.bindingStore");

type BindingModule = {
  resolveTaskBindingForInbound: (params: Record<string, unknown>) => Record<string, unknown> | null;
};

type SessionModule = {
  clearIdleDrainTimers: () => void;
  maybeIngestTaskSourceSession: (params: Record<string, unknown>) => Promise<{
    sessionDir?: string;
    sourceSessionId?: string;
  }>;
};

type RecallModule = {
  prepareSessionForCompaction: (params: { sessionDir: string }) => Promise<Record<string, unknown>>;
  recallTaskWiki: (params: {
    taskRootDir?: string;
    sessionDir?: string;
    includeSessionEvents?: boolean;
  }) => Promise<Record<string, unknown>>;
};

function loadBindingModule(): BindingModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("../task-banding/task-binding-store.js") as BindingModule;
}

function loadSessionModule(): SessionModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("../task-events/session-ingest.js") as SessionModule;
}

function loadRecallModule(): RecallModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("./recall.js") as RecallModule;
}

function makeVerifiedEvent(params: {
  eventId: string;
  sourceSessionId: string;
  ingestVersion: number;
  claim: string;
  coreEntryId: string;
  evidenceQuote: string;
  eventTime: string;
  chatId: string;
}) {
  return {
    event_id: params.eventId,
    task_ref: "FEISHU-231",
    task_id: "task:FEISHU-231",
    source_session_id: params.sourceSessionId,
    ingest_version: params.ingestVersion,
    event_type: "conclusion_event",
    claim: params.claim,
    core_entry_id: params.coreEntryId,
    evidence_quote: params.evidenceQuote,
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
    conclusion: params.claim,
    target: "发布时间口径",
  } satisfies Record<string, unknown>;
}

describe("task wiki recall seam", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-wiki-recall-"));
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
    try {
      loadSessionModule().clearIdleDrainTimers();
    } catch {}
    delete (globalThis as Record<PropertyKey, unknown>)[storeSymbol];
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    delete process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER;
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  async function createDirtySession() {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();
    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_recall_1",
      chatId: "oc_chat_recall_1",
      rootMessageText: "创建任务 FEISHU-231：统一发布时间口径。",
      allowInitialize: true,
    });
    await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_recall_1",
      chatId: "oc_chat_recall_1",
      messageId: "om_recall_seed_0",
      senderId: "ou_pm",
      senderName: "林晨",
      content: "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      createTime: "2026-05-01T10:00:00.000Z",
    });
    return await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_recall_1",
      chatId: "oc_chat_recall_1",
      messageId: "om_recall_seed_1",
      senderId: "ou_dev",
      senderName: "周宇",
      content: "研发这边担心迁移窗口还没锁定，所以 5 月 5 日只能暂定。",
      createTime: "2026-05-01T10:05:00.000Z",
    });
  }

  it("recallTaskWiki drains dirty sessions before reading task wiki state", async () => {
    const { recallTaskWiki } = loadRecallModule();
    const seed = await createDirtySession();

    const recalled = await recallTaskWiki({
      sessionDir: seed.sessionDir!,
    }) as {
      freshness: {
        drained_session_count: number;
        verified_event_count: number;
        projected_session_count: number;
      };
      taskWikiState: Record<string, unknown> | null;
      taskIndexState: Record<string, unknown> | null;
      sessions: Array<{ sessionWikiState: Record<string, unknown> | null; sessionEvents?: unknown[] }>;
    };

    expect(recalled.freshness.drained_session_count).toBe(1);
    expect(recalled.sessions).toHaveLength(1);
    const candidateEvents = await fs.readFile(path.join(seed.sessionDir!, "candidate_events.jsonl"), "utf8");
    expect(candidateEvents.trim()).not.toBe("");
    const pending = (await fs.readFile(path.join(seed.sessionDir!, "pending_ingests.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(pending.every((entry) => entry.status !== "pending_extraction")).toBe(true);

    const metadata = YAML.parse(await fs.readFile(path.join(seed.sessionDir!, "metadata.yaml"), "utf8")) as {
      last_drain_reason: string;
    };
    expect(metadata.last_drain_reason).toBe("recall");
  });

  it("recallTaskWiki projects existing verified events when state files are missing", async () => {
    const { maybeIngestTaskSourceSession } = loadSessionModule();
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { recallTaskWiki } = loadRecallModule();

    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_recall_projection",
      chatId: "oc_chat_recall_projection",
      rootMessageText: "创建任务 FEISHU-231：统一发布时间口径。",
      allowInitialize: true,
    });
    const seed = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_recall_projection",
      chatId: "oc_chat_recall_projection",
      messageId: "om_recall_projection_0",
      senderId: "ou_pm",
      senderName: "林晨",
      content: "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      createTime: "2026-05-01T10:00:00.000Z",
    });

    await fs.writeFile(
      path.join(seed.sessionDir!, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedEvent({
        eventId: "evt_recall_projection_1",
        sourceSessionId: seed.sourceSessionId!,
        ingestVersion: 1,
        claim: "内部暂按 5 月 5 日推进。",
        coreEntryId: "om_recall_projection_0",
        evidenceQuote: "内部暂按 5 月 5 日推进。",
        eventTime: "2026-05-01T10:00:00.000Z",
        chatId: "oc_chat_recall_projection",
      }))}\n`,
      "utf8",
    );

    const recalled = await recallTaskWiki({
      sessionDir: seed.sessionDir!,
    }) as {
      freshness: {
        projected_session_count: number;
      };
      taskWikiState: Record<string, unknown> | null;
      taskIndexState: Record<string, unknown> | null;
      sessions: Array<{ sessionWikiState: Record<string, unknown> | null; sessionEvents?: unknown[] }>;
    };

    expect(recalled.freshness.projected_session_count).toBe(1);
    expect(recalled.taskWikiState).toBeTruthy();
    expect(recalled.taskIndexState).toBeTruthy();
    expect(recalled.sessions[0]?.sessionWikiState).toBeTruthy();
    expect((recalled.sessions[0]?.sessionEvents ?? []).length).toBeGreaterThan(0);
  });

  it("prepareSessionForCompaction forces freshness before compaction work", async () => {
    const { prepareSessionForCompaction } = loadRecallModule();
    const seed = await createDirtySession();

    const prepared = await prepareSessionForCompaction({
      sessionDir: seed.sessionDir!,
    }) as {
      drained_session_count: number;
      verified_event_count: number;
      projected_session_count: number;
    };

    expect(prepared.drained_session_count).toBe(1);
    const candidateEvents = await fs.readFile(path.join(seed.sessionDir!, "candidate_events.jsonl"), "utf8");
    expect(candidateEvents.trim()).not.toBe("");

    const metadata = YAML.parse(await fs.readFile(path.join(seed.sessionDir!, "metadata.yaml"), "utf8")) as {
      last_drain_reason: string;
    };
    expect(metadata.last_drain_reason).toBe("pre_compaction");
  });
});
