import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { generateUlid } from "./id-v2.js";
import {
  canonicalizeV2,
  closeAllCanonicalStores,
  getCanonicalStore,
  setDefaultExtractorClient,
} from "./index.js";
import { searchGraphV2 } from "./query-v2.js";
import { buildEvidenceFingerprint, buildEventFingerprint } from "./schema-v2.js";

describe("canonical graph v2", () => {
  let workspaceDir = "";
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    workspaceDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-v2-workspace-"));
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-v2-state-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    await fs.mkdir(path.join(workspaceDir, "memory"), { recursive: true });
    await fs.writeFile(
      path.join(workspaceDir, "memory", "2026-04-15.md"),
      "line 12: FEISHU-231 is blocked by AP-778\nline 13: owner Alice\n",
      "utf8",
    );
    setDefaultExtractorClient({
      async extractGraphEvents() {
        return JSON.stringify({
          should_extract: false,
          topic_ref: null,
          topic_anchors_json: null,
          decision_axis_key: null,
          decision_axis_text: null,
          decision_axis_instance_id: null,
          claims: [],
        });
      },
    });
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    setDefaultExtractorClient(null);
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(workspaceDir, { recursive: true, force: true });
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("persists semantic v2 records directly", async () => {
    const store = getCanonicalStore("main");
    const evidenceId = generateUlid();
    const occurredAt = "2026-04-20T12:00:00.000Z";
    const evidence = {
      evidence_id: evidenceId,
      evidence_fingerprint: buildEvidenceFingerprint({
        sourcePlatform: "transcript",
        sourceKind: "transcript_span",
        sessionKey: "agent:channel:thread",
        firstEntryId: "e1",
        lastEntryId: "e1",
        occurredAt,
        contentText: "FEISHU-231 blocked by AP-778",
        contentJson: {},
      }),
      source_platform: "transcript" as const,
      source_kind: "transcript_span" as const,
      session_key: "agent:channel:thread",
      message_id: null,
      chat_id: null,
      chat_type: null,
      thread_id: null,
      root_id: null,
      parent_id: null,
      first_entry_id: "e1",
      last_entry_id: "e1",
      content_text: "FEISHU-231 blocked by AP-778",
      content_json: "{}",
      source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L1-L1" }),
      occurred_at: occurredAt,
      created_at: Date.now(),
    };
    const event = {
      event_id: generateUlid(),
      event_fingerprint: buildEventFingerprint({
        evidenceId,
        eventType: "blocked",
        subjectRef: "task:FEISHU-231",
        objectRef: "approval:AP-778",
        occurredAt,
        payloadJson: { blocker_ref: "approval:AP-778" },
      }),
      evidence_id: evidenceId,
      event_type: "blocked" as const,
      subject_ref: "task:FEISHU-231",
      actor_ref: "person_name:alice",
      object_ref: "approval:AP-778",
      related_refs_json: JSON.stringify(["approval:AP-778", "person_name:alice"]),
      occurred_at: occurredAt,
      payload_json: JSON.stringify({ blocker_ref: "approval:AP-778" }),
      confidence: 0.9,
      extraction_version: "test",
      created_at: Date.now(),
    };

    const persisted = await store.persistSemanticBatchV2({ evidence: [evidence], events: [event] });
    expect(persisted.events).toHaveLength(1);
    expect(store.getWorkflowStateV2("task:FEISHU-231")).toMatchObject({
      current_stage: "blocked",
      current_blocker_ref: "approval:AP-778",
    });
    const result = await searchGraphV2(store, "FEISHU-231 why blocked", 5);
    expect(result.hits.length).toBeGreaterThan(0);
  });

  it("supports state and relation queries from v2 tables", async () => {
    const store = getCanonicalStore("main");
    const evidenceId = generateUlid();
    const occurredAt = "2026-04-20T12:05:00.000Z";
    await store.persistSemanticBatchV2({
      evidence: [{
        evidence_id: evidenceId,
        evidence_fingerprint: buildEvidenceFingerprint({
          sourcePlatform: "transcript",
          sourceKind: "transcript_span",
          sessionKey: "agent:channel:thread",
          firstEntryId: "e2",
          lastEntryId: "e2",
          occurredAt,
          contentText: "FEISHU-231 owner changed to Bob",
          contentJson: {},
        }),
        source_platform: "transcript",
        source_kind: "transcript_span",
        session_key: "agent:channel:thread",
        message_id: null,
        chat_id: null,
        chat_type: null,
        thread_id: null,
        root_id: null,
        parent_id: null,
        first_entry_id: "e2",
        last_entry_id: "e2",
        content_text: "FEISHU-231 owner changed to Bob",
        content_json: "{}",
        source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L2-L2" }),
        occurred_at: occurredAt,
        created_at: Date.now(),
      }],
      events: [
        {
          event_id: generateUlid(),
          event_fingerprint: buildEventFingerprint({
            evidenceId,
            eventType: "owner_changed",
            subjectRef: "task:FEISHU-231",
            objectRef: "person_name:bob",
            occurredAt,
            payloadJson: { new_owner_ref: "person_name:bob" },
          }),
          evidence_id: evidenceId,
          event_type: "owner_changed",
          subject_ref: "task:FEISHU-231",
          actor_ref: "person_name:bob",
          object_ref: "person_name:bob",
          related_refs_json: JSON.stringify(["person_name:bob"]),
          occurred_at: occurredAt,
          payload_json: JSON.stringify({ new_owner_ref: "person_name:bob" }),
          confidence: 0.91,
          extraction_version: "test",
          created_at: Date.now(),
        },
      ],
    });

    expect(store.getStatus()).toMatchObject({
      eventRecordsV2Total: 1,
      workflowStatesV2Total: 1,
      graphEdgesV2Total: 1,
    });
    const stateResult = await searchGraphV2(store, "FEISHU-231 state", 5);
    expect(stateResult.hits).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "state",
        }),
      ]),
    );
    const relationResult = await searchGraphV2(store, "FEISHU-231 关系", 5);
    expect(relationResult.hits).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "edge",
        }),
      ]),
    );
  });

  it("returns decision_card hits for decision memory queries", async () => {
    const store = getCanonicalStore("main");
    const evidenceId1 = generateUlid();
    const evidenceId2 = generateUlid();
    const occurredAt = "2026-04-20T12:10:00.000Z";
    await store.persistSemanticBatchV2({
      evidence: [
        {
          evidence_id: evidenceId1,
          evidence_fingerprint: buildEvidenceFingerprint({
            sourcePlatform: "transcript",
            sourceKind: "transcript_span",
            sessionKey: "agent:channel:thread",
            firstEntryId: "e3",
            lastEntryId: "e3",
            occurredAt,
            contentText: "5 月 5 日不是已确认发布日期",
            contentJson: {},
          }),
          source_platform: "transcript",
          source_kind: "transcript_span",
          session_key: "agent:channel:thread",
          message_id: null,
          chat_id: null,
          chat_type: null,
          thread_id: null,
          root_id: null,
          parent_id: null,
          first_entry_id: "e3",
          last_entry_id: "e3",
          content_text: "5 月 5 日不是已确认发布日期",
          content_json: "{}",
          source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L3-L3" }),
          occurred_at: occurredAt,
          created_at: Date.now(),
        },
        {
          evidence_id: evidenceId2,
          evidence_fingerprint: buildEvidenceFingerprint({
            sourcePlatform: "transcript",
            sourceKind: "transcript_span",
            sessionKey: "agent:channel:thread",
            firstEntryId: "e4",
            lastEntryId: "e4",
            occurredAt,
            contentText: "迁移窗口还没锁定",
            contentJson: {},
          }),
          source_platform: "transcript",
          source_kind: "transcript_span",
          session_key: "agent:channel:thread",
          message_id: null,
          chat_id: null,
          chat_type: null,
          thread_id: null,
          root_id: null,
          parent_id: null,
          first_entry_id: "e4",
          last_entry_id: "e4",
          content_text: "迁移窗口还没锁定",
          content_json: "{}",
          source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L4-L4" }),
          occurred_at: occurredAt,
          created_at: Date.now(),
        },
      ],
      events: [
        {
          event_id: generateUlid(),
          event_fingerprint: buildEventFingerprint({
            evidenceId: evidenceId1,
            eventType: "decision_claim_recorded",
            subjectRef: "topic:task:FEISHU-231:release_date",
            objectRef: "date:2026-05-05",
            occurredAt,
            payloadJson: {
              topic_ref: "topic:task:FEISHU-231:release_date",
              topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
              decision_axis_key: "release_date",
              decision_axis_text: "Whether the release date is confirmed",
              decision_axis_instance_id: null,
              claim_field: "time_point",
              claim_text: "5 月 5 日不是已确认发布日期",
              claim_value_json: { date: "2026-05-05", role: "target_date" },
              evidence_quote: "5 月 5 日不是已确认发布日期",
              confidence: 0.92,
            },
          }),
          evidence_id: evidenceId1,
          event_type: "decision_claim_recorded",
          subject_ref: "topic:task:FEISHU-231:release_date",
          actor_ref: null,
          object_ref: "date:2026-05-05",
          related_refs_json: JSON.stringify(["task:FEISHU-231", "date:2026-05-05"]),
          occurred_at: occurredAt,
          payload_json: JSON.stringify({
            topic_ref: "topic:task:FEISHU-231:release_date",
            topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
            decision_axis_key: "release_date",
            decision_axis_text: "Whether the release date is confirmed",
            decision_axis_instance_id: null,
            claim_field: "time_point",
            claim_text: "5 月 5 日不是已确认发布日期",
            claim_value_json: { date: "2026-05-05", role: "target_date" },
            evidence_quote: "5 月 5 日不是已确认发布日期",
            confidence: 0.92,
          }),
          confidence: 0.92,
          extraction_version: "test",
          created_at: Date.now(),
        },
        {
          event_id: generateUlid(),
          event_fingerprint: buildEventFingerprint({
            evidenceId: evidenceId2,
            eventType: "decision_claim_recorded",
            subjectRef: "topic:task:FEISHU-231:release_date",
            objectRef: null,
            occurredAt,
            payloadJson: {
              topic_ref: "topic:task:FEISHU-231:release_date",
              topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
              decision_axis_key: "release_date",
              decision_axis_text: "Whether the release date is confirmed",
              decision_axis_instance_id: null,
              claim_field: "rationale",
              claim_text: "迁移窗口还没锁定",
              claim_value_json: { reason_type: "risk_or_blocker" },
              evidence_quote: "迁移窗口还没锁定",
              confidence: 0.88,
            },
          }),
          evidence_id: evidenceId2,
          event_type: "decision_claim_recorded",
          subject_ref: "topic:task:FEISHU-231:release_date",
          actor_ref: null,
          object_ref: null,
          related_refs_json: JSON.stringify(["task:FEISHU-231"]),
          occurred_at: occurredAt,
          payload_json: JSON.stringify({
            topic_ref: "topic:task:FEISHU-231:release_date",
            topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
            decision_axis_key: "release_date",
            decision_axis_text: "Whether the release date is confirmed",
            decision_axis_instance_id: null,
            claim_field: "rationale",
            claim_text: "迁移窗口还没锁定",
            claim_value_json: { reason_type: "risk_or_blocker" },
            evidence_quote: "迁移窗口还没锁定",
            confidence: 0.88,
          }),
          confidence: 0.88,
          extraction_version: "test",
          created_at: Date.now(),
        },
      ],
    });

    const result = await searchGraphV2(store, "FEISHU-231 为什么 5 月 5 日不是确认日期？", 5);
    expect(result.queryClass).toBe("decision_card");
    expect(result.hits).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "state",
          snippet_structured: expect.objectContaining({
            query_kind: "decision_card",
            decision_axis_key: "release_date",
            current_conclusion: null,
            rationales: expect.arrayContaining(["迁移窗口还没锁定"]),
            time_point_claims: expect.arrayContaining(["5 月 5 日不是已确认发布日期"]),
          }),
        }),
      ]),
    );
  });

  it("resolves evidence_quote to a concrete core entry and keeps supporting context metadata", () => {
    const result = canonicalizeV2({
      sourceId: "agent:channel:thread",
      sourceRef: "transcripts/test.txt#L1-L3",
      text: [
        "[entry-ctx-1] user: FEISHU-231 目标发布时间暂定 5 月 5 日。",
        "[entry-core] assistant: 这个日期先别说死。",
      ].join("\n"),
      entries: [
        {
          entryId: "entry-ctx-1",
          parentId: null,
          entryType: "message",
          messageRole: "user",
          messageContent: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:00:00.000Z",
        },
        {
          entryId: "entry-core",
          parentId: "entry-ctx-1",
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      coreEntries: [
        {
          entryId: "entry-core",
          parentId: "entry-ctx-1",
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      contextEntries: [
        {
          entryId: "entry-ctx-1",
          parentId: null,
          entryType: "message",
          messageRole: "user",
          messageContent: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:00:00.000Z",
        },
      ],
      coreText: "[entry-core] assistant: 这个日期先别说死。",
      contextText: "[entry-ctx-1] user: FEISHU-231 目标发布时间暂定 5 月 5 日。",
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
              date: "2026-05-05",
              role: "target_date",
              modality: "not_confirmed",
              core_entry_id: "entry-core",
              supporting_context_quotes: [
                {
                  quote: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
                  entry_id: "entry-ctx-1",
                  source: "context",
                },
              ],
            },
            evidence_quote: "这个日期先别说死",
            confidence: 0.92,
          },
        ],
      },
    });

    expect(result.events).toHaveLength(1);
    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0]).toMatchObject({
      first_entry_id: "entry-core",
      last_entry_id: "entry-core",
      content_text: "这个日期先别说死",
    });
    expect(JSON.parse(result.evidence[0].content_json)).toMatchObject({
      resolved_core_entry_id: "entry-core",
      supporting_context_entry_ids: ["entry-ctx-1"],
    });
    expect(JSON.parse(result.events[0].payload_json)).toMatchObject({
      claim_value_json: expect.objectContaining({
        core_entry_id: "entry-core",
        supporting_context_quotes: [
          expect.objectContaining({
            quote: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
            entry_id: "entry-ctx-1",
            source: "context",
          }),
        ],
      }),
    });
  });

  it("rejects claims when the core quote has no new semantic action", () => {
    const result = canonicalizeV2({
      sourceId: "agent:channel:thread",
      sourceRef: "transcripts/test.txt#L1-L2",
      text: "[entry-core-ack] user: 收到",
      entries: [
        {
          entryId: "entry-core-ack",
          parentId: null,
          entryType: "message",
          messageRole: "user",
          messageContent: "收到",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      coreEntries: [
        {
          entryId: "entry-core-ack",
          parentId: null,
          entryType: "message",
          messageRole: "user",
          messageContent: "收到",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      contextEntries: [
        {
          entryId: "entry-ctx-old",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "当前结论：先按 5 月 5 日推进。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:00:00.000Z",
        },
      ],
      coreText: "[entry-core-ack] user: 收到",
      contextText: "[entry-ctx-old] assistant: 当前结论：先按 5 月 5 日推进。",
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
            claim_text: "当前结论：先按 5 月 5 日推进。",
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
            confidence: 0.92,
          },
        ],
      },
    });

    expect(result.events).toHaveLength(0);
    expect(result.evidence).toHaveLength(0);
  });

  it("drops unresolved supporting context quotes and rejects the claim if support disappears", () => {
    const result = canonicalizeV2({
      sourceId: "agent:channel:thread",
      sourceRef: "transcripts/test.txt#L1-L2",
      text: "[entry-core] assistant: 这个日期先别说死。",
      entries: [
        {
          entryId: "entry-core",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      coreEntries: [
        {
          entryId: "entry-core",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      contextEntries: [],
      coreText: "[entry-core] assistant: 这个日期先别说死。",
      contextText: "",
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
              core_entry_id: "entry-core",
              supporting_context_quotes: [
                {
                  quote: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
                  entry_id: "entry-ctx-missing",
                  source: "context",
                },
              ],
            },
            evidence_quote: "这个日期先别说死",
            confidence: 0.92,
          },
        ],
      },
    });

    expect(result.events).toHaveLength(0);
    expect(result.evidence).toHaveLength(0);
  });

  it("prefers extractor core_entry_id when the evidence quote matches multiple core entries", () => {
    const result = canonicalizeV2({
      sourceId: "agent:channel:thread",
      sourceRef: "transcripts/test.txt#L1-L3",
      text: [
        "[entry-core-1] assistant: 这个日期先别说死。",
        "[entry-core-2] assistant: 这个日期先别说死。",
      ].join("\n"),
      entries: [
        {
          entryId: "entry-core-1",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:00:00.000Z",
        },
        {
          entryId: "entry-core-2",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      coreEntries: [
        {
          entryId: "entry-core-1",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:00:00.000Z",
        },
        {
          entryId: "entry-core-2",
          parentId: null,
          entryType: "message",
          messageRole: "assistant",
          messageContent: "这个日期先别说死。",
          toolName: null,
          toolResult: null,
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
      contextEntries: [],
      coreText: [
        "[entry-core-1] assistant: 这个日期先别说死。",
        "[entry-core-2] assistant: 这个日期先别说死。",
      ].join("\n"),
      contextText: "",
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
            claim_text: "这个日期先别说死。",
            claim_value_json: {
              core_entry_id: "entry-core-1",
            },
            evidence_quote: "这个日期先别说死",
            confidence: 0.92,
          },
        ],
      },
    });

    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0].first_entry_id).toBe("entry-core-1");
    expect(JSON.parse(result.evidence[0].content_json)).toMatchObject({
      resolved_core_entry_id: "entry-core-1",
    });
  });
});
