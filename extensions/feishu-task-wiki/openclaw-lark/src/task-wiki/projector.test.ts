import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const storeSymbol = Symbol.for("openclaw.feishuTaskWiki.bindingStore");

type BindingModule = {
  resolveTaskBindingForInbound: (params: Record<string, unknown>) => Record<string, unknown> | null;
};

type SessionModule = {
  maybeIngestTaskSourceSession: (params: Record<string, unknown>) => Promise<{
    sessionDir?: string;
    sourceSessionId?: string;
  }>;
};

type ProjectorModule = {
  updateTaskWikiFromVerifiedEvents: (params: { sessionDir: string }) => Promise<Record<string, unknown>>;
};

function loadBindingModule(): BindingModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("../task-banding/task-binding-store.js") as BindingModule;
}

function loadSessionModule(): SessionModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("../task-events/session-ingest.js") as SessionModule;
}

function loadProjectorModule(): ProjectorModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree is intentional
  return require("./projector.js") as ProjectorModule;
}

function makeVerifiedEvent(params: {
  eventId: string;
  sourceSessionId: string;
  ingestVersion: number;
  eventType:
    | "conclusion_event"
    | "rationale_event"
    | "objection_event"
    | "constraint_event"
    | "commitment_event"
    | "status_event"
    | "time_event"
    | "scope_event";
  claim: string;
  coreEntryId: string;
  evidenceQuote: string;
  eventTime: string;
  chatId: string;
  target?: string;
  reason?: string;
  objection?: string;
  objector?: string;
  constraint?: string;
  owner?: string;
  action?: string;
  status?: string;
  timeTarget?: string;
  timeValue?: string;
  certainty?: string;
  scopeTarget?: string;
  included?: string[];
  excluded?: string[];
}) {
  const base = {
    event_id: params.eventId,
    task_ref: "FEISHU-231",
    task_id: "task:FEISHU-231",
    source_session_id: params.sourceSessionId,
    ingest_version: params.ingestVersion,
    event_type: params.eventType,
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
  } satisfies Record<string, unknown>;

  switch (params.eventType) {
    case "conclusion_event":
      return { ...base, conclusion: params.claim, target: params.target };
    case "rationale_event":
      return { ...base, reason: params.reason ?? params.claim };
    case "objection_event":
      return {
        ...base,
        objection: params.objection ?? params.claim,
        objector: params.objector ?? "周宇",
        target: params.target,
      };
    case "constraint_event":
      return { ...base, constraint: params.constraint ?? params.claim, target: params.target };
    case "commitment_event":
      return { ...base, owner: params.owner ?? "张楠", action: params.action ?? params.claim };
    case "status_event":
      return { ...base, status: params.status ?? params.claim, target: params.target };
    case "time_event":
      return {
        ...base,
        time_target: params.timeTarget,
        time_value: params.timeValue,
        certainty: params.certainty ?? "暂定",
      };
    case "scope_event":
      return {
        ...base,
        scope_target: params.scopeTarget,
        included: params.included ?? [],
        excluded: params.excluded ?? [],
      };
  }
}

