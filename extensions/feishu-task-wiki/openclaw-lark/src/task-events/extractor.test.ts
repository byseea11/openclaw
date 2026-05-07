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

function setLlmEnv() {
  process.env.OPENAI_API_KEY = "test-key";
  process.env.OPENAI_API_BASE_URL = "https://example.com/v1";
  process.env.FEISHU_TASK_WIKI_MODEL = "test-model";
}

function maskLlmEnv() {
  process.env.FEISHU_TASK_WIKI_API_KEY = " ";
  process.env.FEISHU_TASK_WIKI_API_BASE_URL = " ";
  process.env.FEISHU_TASK_WIKI_MODEL = " ";
  process.env.OPENAI_API_KEY = " ";
  process.env.OPENAI_API_BASE_URL = " ";
  process.env.OPENAI_MODEL = " ";
}

function buildExtractionParams(text = "发布时间口径这次先按方案 B 来。") {
  return {
    task: { taskId: "task:FEISHU-231", taskKey: "FEISHU-231", taskTitle: "FEISHU-231 发布任务" },
    sourceSessionId: "task:FEISHU-231::chat:oc_chat_1",
    ingestVersion: 1,
    coreEntries: [{ entry_id: "e1", text, sender_name: "林晨", create_time: "2026-05-01T10:00:00Z" }],
    contextEntries: [],
    sourceType: "chat",
    sourceId: "chat:oc_chat_1",
    chatId: "oc_chat_1",
  };
}

