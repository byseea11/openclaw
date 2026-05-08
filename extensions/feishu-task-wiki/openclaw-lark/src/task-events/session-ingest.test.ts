import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import YAML from "yaml";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const storeSymbol = Symbol.for("openclaw.feishuTaskWiki.bindingStore");

type TaskBindingModule = {
  resolveTaskBindingForInbound: (params: Record<string, unknown>) => {
    task: { taskId: string; taskKey: string };
    binding: { taskId: string; chatId: string | null; threadId?: string | null; rootId?: string | null };
    reason: string;
    sourceScope: string;
    taskSessionKey: string | null;
    taskQueueKey: string;
  } | null;
};

type SessionIngestResult = {
  skipped: boolean;
  reason?: string;
  taskId?: string;
  sourceSessionId?: string;
  ingestId?: string;
  ingestVersion?: number;
  sessionDir?: string;
  candidateEventCount?: number;
  verificationJobsQueued?: number;
  coreEntryCount?: number;
};

type SessionIngestModule = {
  maybeIngestTaskSourceSession: (params: Record<string, unknown>) => Promise<SessionIngestResult>;
  runVerificationJobs: (params: { sessionDir: string }) => Promise<Record<string, unknown>>;
};

function loadBindingModule(): TaskBindingModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- package subtree is CommonJS on purpose
  return require("../task-banding/task-binding-store.js") as TaskBindingModule;
}

function loadSessionModule(): SessionIngestModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- package subtree is CommonJS on purpose
  return require("./session-ingest.js") as SessionIngestModule;
}

async function readJsonlIfExists(filePath: string): Promise<Array<Record<string, unknown>>> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return raw.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line) as Record<string, unknown>);
  } catch {
    return [];
  }
}

