import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { generateUlid } from "./id-v2.js";
import { closeAllCanonicalStores, getCanonicalStore } from "./index.js";
import { searchGraphV2 } from "./query-v2.js";
import { buildEvidenceFingerprint, buildEventFingerprint } from "./schema-v2.js";

describe("feishu task wiki", () => {
  let stateDir = "";
  let workspaceDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-wiki-state-"));
    workspaceDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-task-wiki-workspace-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(stateDir, { recursive: true, force: true });
    await fs.rm(workspaceDir, { recursive: true, force: true });
  });

  it("persists typed task events and renders a task memory card", async () => {
    const store = getCanonicalStore("main");
    const occurredAt = "2026-05-01T10:00:00.000Z";
    const evidenceId1 = generateUlid();
    const evidenceId2 = generateUlid();

    await store.persistSemanticBatchV2({
      evidence: [
        {
          evidence_id: evidenceId1,
          evidence_fingerprint: buildEvidenceFingerprint({
            sourcePlatform: "transcript",
            sourceKind: "transcript_span",
            sessionKey: "agent:channel:thread",
            firstEntryId: "e1",
            lastEntryId: "e1",
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
          first_entry_id: "e1",
          last_entry_id: "e1",
          content_text: "5 月 5 日不是已确认发布日期",
          content_json: "{}",
          source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L1-L1" }),
          occurred_at: occurredAt,
          created_at: Date.now(),
        },
        {
          evidence_id: evidenceId2,
          evidence_fingerprint: buildEvidenceFingerprint({
            sourcePlatform: "transcript",
            sourceKind: "transcript_span",
            sessionKey: "agent:channel:thread",
            firstEntryId: "e2",
            lastEntryId: "e2",
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
          first_entry_id: "e2",
          last_entry_id: "e2",
          content_text: "迁移窗口还没锁定",
          content_json: "{}",
          source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L2-L2" }),
          occurred_at: occurredAt,
          created_at: Date.now(),
        },
      ],
      events: [
        {
          event_id: generateUlid(),
          event_fingerprint: buildEventFingerprint({
            evidenceId: evidenceId1,
            eventType: "time_event",
            subjectRef: "task:FEISHU-231",
            objectRef: "date:2026-05-05",
            occurredAt,
            payloadJson: {
              task_ref: "task:FEISHU-231",
              topic_ref: "topic:task:FEISHU-231:release_date",
              claim: "5 月 5 日不是已确认发布日期",
              claim_value: { date: "2026-05-05", role: "target_date" },
              evidence_quote: "5 月 5 日不是已确认发布日期",
            },
          }),
          evidence_id: evidenceId1,
          event_type: "time_event",
          subject_ref: "task:FEISHU-231",
          actor_ref: null,
          object_ref: "date:2026-05-05",
          related_refs_json: JSON.stringify(["date:2026-05-05"]),
          occurred_at: occurredAt,
          payload_json: JSON.stringify({
            task_ref: "task:FEISHU-231",
            topic_ref: "topic:task:FEISHU-231:release_date",
            claim: "5 月 5 日不是已确认发布日期",
            claim_value: { date: "2026-05-05", role: "target_date" },
            evidence_quote: "5 月 5 日不是已确认发布日期",
          }),
          confidence: 0.92,
          extraction_version: "test",
          created_at: Date.now(),
        },
        {
          event_id: generateUlid(),
          event_fingerprint: buildEventFingerprint({
            evidenceId: evidenceId2,
            eventType: "rationale_event",
            subjectRef: "task:FEISHU-231",
            objectRef: null,
            occurredAt,
            payloadJson: {
              task_ref: "task:FEISHU-231",
              topic_ref: "topic:task:FEISHU-231:release_date",
              claim: "迁移窗口还没锁定",
              reason: "迁移窗口还没锁定",
              evidence_quote: "迁移窗口还没锁定",
            },
          }),
          evidence_id: evidenceId2,
          event_type: "rationale_event",
          subject_ref: "task:FEISHU-231",
          actor_ref: null,
          object_ref: null,
          related_refs_json: JSON.stringify([]),
          occurred_at: occurredAt,
          payload_json: JSON.stringify({
            task_ref: "task:FEISHU-231",
            topic_ref: "topic:task:FEISHU-231:release_date",
            claim: "迁移窗口还没锁定",
            reason: "迁移窗口还没锁定",
            evidence_quote: "迁移窗口还没锁定",
          }),
          confidence: 0.88,
          extraction_version: "test",
          created_at: Date.now(),
        },
      ],
    });

    const taskState = store.getTaskCurrentStateV2("task:FEISHU-231");
    expect(taskState).toMatchObject({
      task_ref: "task:FEISHU-231",
      primary_topic_ref: "topic:task:FEISHU-231:release_date",
    });

    const result = await searchGraphV2(store, "FEISHU-231 为什么 5 月 5 日不是确认日期？", 5);
    expect(result.queryClass).toBe("task_memory_card");
    expect(result.hits).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "state",
          snippet_structured: expect.objectContaining({
            query_kind: "task_memory_card",
            task_ref: "task:FEISHU-231",
            rationales: expect.arrayContaining(["迁移窗口还没锁定"]),
            time_point_claims: expect.arrayContaining(["5 月 5 日不是已确认发布日期"]),
          }),
        }),
      ]),
    );
  });
});
