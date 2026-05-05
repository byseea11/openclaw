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

function loadLintModule() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("./lint.js") as {
    runTaskWikiLint: (params: { taskRootDir: string; appendLog?: boolean }) => Promise<Record<string, unknown>>;
  };
}

function makeVerifiedConclusion(params: {
  eventId: string;
  sourceSessionId: string;
  claim: string;
  eventTime: string;
  chatId: string;
}) {
  return {
    event_id: params.eventId,
    task_ref: "FEISHU-231",
    task_id: "task:FEISHU-231",
    source_session_id: params.sourceSessionId,
    ingest_version: 1,
    event_type: "conclusion_event",
    claim: params.claim,
    conclusion: params.claim,
    target: "发布时间口径",
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
  };
}

describe("task wiki lint", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-wiki-lint-"));
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

  it("reports orphan events and missing evidence references", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const { runTaskWikiLint } = loadLintModule();
    const seed = await createSeedSession("oc_lint_1", "创建任务 FEISHU-231：统一发布时间。");

    await fs.writeFile(
      path.join(seed.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedConclusion({
        eventId: "evt_orphan",
        sourceSessionId: seed.sourceSessionId,
        claim: "先按 5 月 5 日推进。",
        eventTime: "2026-05-01T10:00:00.000Z",
        chatId: "oc_lint_1",
      }))}\n`,
      "utf8",
    );
    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });

    const statePath = path.join(seed.sessionDir, "session_wiki_state.json");
    const state = JSON.parse(await fs.readFile(statePath, "utf8")) as {
      block_order: string[];
      blocks: Record<string, { event_ids: string[]; evidence_refs: unknown[] }>;
    };
    const firstBlock = state.block_order[0]!;
    state.blocks[firstBlock]!.event_ids = [];
    state.blocks[firstBlock]!.evidence_refs = [];
    await fs.writeFile(statePath, JSON.stringify(state, null, 2), "utf8");

    const taskRootDir = path.dirname(path.dirname(seed.sessionDir));
    const lintState = await runTaskWikiLint({ taskRootDir });
    const orphanFile = await fs.readFile(path.join(taskRootDir, "lint", "orphan_events.md"), "utf8");

    expect((lintState as { orphan_event_count: number }).orphan_event_count).toBeGreaterThan(0);
    expect(orphanFile).toContain("orphan event evt_orphan");
    expect(orphanFile).toContain("missing evidence refs");
  });

  it("reports open conflicts for competing current conclusions", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const { runTaskWikiLint } = loadLintModule();
    const first = await createSeedSession("oc_lint_2a", "创建任务 FEISHU-231：统一发布时间。");
    const second = await createSeedSession("oc_lint_2b", "同步 FEISHU-231：更新发布时间。");

    await fs.writeFile(
      path.join(first.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedConclusion({
        eventId: "evt_conflict_old",
        sourceSessionId: first.sourceSessionId,
        claim: "当前结论是 5 月 5 日可发。",
        eventTime: "2026-05-01T09:00:00.000Z",
        chatId: "oc_lint_2a",
      }))}\n`,
      "utf8",
    );
    await fs.writeFile(
      path.join(second.sessionDir, "session_events.jsonl"),
      `${JSON.stringify(makeVerifiedConclusion({
        eventId: "evt_conflict_new",
        sourceSessionId: second.sourceSessionId,
        claim: "当前结论是 5 月 8 日才可发。",
        eventTime: "2026-05-01T11:00:00.000Z",
        chatId: "oc_lint_2b",
      }))}\n`,
      "utf8",
    );

    await updateTaskWikiFromVerifiedEvents({ sessionDir: first.sessionDir });
    await updateTaskWikiFromVerifiedEvents({ sessionDir: second.sessionDir });

    const taskRootDir = path.dirname(path.dirname(first.sessionDir));
    const lintState = await runTaskWikiLint({ taskRootDir });
    const conflictsFile = await fs.readFile(path.join(taskRootDir, "lint", "open_conflicts.md"), "utf8");

    expect((lintState as { open_conflict_count: number }).open_conflict_count).toBeGreaterThan(0);
    expect(conflictsFile).toContain("发布时间口径");
    expect(conflictsFile).toContain("5 月 5 日可发");
    expect(conflictsFile).toContain("5 月 8 日才可发");
  });
});