function stubChatCompletionContent(content: string) {
  const fetchMock = vi.fn(async () =>
    ({
      ok: true,
      text: async () =>
        JSON.stringify({
          choices: [
            {
              message: {
                content,
              },
            },
          ],
        }),
    }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubChatCompletionObject(result: Record<string, unknown>) {
  return stubChatCompletionContent(JSON.stringify(result));
}

describe("task event extractor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete process.env.FEISHU_TASK_WIKI_API_KEY;
    delete process.env.FEISHU_TASK_WIKI_API_BASE_URL;
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

  it("repairs Chinese status candidates with supported status and target fields", () => {
    const { validateCandidateEvent } = loadExtractorModule();
    const coreEntries = [{ entry_id: "om_status", text: "QA测试环境已准备。", sender_id: "ou_qa", sender_name: "唐越" }];

    const validated = validateCandidateEvent(
      {
        event_id: "evt_status",
        task_ref: "FEISHU-666",
        source_session_id: "task:FEISHU-666::chat:main",
        ingest_version: 1,
        event_type: "status_event",
        claim: "QA测试环境已准备。",
        core_entry_id: "om_status",
        evidence_quote: "QA测试环境已准备。",
        context_quotes: [],
        participants: ["唐越"],
        event_time: "2026-05-06T10:00:00Z",
        source: { source_type: "chat", source_id: "chat:main" },
        confidence: 0.7,
      },
      coreEntries,
    ) as {
      status?: string;
      target?: string;
      programmatic_validation?: { verdict?: string; missing_required_fields?: string[] };
    };

    expect(validated.status).toBe("QA测试环境已准备。");
    expect(validated.target).toBe("QA测试环境");
    expect(validated.programmatic_validation?.verdict).toBe("ready_for_verification");
    expect(validated.programmatic_validation?.missing_required_fields).toEqual([]);
  });

  it("repairs first-person commitment candidates with sender-backed owner", async () => {
    const { validateCandidateEvent, verifyCandidateEvent } = loadExtractorModule();
    const coreEntries = [{ entry_id: "om_commit", text: "好吧，我会安排夜间值班。", sender_id: "ou_ops", sender_name: "赵敏" }];

    const validated = validateCandidateEvent(
      {
        event_id: "evt_commit",
        task_ref: "FEISHU-666",
        source_session_id: "task:FEISHU-666::chat:main",
        ingest_version: 1,
        event_type: "commitment_event",
        claim: "赵敏承诺安排夜间值班。",
        core_entry_id: "om_commit",
        evidence_quote: "好吧，我会安排夜间值班。",
        context_quotes: [],
        participants: ["赵敏"],
        event_time: "2026-05-06T10:00:00Z",
        source: { source_type: "chat", source_id: "chat:main" },
        confidence: 0.7,
      },
      coreEntries,
    ) as {
      owner?: string;
      action?: string;
      programmatic_validation?: { verdict?: string };
    };

    expect(validated.owner).toBe("赵敏");
    expect(validated.action).toBe("好吧，我会安排夜间值班。");
    expect(validated.programmatic_validation?.verdict).toBe("ready_for_verification");

    const verified = await verifyCandidateEvent({
      candidateEvent: validated,
      coreEntries,
      contextEntries: [],
    });
    expect(verified.verification?.verdict).toBe("verified");
  });

  it("repairs Chinese time candidates with time target, value, and certainty", () => {
    const { validateCandidateEvent } = loadExtractorModule();
    const coreEntries = [{ entry_id: "om_time", text: "升级窗口5月10日22点UTC，已正式确认。", sender_name: "林晨" }];

    const validated = validateCandidateEvent(
      {
        event_id: "evt_time",
        task_ref: "FEISHU-666",
        source_session_id: "task:FEISHU-666::chat:main",
        ingest_version: 1,
        event_type: "time_event",
        claim: "升级窗口5月10日22点UTC已正式确认",
        core_entry_id: "om_time",
        evidence_quote: "升级窗口5月10日22点UTC",
        context_quotes: [],
        participants: ["林晨"],
        event_time: "2026-05-06T10:00:00Z",
        source: { source_type: "chat", source_id: "chat:main" },
        confidence: 0.7,
      },
      coreEntries,
    ) as {
      time_target?: string;
      time_value?: string;
      certainty?: string;
      programmatic_validation?: { verdict?: string };
    };

    expect(validated.time_target).toBe("升级窗口");
    expect(validated.time_value).toBe("5月10日22点UTC");
    expect(validated.certainty).toBe("确认");
    expect(validated.programmatic_validation?.verdict).toBe("ready_for_verification");
  });

  it("rejects private-only personal information when it is shaped as task status", () => {
    const { validateCandidateEvent } = loadExtractorModule();
    const coreEntries = [{ entry_id: "om_private", text: "我周四有个人面试。", sender_name: "陈雪" }];

    const validated = validateCandidateEvent(
      {
        event_id: "evt_private",
        task_ref: "FEISHU-666",
        source_session_id: "task:FEISHU-666::chat:main",
        ingest_version: 1,
        event_type: "status_event",
        claim: "陈雪周四有个人面试。",
        core_entry_id: "om_private",
        evidence_quote: "我周四有个人面试。",
        context_quotes: [],
        participants: ["陈雪"],
        event_time: "2026-05-06T10:00:00Z",
        source: { source_type: "chat", source_id: "chat:main" },
        confidence: 0.7,
      },
      coreEntries,
    ) as {
      programmatic_validation?: { verdict?: string; rejection_reasons?: string[] };
    };

    expect(validated.programmatic_validation?.verdict).toBe("rejected");
    expect(validated.programmatic_validation?.rejection_reasons).toContain("private_only_status_candidate");
  });

  it("uses LLM extraction when configured and normalizes candidate events", async () => {
    setLlmEnv();
    stubChatCompletionObject({
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
    });

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams("这次先按方案 B 来。"));

    expect(result).toHaveLength(1);
    expect(result[0]?.event_type).toBe("conclusion_event");
    expect(result[0]?.event_id).toBeTruthy();
  });

  it("falls back to heuristic extraction when LLM is not configured", async () => {
    maskLlmEnv();

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result.some((event) => event.event_type === "conclusion_event")).toBe(true);
  });

  it("falls back to heuristic extraction when LLM request throws", async () => {
    setLlmEnv();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result.some((event) => event.event_type === "conclusion_event")).toBe(true);
  });

  it("falls back to heuristic extraction when LLM returns invalid JSON content", async () => {
    setLlmEnv();
    stubChatCompletionContent("not valid json");

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result.some((event) => event.event_type === "conclusion_event")).toBe(true);
  });

  it("falls back to heuristic extraction when LLM response omits events", async () => {
    setLlmEnv();
    stubChatCompletionObject({});

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result.some((event) => event.event_type === "conclusion_event")).toBe(true);
  });

  it("falls back to heuristic extraction when LLM response events is null", async () => {
    setLlmEnv();
    stubChatCompletionObject({ events: null });

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result.some((event) => event.event_type === "conclusion_event")).toBe(true);
  });

  it("trusts an empty LLM events result instead of falling back to heuristic extraction", async () => {
    setLlmEnv();
    stubChatCompletionObject({ events: [] });

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result).toEqual([]);
  });

  it("trusts LLM output filtered to no supported event types instead of falling back", async () => {
    setLlmEnv();
    stubChatCompletionObject({
      events: [
        {
          event_type: "unsupported_event",
          claim: "发布时间口径这次先按方案 B 来",
          core_entry_id: "e1",
          evidence_quote: "发布时间口径这次先按方案 B 来",
        },
      ],
    });

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams());

    expect(result).toEqual([]);
  });

  it("does not turn a weak trigger into a conclusion event when LLM abstains", async () => {
    setLlmEnv();
    stubChatCompletionObject({ events: [] });

    const { extractCandidateEventsWithLLM } = loadExtractorModule();
    const result = await extractCandidateEventsWithLLM(buildExtractionParams("先看一下这个方案吧"));

    expect(result.some((event) => event.event_type === "conclusion_event")).toBe(false);
    expect(result).toEqual([]);
  });
});