describe("task wiki projector", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-wiki-phase3-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER = "1";
    delete (globalThis as Record<PropertyKey, unknown>)[storeSymbol];
    delete process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_BASE_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.FEISHU_TASK_WIKI_MODEL;
    vi.restoreAllMocks();
  });

  afterEach(async () => {
    delete (globalThis as Record<PropertyKey, unknown>)[storeSymbol];
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    delete process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER;
    delete process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_BASE_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.FEISHU_TASK_WIKI_MODEL;
    vi.restoreAllMocks();
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  async function createSeedSession(chatId: string, rootMessageText: string) {
    const { resolveTaskBindingForInbound } = loadBindingModule();
    const { maybeIngestTaskSourceSession } = loadSessionModule();
    const binding = resolveTaskBindingForInbound({
      accountId: "default",
      sourceType: "chat",
      sourceId: `chat:${chatId}`,
      chatId,
      rootMessageText,
      allowInitialize: true,
    });
    const ingest = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: binding,
      sourceType: "chat",
      sourceId: `chat:${chatId}`,
      chatId,
      messageId: `om_seed_${chatId}`,
      senderId: "ou_pm",
      senderName: "林晨",
      content: rootMessageText,
      createTime: "2026-05-01T10:00:00.000Z",
    });
    return {
      sessionDir: ingest.sessionDir!,
      sourceSessionId: ingest.sourceSessionId!,
    };
  }

  async function writeSessionEvents(sessionDir: string, events: Array<Record<string, unknown>>) {
    await fs.writeFile(
      path.join(sessionDir, "session_events.jsonl"),
      events.map((event) => `${JSON.stringify(event)}\n`).join(""),
      "utf8",
    );
  }

  it("creates session_wiki, index, and task_wiki from verified session events", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const seed = await createSeedSession("oc_chat_p3_1", "创建任务 FEISHU-231：统一发布时间口径。");

    await writeSessionEvents(seed.sessionDir, [
      makeVerifiedEvent({
        eventId: "evt_conclusion_1",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "conclusion_event",
        claim: "内部暂按 5 月 5 日推进。",
        coreEntryId: "om_root_1",
        evidenceQuote: "内部暂按 5 月 5 日推进。",
        eventTime: "2026-05-01T10:00:00.000Z",
        chatId: "oc_chat_p3_1",
        target: "发布时间口径",
      }),
      makeVerifiedEvent({
        eventId: "evt_rationale_1",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "rationale_event",
        claim: "因为迁移窗口还没锁定。",
        coreEntryId: "om_reply_1",
        evidenceQuote: "因为迁移窗口还没锁定。",
        eventTime: "2026-05-01T10:01:00.000Z",
        chatId: "oc_chat_p3_1",
        reason: "迁移窗口还没锁定",
      }),
      makeVerifiedEvent({
        eventId: "evt_constraint_1",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "constraint_event",
        claim: "不要对外说死 5 月 5 日。",
        coreEntryId: "om_reply_2",
        evidenceQuote: "不要对外说死 5 月 5 日。",
        eventTime: "2026-05-01T10:02:00.000Z",
        chatId: "oc_chat_p3_1",
        target: "发布时间口径",
      }),
      makeVerifiedEvent({
        eventId: "evt_time_1",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "time_event",
        claim: "目标发布时间暂定 5 月 5 日。",
        coreEntryId: "om_reply_3",
        evidenceQuote: "目标发布时间暂定 5 月 5 日。",
        eventTime: "2026-05-01T10:03:00.000Z",
        chatId: "oc_chat_p3_1",
        timeTarget: "发布时间口径",
        timeValue: "5 月 5 日",
      }),
      makeVerifiedEvent({
        eventId: "evt_objection_1",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "objection_event",
        claim: "销售可能会把 5 月 5 日直接承诺给客户。",
        coreEntryId: "om_reply_4",
        evidenceQuote: "销售可能会把 5 月 5 日直接承诺给客户。",
        eventTime: "2026-05-01T10:04:00.000Z",
        chatId: "oc_chat_p3_1",
        target: "销售承诺风险",
        objector: "周宇",
      }),
    ]);

    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });

    const taskRoot = path.dirname(path.dirname(seed.sessionDir));
    const sessionWiki = await fs.readFile(path.join(seed.sessionDir, "session_wiki.md"), "utf8");
    const indexMd = await fs.readFile(path.join(taskRoot, "index.md"), "utf8");
    const taskWiki = await fs.readFile(path.join(taskRoot, "task_wiki.md"), "utf8");

    expect(sessionWiki).toContain("## Session Summary");
    expect(sessionWiki).toContain("## Memory Blocks");
    expect(sessionWiki).toContain("### Memory Block 1:");
    expect(sessionWiki).toContain("#### Evidence References");
    expect(indexMd).toContain("## Wiki Page Index");
    expect(indexMd).toContain("## Topic Routes");
    expect(indexMd).toContain("### 发布时间");
    expect(indexMd).toContain("### 风险");
    expect(taskWiki).toContain("## Current Summary");
    expect(taskWiki).toContain("## Current Conclusions");
    expect(taskWiki).toContain("## Objections / Risks");
    expect(sessionWiki).toContain("Event Ref:");
    expect(sessionWiki).toContain("Entry Ref:");
    expect(sessionWiki).toContain("session_events.jsonl#evt_conclusion_1");
    expect(indexMd).toContain("session_wiki.md#block-");
    expect(taskWiki).toContain("Block Ref:");
    expect(taskWiki).toContain("Event Ref:");
  });

  it("uses constrained LLM topic normalization to merge coarse groups into one block", async () => {
    process.env.OPENAI_API_KEY = "test-key";
    process.env.OPENAI_API_BASE_URL = "https://example.com/v1";
    process.env.FEISHU_TASK_WIKI_MODEL = "test-model";

    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        void input;
        callCount += 1;
        const rawBody = typeof init?.body === "string" ? init.body : "{}";
        const payload = JSON.parse(rawBody) as {
          messages?: Array<{ content?: string }>;
        };
        const userPrompt = String(payload.messages?.[1]?.content ?? "");
        if (userPrompt.includes("\"assignments\"")) {
          return {
            ok: true,
            text: async () =>
              JSON.stringify({
                choices: [
                  {
                    message: {
                      content: JSON.stringify({
                        assignments: [
                          {
                            event_id: "evt_conclusion_2",
                            topic_key: "发布时间口径",
                            topic_title: "发布时间口径",
                          },
                          {
                            event_id: "evt_time_2",
                            topic_key: "发布时间口径",
                            topic_title: "发布时间口径",
                          },
                        ],
                      }),
                    },
                  },
                ],
              }),
          } as Response;
        }
        return {
          ok: true,
          text: async () =>
            JSON.stringify({
              choices: [
                {
                  message: {
                    content: JSON.stringify({
                      summary: "受约束摘要。",
                    }),
                  },
                },
              ],
            }),
        } as Response;
      }),
    );

    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const seed = await createSeedSession("oc_chat_p3_2", "创建任务 FEISHU-231：统一发布时间。");

    await writeSessionEvents(seed.sessionDir, [
      makeVerifiedEvent({
        eventId: "evt_conclusion_2",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "conclusion_event",
        claim: "对外口径先按预计 5 月上旬。",
        coreEntryId: "om_root_2",
        evidenceQuote: "对外口径先按预计 5 月上旬。",
        eventTime: "2026-05-01T11:00:00.000Z",
        chatId: "oc_chat_p3_2",
        target: "发布时间口径",
      }),
      makeVerifiedEvent({
        eventId: "evt_time_2",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "time_event",
        claim: "上线日期暂定 5 月 5 日。",
        coreEntryId: "om_reply_22",
        evidenceQuote: "上线日期暂定 5 月 5 日。",
        eventTime: "2026-05-01T11:01:00.000Z",
        chatId: "oc_chat_p3_2",
        timeTarget: "上线日期",
        timeValue: "5 月 5 日",
      }),
    ]);

    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });

    const state = JSON.parse(
      await fs.readFile(path.join(seed.sessionDir, "session_wiki_state.json"), "utf8"),
    ) as {
      block_order: string[];
      blocks: Record<string, { topic_title: string }>;
    };

    expect(state.block_order).toHaveLength(1);
    expect(state.blocks[state.block_order[0]!]!.topic_title).toBe("发布时间口径");
    expect(callCount).toBeGreaterThan(0);
  });

  it("falls back to semantic topic seeds when LLM topic normalization is unavailable", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const seed = await createSeedSession("oc_chat_p3_2b", "创建任务 FEISHU-231：统一发布时间。");

    await writeSessionEvents(seed.sessionDir, [
      makeVerifiedEvent({
        eventId: "evt_commitment_seed",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "commitment_event",
        claim: "我会在文档里先保留 5 月 5 日目标，但标注存在 blocker。",
        coreEntryId: "om_seed_commitment",
        evidenceQuote: "我会在文档里先保留 5 月 5 日目标，但标注存在 blocker。",
        eventTime: "2026-05-01T11:10:00.000Z",
        chatId: "oc_chat_p3_2b",
        owner: "陈嘉怡",
        action: "我会在文档里先保留 5 月 5 日目标，但标注存在 blocker。",
      }),
      makeVerifiedEvent({
        eventId: "evt_time_seed",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "time_event",
        claim: "上线日期暂定 5 月 5 日。",
        coreEntryId: "om_seed_time",
        evidenceQuote: "上线日期暂定 5 月 5 日。",
        eventTime: "2026-05-01T11:11:00.000Z",
        chatId: "oc_chat_p3_2b",
        timeTarget: "上线日期",
        timeValue: "5 月 5 日",
      }),
    ]);

    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });

    const state = JSON.parse(
      await fs.readFile(path.join(seed.sessionDir, "session_wiki_state.json"), "utf8"),
    ) as {
      block_order: string[];
      blocks: Record<string, { topic_title: string }>;
    };

    const topicTitles = state.block_order.map((blockId) => state.blocks[blockId]!.topic_title);
    expect(topicTitles).toContain("发布时间口径");
    expect(topicTitles.every((title) => !title.includes("我会在文档里先保留"))).toBe(true);
  });

  it("preserves unrelated block summaries during incremental updates", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const seed = await createSeedSession("oc_chat_p3_3", "创建任务 FEISHU-231：推进上线准备。");

    const baseEvents = [
      makeVerifiedEvent({
        eventId: "evt_conclusion_3",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "conclusion_event",
        claim: "内部暂按 5 月 5 日推进。",
        coreEntryId: "om_root_3",
        evidenceQuote: "内部暂按 5 月 5 日推进。",
        eventTime: "2026-05-01T12:00:00.000Z",
        chatId: "oc_chat_p3_3",
        target: "发布时间口径",
      }),
      makeVerifiedEvent({
        eventId: "evt_objection_3",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 1,
        eventType: "objection_event",
        claim: "销售可能会把 5 月 5 日直接承诺给客户。",
        coreEntryId: "om_reply_31",
        evidenceQuote: "销售可能会把 5 月 5 日直接承诺给客户。",
        eventTime: "2026-05-01T12:01:00.000Z",
        chatId: "oc_chat_p3_3",
        target: "销售承诺风险",
        objector: "周宇",
      }),
    ];

    await writeSessionEvents(seed.sessionDir, baseEvents);
    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });

    const beforeState = JSON.parse(
      await fs.readFile(path.join(seed.sessionDir, "session_wiki_state.json"), "utf8"),
    ) as {
      blocks: Record<string, { topic_title: string; summary: string }>;
    };
    const riskBlockBefore = Object.values(beforeState.blocks).find((block) => block.topic_title === "销售承诺风险");
    expect(riskBlockBefore).toBeTruthy();

    await writeSessionEvents(seed.sessionDir, [
      ...baseEvents,
      makeVerifiedEvent({
        eventId: "evt_status_3",
        sourceSessionId: seed.sourceSessionId,
        ingestVersion: 2,
        eventType: "status_event",
        claim: "迁移窗口确认仍然卡住。",
        coreEntryId: "om_reply_32",
        evidenceQuote: "迁移窗口确认仍然卡住。",
        eventTime: "2026-05-01T12:05:00.000Z",
        chatId: "oc_chat_p3_3",
        target: "发布时间口径",
      }),
    ]);
    await updateTaskWikiFromVerifiedEvents({ sessionDir: seed.sessionDir });

    const afterState = JSON.parse(
      await fs.readFile(path.join(seed.sessionDir, "session_wiki_state.json"), "utf8"),
    ) as {
      blocks: Record<string, { topic_title: string; summary: string }>;
    };
    const riskBlockAfter = Object.values(afterState.blocks).find((block) => block.topic_title === "销售承诺风险");
    expect(riskBlockAfter?.summary).toBe(riskBlockBefore?.summary);
  });

  it("keeps only the newest current item for the same topic in task_wiki across sessions", async () => {
    const { updateTaskWikiFromVerifiedEvents } = loadProjectorModule();
    const first = await createSeedSession("oc_chat_p3_4a", "创建任务 FEISHU-231：统一发布时间口径。");
    const second = await createSeedSession("oc_chat_p3_4b", "同步任务 FEISHU-231：上线时间更新。");

    await writeSessionEvents(first.sessionDir, [
      makeVerifiedEvent({
        eventId: "evt_time_old",
        sourceSessionId: first.sourceSessionId,
        ingestVersion: 1,
        eventType: "time_event",
        claim: "目标发布时间暂定 5 月 5 日。",
        coreEntryId: "om_old_root",
        evidenceQuote: "目标发布时间暂定 5 月 5 日。",
        eventTime: "2026-05-01T09:00:00.000Z",
        chatId: "oc_chat_p3_4a",
        timeTarget: "发布时间口径",
        timeValue: "5 月 5 日",
      }),
    ]);
    await writeSessionEvents(second.sessionDir, [
      makeVerifiedEvent({
        eventId: "evt_time_new",
        sourceSessionId: second.sourceSessionId,
        ingestVersion: 1,
        eventType: "time_event",
        claim: "目标发布时间顺延到 5 月 8 日。",
        coreEntryId: "om_new_root",
        evidenceQuote: "目标发布时间顺延到 5 月 8 日。",
        eventTime: "2026-05-01T15:00:00.000Z",
        chatId: "oc_chat_p3_4b",
        timeTarget: "发布时间口径",
        timeValue: "5 月 8 日",
      }),
    ]);

    await updateTaskWikiFromVerifiedEvents({ sessionDir: first.sessionDir });
    await updateTaskWikiFromVerifiedEvents({ sessionDir: second.sessionDir });

    const taskRoot = path.dirname(path.dirname(first.sessionDir));
    const taskWikiState = JSON.parse(
      await fs.readFile(path.join(taskRoot, "task_wiki_state.json"), "utf8"),
    ) as {
      sections: {
        time: Array<{ claim: string }>;
      };
    };

    expect(taskWikiState.sections.time).toHaveLength(1);
    expect(taskWikiState.sections.time[0]?.claim).toBe("目标发布时间顺延到 5 月 8 日。");
  });
});
