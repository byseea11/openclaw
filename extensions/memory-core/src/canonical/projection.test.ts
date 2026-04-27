import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type {
  MemoryTranscriptSpanEntry,
  OpenClawConfig,
} from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setDefaultExtractorClient, type CanonicalExtractorClient } from "./index.js";
import {
  drainPendingGraphUpdates,
  handleGraphAfterTurn,
  handleGraphBeforeCompaction,
} from "./projection.js";
import { searchGraphV2 } from "./query-v2.js";
import { closeAllCanonicalStores, getCanonicalStore } from "./store.js";

function cfg(tracePath?: string): OpenClawConfig {
  return {
    memory: {
      backend: "builtin",
    },
    plugins: {
      entries: {
        "memory-core": {
          config: {
            graphIndex: {
              enabled: true,
              ...(tracePath
                ? {
                    trace: {
                      enabled: true,
                      filePath: tracePath,
                      includeEntryPreview: true,
                      maxPreviewChars: 80,
                    },
                  }
                : {}),
            },
          },
        },
      },
    },
  } as OpenClawConfig;
}

function entry(overrides: Partial<MemoryTranscriptSpanEntry> = {}): MemoryTranscriptSpanEntry {
  return {
    entryId: "entry-1",
    parentId: null,
    entryType: "message",
    messageRole: "assistant",
    messageContent:
      "FEISHU-231 这周先按 5 月 5 日推进，但 5 月 5 日不是已确认发布日期，因为迁移窗口还没锁定。",
    toolName: null,
    toolResult: null,
    timestamp: "2026-04-17T00:00:00.000Z",
    ...overrides,
  };
}

function createMockExtractorClient(): CanonicalExtractorClient {
  return {
    async extractGraphEvents() {
      return {
        extraction: {
          should_extract: true,
          topic_ref: "topic:task:FEISHU-231:release_date",
          topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
          decision_axis_key: "release_date",
          decision_axis_text: "Whether the release date is confirmed",
          decision_axis_instance_id: null,
          claims: [
            {
              claim_field: "time_point",
              claim_text: "5 月 5 日不是已确认发布日期",
              claim_value_json: {
                date: "2026-05-05",
                role: "target_date",
                modality: "not_confirmed",
              },
              evidence_quote: "5 月 5 日不是已确认发布日期",
              confidence: 0.93,
            },
            {
              claim_field: "rationale",
              claim_text: "迁移窗口还没锁定",
              claim_value_json: { reason_type: "risk_or_blocker" },
              evidence_quote: "迁移窗口还没锁定",
              confidence: 0.88,
            },
          ],
        },
      };
    },
  };
}

function createDecisionCardExtractorClient(): CanonicalExtractorClient {
  return {
    async extractGraphEvents() {
      return {
        extraction: {
          should_extract: true,
          topic_ref: "topic:task:FEISHU-231:release_date",
          topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
          decision_axis_key: "release_date",
          decision_axis_text: "Whether the release date is confirmed",
          decision_axis_instance_id: null,
          claims: [
            {
              claim_field: "conclusion",
              claim_text: "当前口径是不把 5 月 5 日当成已确认发布日期。",
              claim_value_json: {
                modality: "not_confirmed",
              },
              evidence_quote: "5 月 5 日不是已确认发布日期",
              confidence: 0.92,
            },
            {
              claim_field: "time_point",
              claim_text: "5 月 5 日不是已确认发布日期",
              claim_value_json: {
                date: "2026-05-05",
                role: "target_date",
                modality: "not_confirmed",
              },
              evidence_quote: "5 月 5 日不是已确认发布日期",
              confidence: 0.93,
            },
            {
              claim_field: "rationale",
              claim_text: "迁移窗口还没锁定",
              claim_value_json: { reason_type: "risk_or_blocker" },
              evidence_quote: "迁移窗口还没锁定",
              confidence: 0.88,
            },
          ],
        },
      };
    },
  };
}

function createContextAwareExtractorClient(): CanonicalExtractorClient {
  return {
    async extractGraphEvents() {
      return {
        extraction: {
          should_extract: true,
          topic_ref: "topic:task:FEISHU-231:release_date",
          topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
          decision_axis_key: "release_date",
          decision_axis_text: "Whether the release date is confirmed",
          decision_axis_instance_id: null,
          claims: [
            {
              claim_field: "objection",
              claim_text: "不要把 5 月 5 日作为确认日期对外同步。",
              claim_value_json: {
                core_entry_id: "entry-core",
                supporting_context_quotes: [
                  {
                    quote: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
                    entry_id: "entry-ctx-1",
                    source: "context",
                  },
                  {
                    quote: "迁移窗口还没锁定。",
                    entry_id: "entry-ctx-2",
                    source: "context",
                  },
                ],
              },
              evidence_quote: "不要对外说死",
              confidence: 0.9,
            },
          ],
        },
      };
    },
  };
}