describe("task event session ingest", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-events-"));
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
    delete process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER;
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("creates a stable chat source session, accumulates session files, and separates candidate/session events", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession, runVerificationJobs } = loadSessionModule();

    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_1",
      chatId: "oc_chat_1",
      rootMessageText: "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      allowInitialize: true,
    });

    expect(binding).not.toBeNull();

    const first = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_1",
      chatId: "oc_chat_1",
      messageId: "om_first",
      senderId: "ou_pm",
      senderName: "林晨",
      content: "创建任务 FEISHU-231：Q2 发布准备启动，目标先看 5 月 5 日。",
      createTime: "2026-05-01T10:00:00.000Z",
    });

    const second = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_1",
      chatId: "oc_chat_1",
      messageId: "om_second",
      senderId: "ou_dev",
      senderName: "周宇",
      content: "研发这边担心迁移窗口还没锁定，所以 5 月 5 日只能暂定。",
      createTime: "2026-05-01T10:05:00.000Z",
    });

    expect(first.skipped).toBe(false);
    expect(second.skipped).toBe(false);
    expect(first.sourceSessionId).toBe(second.sourceSessionId);
    expect(first.ingestVersion).toBe(1);
    expect(second.ingestVersion).toBe(2);
    expect(second.sessionDir).toBeTruthy();

    await runVerificationJobs({ sessionDir: second.sessionDir! });

    const sessionRoot = path.join(stateDir, "feishu-task-wiki", "tasks");
    const taskDirs = await fs.readdir(sessionRoot);
    const sessionDirs = await fs.readdir(path.join(sessionRoot, taskDirs[0]!, "sessions"));
    const sessionDir = path.join(sessionRoot, taskDirs[0]!, "sessions", sessionDirs[0]!);

    const streamManifest = JSON.parse(
      await fs.readFile(path.join(sessionDir, "session-stream.json"), "utf8"),
    ) as { latest_ingest_version: number; source_scope: string };
    expect(streamManifest.latest_ingest_version).toBe(2);
    expect(streamManifest.source_scope).toBe("chat:oc_chat_1");

    const metadata = YAML.parse(
      await fs.readFile(path.join(sessionDir, "metadata.yaml"), "utf8"),
    ) as { task_id: string; source_type: string; latest_ingest_version: number };
    expect(metadata.task_id).toBe("task:FEISHU-231");
    expect(metadata.source_type).toBe("chat");
    expect(metadata.latest_ingest_version).toBe(2);

    const pending = (await fs.readFile(path.join(sessionDir, "pending_ingests.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(pending).toHaveLength(2);

    const candidates = (await fs.readFile(path.join(sessionDir, "candidate_events.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    const verified = await readJsonlIfExists(path.join(sessionDir, "session_events.jsonl"));
    expect(candidates.length).toBeGreaterThan(0);
    expect(verified.every((entry) => (entry.verification as { verdict?: string } | undefined)?.verdict === "verified")).toBe(true);

    const sessionMarkdown = await fs.readFile(path.join(sessionDir, "session.md"), "utf8");
    expect(sessionMarkdown).toContain("om_first");
    expect(sessionMarkdown).toContain("om_second");
  });

  it("keeps chat and thread as separate source sessions under the same task", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();

    const chatBinding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_2",
      chatId: "oc_chat_2",
      rootMessageText: "创建任务 FEISHU-231：先统一发布时间口径。",
      allowInitialize: true,
    });
    const threadBinding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_231",
      chatId: "oc_chat_2",
      threadId: "omt_231",
      rootId: "om_root_231",
      rootMessageText: "同步 FEISHU-231：迁移窗口风险还没收敛。",
      allowInitialize: true,
    });

    const chatIngest = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: chatBinding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_2",
      chatId: "oc_chat_2",
      messageId: "om_chat",
      senderId: "ou_pm",
      senderName: "林晨",
      content: "创建任务 FEISHU-231：先统一发布时间口径。",
    });
    const threadIngest = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: threadBinding,
      sourceType: "thread",
      sourceId: "thread:omt_231",
      chatId: "oc_chat_2",
      threadId: "omt_231",
      rootId: "om_root_231",
      messageId: "om_thread",
      senderId: "ou_dev",
      senderName: "周宇",
      content: "迁移窗口还没锁定，所以这个日期先不要对外说死。",
      rootContent: "同步 FEISHU-231：迁移窗口风险还没收敛。",
    });

    expect(chatIngest.sourceSessionId).not.toBe(threadIngest.sourceSessionId);
    expect(chatIngest.taskId).toBe(threadIngest.taskId);
  });

  it("builds thread core with root plus current reply", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();

    const threadBinding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_555",
      chatId: "oc_chat_5",
      threadId: "omt_555",
      rootId: "om_root_555",
      rootMessageText: "创建任务 FEISHU-231：统一外部发布时间口径。",
      allowInitialize: true,
    });

    const ingest = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: threadBinding,
      sourceType: "thread",
      sourceId: "thread:omt_555",
      chatId: "oc_chat_5",
      threadId: "omt_555",
      rootId: "om_root_555",
      messageId: "om_reply_555",
      senderId: "ou_ops",
      senderName: "陈雪",
      content: "先不要对外说死 5 月 5 日。",
      rootContent: "创建任务 FEISHU-231：统一外部发布时间口径。",
    });

    const sessionDir = ingest.sessionDir!;
    const spans = (await fs.readFile(path.join(sessionDir, "evidence_spans.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    const latest = spans.at(-1) as {
      core_entries: Array<{ entry_id: string }>;
      trigger_entries: Array<{ entry_id: string }>;
      support_entries: Array<{ entry_id: string }>;
    };
    expect(latest.core_entries).toHaveLength(2);
    expect(latest.core_entries.map((entry) => entry.entry_id)).toContain("om_root_555");
    expect(latest.core_entries.map((entry) => entry.entry_id)).toContain("om_reply_555");
    expect(latest.trigger_entries.map((entry) => entry.entry_id)).toEqual(["om_reply_555"]);
    expect(latest.support_entries.map((entry) => entry.entry_id)).toEqual(["om_root_555"]);
  });

  it("uses comment source scope instead of collapsing comment sessions into chat scope", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();

    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "comment",
      sourceId: "comment:doc_token:comment_1",
      chatId: "comment_target_doc_token_comment_1",
      rootId: "comment_1",
      rootMessageText: "请在 FEISHU-231 里补充当前迁移窗口风险。",
      docTitle: "FEISHU-231 需求文档",
      allowInitialize: true,
    });

    const ingest = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "comment",
      sourceId: "comment:doc_token:comment_1",
      chatId: "comment_target_doc_token_comment_1",
      rootId: "comment_1",
      messageId: "comment_evt_1",
      senderId: "ou_reviewer",
      senderName: "陈雪",
      content: "请在 FEISHU-231 里补充当前迁移窗口风险。",
      rootContent: "请在 FEISHU-231 里补充当前迁移窗口风险。",
      replyChainContext: "[ou_pm]: 先把影响范围列清楚",
    });

    expect(ingest.skipped).toBe(false);
    expect(ingest.sourceSessionId).toContain("comment:doc_token:comment_1");
  });

  it("keeps ordinary ack ingests out of pending_extraction after immediate extraction", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();

    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_3",
      chatId: "oc_chat_3",
      rootMessageText: "创建任务 FEISHU-231：先统一发布时间口径。",
      allowInitialize: true,
    });

    const seed = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_3",
      chatId: "oc_chat_3",
      messageId: "om_seed",
      senderId: "ou_pm",
      senderName: "林晨",
      content: "创建任务 FEISHU-231：先统一发布时间口径。",
    });

    const jobsBefore = await readJsonlIfExists(path.join(seed.sessionDir!, "verification_jobs.jsonl"));

    const noEvent = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_3",
      chatId: "oc_chat_3",
      messageId: "om_no_event",
      senderId: "ou_dev",
      senderName: "周宇",
      content: "收到，了解。",
    });

    expect(noEvent.candidateEventCount ?? 0).toBeGreaterThanOrEqual(0);
    expect(noEvent.verificationJobsQueued ?? 0).toBeGreaterThanOrEqual(0);

    const pending = (await fs.readFile(path.join(noEvent.sessionDir!, "pending_ingests.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(pending.at(-1)?.status).not.toBe("pending_extraction");

    const jobs = await readJsonlIfExists(path.join(noEvent.sessionDir!, "verification_jobs.jsonl"));
    expect(jobs.length).toBeGreaterThanOrEqual(jobsBefore.length);
  });

  it("does not duplicate root-derived conclusion/time events in thread sessions", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession, runVerificationJobs } = loadSessionModule();

    const threadBinding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "thread",
      sourceId: "thread:omt_777",
      chatId: "oc_chat_7",
      threadId: "omt_777",
      rootId: "om_root_777",
      rootMessageText: "创建任务 FEISHU-231：目标发布时间暂定 5 月 5 日。",
      allowInitialize: true,
    });

    const first = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: threadBinding,
      sourceType: "thread",
      sourceId: "thread:omt_777",
      chatId: "oc_chat_7",
      threadId: "omt_777",
      rootId: "om_root_777",
      messageId: "om_reply_777_1",
      senderId: "ou_dev",
      senderName: "周宇",
      content: "迁移窗口还没锁定。",
      rootContent: "创建任务 FEISHU-231：目标发布时间暂定 5 月 5 日。",
    });
    await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: threadBinding,
      sourceType: "thread",
      sourceId: "thread:omt_777",
      chatId: "oc_chat_7",
      threadId: "omt_777",
      rootId: "om_root_777",
      messageId: "om_reply_777_2",
      senderId: "ou_ops",
      senderName: "陈雪",
      content: "迁移窗口风险仍然卡住。",
      rootContent: "创建任务 FEISHU-231：目标发布时间暂定 5 月 5 日。",
    });

    await runVerificationJobs({ sessionDir: first.sessionDir! });

    const verified = await readJsonlIfExists(path.join(first.sessionDir!, "session_events.jsonl"));
    expect(verified.every((entry) => entry.core_entry_id !== "om_root_777")).toBe(true);
    expect(verified.every((entry) => !["conclusion_event", "time_event"].includes(entry.event_type))).toBe(true);
  });

  it("compacts session markdown into a hot working view while retaining raw ingest metadata", async () => {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();

    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: "chat:oc_chat_9",
      chatId: "oc_chat_9",
      rootMessageText: "创建任务 FEISHU-231：先统一发布时间口径。",
      allowInitialize: true,
    });

    const seed = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: "chat:oc_chat_9",
      chatId: "oc_chat_9",
      messageId: "om_seed",
      senderId: "ou_pm",
      senderName: "林晨",
      content: "创建任务 FEISHU-231：先统一发布时间口径。",
    });

    for (let index = 1; index <= 25; index += 1) {
      await maybeIngestTaskSourceSession({
        accountId: "default",
        taskBinding: binding,
        sourceType: "chat",
        sourceId: "chat:oc_chat_9",
        chatId: "oc_chat_9",
        messageId: `om_cold_${index}`,
        senderId: "ou_dev",
        senderName: "周宇",
        content: `收到，第 ${index} 次同步。`,
      });
    }

    const markdown = await fs.readFile(path.join(seed.sessionDir!, "session.md"), "utf8");
    expect(markdown).toContain("om_seed");
    expect(markdown).toContain("om_cold_25");
    expect(markdown).not.toContain("### om_cold_4\n");

    const metadata = YAML.parse(await fs.readFile(path.join(seed.sessionDir!, "metadata.yaml"), "utf8")) as {
      raw_ingest_count: number;
      visible_ingest_count: number;
      retained_entry_count: number;
    };
    expect(metadata.raw_ingest_count).toBe(26);
    expect(metadata.visible_ingest_count).toBeGreaterThanOrEqual(20);
    expect(metadata.retained_entry_count).toBeGreaterThanOrEqual(21);
  });
});
