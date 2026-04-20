import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { generateUlid } from "./id-v2.js";
import { closeAllCanonicalStores, getCanonicalStore, setDefaultExtractorClient } from "./index.js";
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
          events: [
            {
              actor: "Alice",
              action: "changed_status",
              object: "FEISHU-231",
              status_before: "in_progress",
              status_after: "blocked",
              occurred_at: "2026-04-20T12:10:00.000Z",
              source_ref: "#L1-L1",
            },
          ],
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

    const persisted = await store.persistSemanticBatchV2({ evidence, events: [event] });
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
      evidence: {
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
      },
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
});
