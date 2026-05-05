import { afterEach, describe, expect, it, vi } from "vitest";

type ExtractorModule = {
  extractCandidateEvents: (params: Record<string, unknown>) => Array<Record<string, unknown>>;
  extractCandidateEventsWithLLM: (params: Record<string, unknown>) => Promise<Array<Record<string, unknown>>>;
  validateCandidateEvent: (event: Record<string, unknown>, coreEntries: Array<Record<string, unknown>>) => Record<string, unknown>;
  verifyCandidateEvent: (params: {
    candidateEvent: Record<string, unknown>;
    coreEntries: Array<Record<string, unknown>>;
    contextEntries: Array<Record<string, unknown>>;
  }) => Promise<Record<string, unknown>>;
};

function loadExtractorModule(): ExtractorModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- package subtree is CommonJS on purpose
  return require("./extractor.js") as ExtractorModule;
}

describe("task event extractor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.OPENAI_API_KEY;
    delete process.env.OPENAI_API_BASE_URL;
    delete process.env.OPENAI_MODEL;
    delete process.env.FEISHU_TASK_WIKI_MODEL;
  });

  it("extracts all eight typed events with heuristic fallback", () => {
    const { extractCandidateEvents } = loadExtractorModule();

    const coreEntries = [
      { entry_id: "e1", text: "发布时间口径这次先按方案 B 来。", sender_id: "u1", sender_name: "林晨", create_time: "2026-05-01T10:00:00Z" },
      { entry_id: "e2", text: "因为迁移窗口还没锁定。", sender_id: "u2", sender_name: "周宇", create_time: "2026-05-01T10:01:00Z" },
      { entry_id: "e3", text: "研发这边担心发布时间口径这个日期先不要对外说死。", sender_id: "u3", sender_name: "陈雪", create_time: "2026-05-01T10:02:00Z" },
      { entry_id: "e4", text: "MVP 范围先不支持多审批人。", sender_id: "u4", sender_name: "王晨", create_time: "2026-05-01T10:03:00Z" },
      { entry_id: "e5", text: "张楠负责今天推进迁移窗口确认。", sender_id: "u5", sender_name: "张楠", create_time: "2026-05-01T10:04:00Z" },
      { entry_id: "e6", text: "迁移窗口目前还没完成确认，迁移窗口风险有点卡住。", sender_id: "u6", sender_name: "周宇", create_time: "2026-05-01T10:05:00Z" },
      { entry_id: "e7", text: "上线日期暂定 5 月 5 日。", sender_id: "u7", sender_name: "林晨", create_time: "2026-05-01T10:06:00Z" },
      { entry_id: "e8", text: "MVP 范围本期只做模板化配置，不做自定义节点。", sender_id: "u8", sender_name: "李哲", create_time: "2026-05-01T10:07:00Z" },
    ];

    const candidates = extractCandidateEvents({
      task: { taskKey: "FEISHU-231", taskTitle: "FEISHU-231 发布任务" },
      sourceSessionId: "task:FEISHU-231::chat:oc_chat_1",
      ingestVersion: 1,
      coreEntries,
      contextEntries: [],
      sourceType: "chat",
      sourceId: "chat:oc_chat_1",
      chatId: "oc_chat_1",
    });
    const eventTypes = new Set(candidates.map((event) => event.event_type));

    expect(eventTypes).toEqual(
      new Set([
        "conclusion_event",
        "rationale_event",
        "objection_event",
        "constraint_event",
        "commitment_event",
        "status_event",
        "time_event",
        "scope_event",
      ]),
    );
  });

  it("validates candidate events programmatically before verifier", () => {
    const { validateCandidateEvent } = loadExtractorModule();
    const coreEntries = [{ entry_id: "e1", text: "这次先按方案 B 来。", sender_id: "u1", sender_name: "林晨" }];

    const validated = validateCandidateEvent(
      {
        event_id: "evt_bad",
        task_ref: "FEISHU-231",
        source_session_id: "task:FEISHU-231::chat:oc_chat_1",
        ingest_version: 1,
        event_type: "conclusion_event",
        claim: "这次先按方案 B 来。",
        core_entry_id: "e1",
        evidence_quote: "这个 quote 不存在",
        context_quotes: [],
        participants: ["林晨"],
        event_time: "2026-05-01T10:00:00Z",
        source: { source_type: "chat", source_id: "chat:oc_chat_1" },
        confidence: 0.7,
        conclusion: "这次先按方案 B 来。",
        target: "FEISHU-231 发布任务",
      },
      coreEntries,
    ) as {
      verification?: { core_quote_found?: boolean; verdict?: string };
      programmatic_validation?: { verdict?: string };
    };

    expect(validated.verification?.core_quote_found).toBe(false);
    expect(validated.programmatic_validation?.verdict).toBe("rejected");
  });

  it("uses LLM extraction when configured and falls back to normalized candidate events", async () => {
    process.env.OPENAI_API_KEY = "test-key";
    process.env.OPENAI_API_BASE_URL = "https://example.com/v1";
    process.env.FEISHU_TASK_WIKI_MODEL = "test-model";

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        ({
          ok: true,
          text: async () =>
            JSON.stringify({
              choices: [
                {
                  message: {
                    content: JSON.stringify({
                      events: [
                        {
                          event_type: "conclusion_event",
                          claim: "本期先按方案 B 来",
                          core_entry_id: "e1",
                          evidence_quote: "这次先按方案 B 来",
                          conclusion: "先按方案 B 来",
                          target: "方案选择",
                        },
                      ],
                    }),
                  },
                },
              ],
            }),
        }) as Response),
    );

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM({
      task: { taskId: "task:FEISHU-231", taskKey: "FEISHU-231", taskTitle: "FEISHU-231 发布任务" },
      sourceSessionId: "task:FEISHU-231::chat:oc_chat_1",
      ingestVersion: 1,
      coreEntries: [{ entry_id: "e1", text: "这次先按方案 B 来。", sender_name: "林晨", create_time: "2026-05-01T10:00:00Z" }],
      contextEntries: [],
      sourceType: "chat",
      sourceId: "chat:oc_chat_1",
      chatId: "oc_chat_1",
    });

    expect(result).toHaveLength(1);
    expect(result[0]?.event_type).toBe("conclusion_event");
    expect(result[0]?.event_id).toBeTruthy();
  });
});