function createContextOnlyExtractorClient(): CanonicalExtractorClient {
  return {
    async extractGraphEvents() {
      return {
        extraction: {
          should_extract: true,
          topic_ref: "topic:task:FEISHU-231:release_date",
          topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
          decision_axis_key: "release_date",
          decision_axis_text: "Whether the release date is confirmed",
          decision_axis_instance_id: null,
          claims: [
            {
              claim_field: "conclusion",
              claim_text: "当前结论是先按 5 月 5 日推进。",
              claim_value_json: {
                core_entry_id: "entry-core-ack",
                supporting_context_quotes: [
                  {
                    quote: "当前结论：先按 5 月 5 日推进。",
                    entry_id: "entry-ctx-old",
                    source: "context",
                  },
                ],
              },
              evidence_quote: "收到",
              confidence: 0.9,
            },
          ],
        },
      };
    },
  };
}

function createFailingExtractorClient(message = "gateway timeout after 60000ms"): CanonicalExtractorClient {
  return {
    async extractGraphEvents() {
      throw new Error(message);
    },
  };
}

describe("canonical decision transcript projection v2", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-projection-v2-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    setDefaultExtractorClient(createMockExtractorClient());
  });

  afterEach(async () => {
    setDefaultExtractorClient(null);
    await closeAllCanonicalStores();
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("marks afterTurn spans dirty without per-turn semantic writes", async () => {
    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    });

    const store = getCanonicalStore("main");
    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 0,
      evidenceRecordsV2Total: 0,
      pendingProjectionSpans: 1,
    });
  });

  it("drains transcript spans into decision semantic tables", async () => {
    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId: "main",
      sourceId: "agent:channel:thread",
      reason: "recall",
    });

    const store = getCanonicalStore("main");
    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 2,
      decisionStatesV2Total: 1,
      pendingProjectionSpans: 0,
    });
    const decisionStates = store.findDecisionStatesByAnchor({
      anchorType: "task",
      anchorRef: "FEISHU-231",
      decisionAxisKey: "release_date",
      limit: 5,
    });
    expect(decisionStates).toEqual([
      expect.objectContaining({
        topic_ref: "topic:task:FEISHU-231:release_date",
        decision_axis_key: "release_date",
      }),
    ]);
    const exported = await store.exportData();
    expect(exported.evidence).toEqual(
      expect.arrayContaining([expect.objectContaining({ source_platform: "transcript" })]),
    );
    expect(exported.events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          event_type: "decision_claim_recorded",
          subject_ref: "topic:task:FEISHU-231:release_date",
        }),
      ]),
    );
    expect(exported.decisionStates).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ topic_ref: "topic:task:FEISHU-231:release_date" }),
      ]),
    );
  });

  it("runs the decision memory V1 chain end to end", async () => {
    const agentId = "smoke-agent";
    const sessionKey = "agent:channel:decision-thread";
    setDefaultExtractorClient(createDecisionCardExtractorClient());

    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-smoke",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [entry({ entryId: "entry-smoke", messageRole: "user" })],
      prePromptMessageCount: 4,
    });

    const store = getCanonicalStore(agentId);
    expect(store.getStatus()).toMatchObject({
      pendingProjectionSpans: 1,
    });
    expect(store.getProjectionState(sessionKey)).toMatchObject({
      status: "dirty",
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId,
      sourceId: sessionKey,
      reason: "recall",
    });

    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 3,
      decisionStatesV2Total: 1,
      pendingProjectionSpans: 0,
    });

    const decisionState = store.getDecisionStateV2("topic:task:FEISHU-231:release_date");
    expect(decisionState).toMatchObject({
      topic_ref: "topic:task:FEISHU-231:release_date",
      decision_axis_key: "release_date",
      active_conclusion_event_id: expect.any(String),
      active_rationale_event_ids_json: expect.stringContaining("["),
      active_time_point_event_ids_json: expect.stringContaining("["),
      last_event_id: expect.any(String),
    });

    const result = await searchGraphV2(store, "FEISHU-231 为什么 5 月 5 日不是确认日期？", 5);
    expect(result.queryClass).toBe("decision_card");
    expect(result.hits).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "state",
          snippet_structured: expect.objectContaining({
            query_kind: "decision_card",
            topic_ref: "topic:task:FEISHU-231:release_date",
            decision_axis_key: "release_date",
            current_conclusion: "当前口径是不把 5 月 5 日当成已确认发布日期。",
            rationales: expect.arrayContaining(["迁移窗口还没锁定"]),
            time_point_claims: expect.arrayContaining([
              "5 月 5 日不是已确认发布日期",
            ]),
            evidence_refs: expect.arrayContaining([
              expect.objectContaining({
                quote: "5 月 5 日不是已确认发布日期",
              }),
              expect.objectContaining({
                quote: "迁移窗口还没锁定",
              }),
            ]),
          }),
        }),
      ]),
    );
  });

  it("uses context entries only to resolve references while extracting from core", async () => {
    const agentId = "context-agent";
    const sessionKey = "agent:channel:context-thread";
    setDefaultExtractorClient(createContextAwareExtractorClient());

    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-context-1",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-ctx-1",
          messageRole: "user",
          messageContent: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
        }),
        entry({
          entryId: "entry-ctx-2",
          messageRole: "assistant",
          messageContent: "迁移窗口还没锁定。",
          timestamp: "2026-04-17T00:00:30.000Z",
        }),
      ],
      prePromptMessageCount: 4,
    });
    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-context-2",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-core",
          messageRole: "assistant",
          messageContent: "那就先按这个来，但不要对外说死。",
          timestamp: "2026-04-17T00:01:00.000Z",
        }),
      ],
      prePromptMessageCount: 5,
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId,
      sourceId: sessionKey,
      reason: "recall",
    });

    const store = getCanonicalStore(agentId);
    const exported = await store.exportData();
    expect(exported.events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          event_type: "decision_claim_recorded",
          payload_json: expect.stringContaining("\"supporting_context_quotes\""),
        }),
      ]),
    );
    const persistedEvidence = exported.evidence.at(-1);
    expect(persistedEvidence).toBeTruthy();
    expect(JSON.parse(persistedEvidence!.content_json as string) as Record<string, unknown>).toMatchObject({
      resolved_core_entry_id: "entry-core",
      supporting_context_entry_ids: ["entry-ctx-1", "entry-ctx-2"],
    });
    expect(persistedEvidence?.content_text).toBe("不要对外说死");
  });

  it("does not re-extract context-only claims when core has no new semantic action", async () => {
    const agentId = "context-only-agent";
    const sessionKey = "agent:channel:context-only-thread";
    setDefaultExtractorClient(createContextOnlyExtractorClient());

    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-context-old",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-ctx-old",
          messageRole: "assistant",
          messageContent: "当前结论：先按 5 月 5 日推进。",
        }),
      ],
      prePromptMessageCount: 3,
    });
    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-context-ack",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-core-ack",
          messageRole: "user",
          messageContent: "收到",
          timestamp: "2026-04-17T00:01:00.000Z",
        }),
      ],
      prePromptMessageCount: 4,
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId,
      sourceId: sessionKey,
      reason: "recall",
    });

    const store = getCanonicalStore(agentId);
    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 0,
      evidenceRecordsV2Total: 0,
      pendingProjectionSpans: 0,
    });
  });

  it("forces a synchronous drain before compaction", async () => {
    await handleGraphBeforeCompaction({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [entry({ entryId: "entry-2", timestamp: "2026-04-17T00:05:00.000Z" })],
    });

    const store = getCanonicalStore("main");
    const status = store.getStatus();
    expect(status.eventRecordsV2Total).toBeGreaterThanOrEqual(1);
    expect(status.pendingProjectionSpans).toBe(0);
    expect(
      store.findDecisionStatesByAnchor({
        anchorType: "task",
        anchorRef: "FEISHU-231",
        decisionAxisKey: "release_date",
        limit: 5,
      }),
    ).toHaveLength(1);
  });

  it("marks projection failed and keeps pending spans when extraction fails", async () => {
    const agentId = "failed-agent";
    const sessionKey = "agent:channel:failed-thread";
    setDefaultExtractorClient(createFailingExtractorClient());

    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-1",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId,
      sourceId: sessionKey,
      reason: "recall",
    });

    const store = getCanonicalStore(agentId);
    expect(store.getProjectionState(sessionKey)).toMatchObject({
      status: "failed",
    });
    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 0,
      pendingProjectionSpans: 1,
    });
  });

  it("retries the same pending span after extractor recovery", async () => {
    const agentId = "retry-agent";
    const sessionKey = "agent:channel:retry-thread";
    setDefaultExtractorClient(createFailingExtractorClient());

    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId,
      sessionId: "session-1",
      sessionKey,
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId,
      sourceId: sessionKey,
      reason: "recall",
    });

    setDefaultExtractorClient(createMockExtractorClient());

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId,
      sourceId: sessionKey,
      reason: "recall",
    });

    const store = getCanonicalStore(agentId);
    expect(store.getProjectionState(sessionKey)).toMatchObject({
      status: "clean",
      covered_until_entry_id: "entry-1",
    });
    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 2,
      pendingProjectionSpans: 0,
    });
  });
});
