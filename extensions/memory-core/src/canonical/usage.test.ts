import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { OpenClawConfig } from "openclaw/plugin-sdk/core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { generateUlid } from "./id-v2.js";
import { closeAllCanonicalStores, getCanonicalStore } from "./index.js";
import { buildEvidenceFingerprint, buildEventFingerprint } from "./schema-v2.js";
import {
  markGraphHitsUsedFromAssistantTexts,
  markGraphHitsUsedFromMemoryGet,
  recordReturnedGraphHits,
} from "./usage.js";

function createConfig(workspaceDir: string): OpenClawConfig {
  return {
    agents: {
      list: [{ id: "main", default: true, workspace: workspaceDir }],
    },
  } as OpenClawConfig;
}

describe("canonical graph usage tracking", () => {
  let stateDir = "";
  let workspaceDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-usage-state-"));
    workspaceDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-usage-workspace-"));
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

  it("tracks returned hits and marks them used by memory_get and llm output", async () => {
    const cfg = createConfig(workspaceDir);
    const store = getCanonicalStore("main");
    const evidenceId = generateUlid();
    const occurredAt = "2026-04-15T00:00:00.000Z";
    await store.persistSemanticBatchV2({
      evidence: [{
        evidence_id: evidenceId,
        evidence_fingerprint: buildEvidenceFingerprint({
          sourcePlatform: "transcript",
          sourceKind: "transcript_span",
          sessionKey: "agent:main:thread",
          firstEntryId: "e1",
          lastEntryId: "e1",
          occurredAt,
          contentText: "task_123 blocked",
          contentJson: {},
        }),
        source_platform: "transcript",
        source_kind: "transcript_span",
        session_key: "agent:main:thread",
        message_id: null,
        chat_id: null,
        chat_type: null,
        thread_id: null,
        root_id: null,
        parent_id: null,
        first_entry_id: "e1",
        last_entry_id: "e1",
        content_text: "task_123 blocked",
        content_json: "{}",
        source_locator_json: JSON.stringify({
          source_ref: "memory/2026-04-15.md#L12-L18",
        }),
        occurred_at: occurredAt,
        created_at: Date.now(),
      }],
      events: [
        {
          event_id: generateUlid(),
          event_fingerprint: buildEventFingerprint({
            evidenceId,
            eventType: "constraint_event",
            subjectRef: "task:task_123",
            objectRef: "blocker:test",
            occurredAt,
            payloadJson: { task_ref: "task:task_123", claim: "task_123 blocked", constraint: "blocker:test" },
          }),
          evidence_id: evidenceId,
          event_type: "constraint_event",
          subject_ref: "task:task_123",
          actor_ref: "person_name:alice",
          object_ref: "blocker:test",
          related_refs_json: JSON.stringify(["person_name:alice", "blocker:test"]),
          occurred_at: occurredAt,
          payload_json: JSON.stringify({ task_ref: "task:task_123", claim: "task_123 blocked", constraint: "blocker:test" }),
          confidence: 0.9,
          extraction_version: "v-test",
          created_at: Date.now(),
        },
      ],
    });

    await recordReturnedGraphHits({
      cfg,
      agentId: "main",
      sessionKey: "agent:main:thread",
      query: "task_123",
      hits: [
        {
          type: "state",
          entity_id: "task:task_123",
          source_ref: "memory/2026-04-15.md#L12-L18",
          snippet_structured: {},
          score: 0.9,
        },
        {
          type: "event",
          entity_id: "task:task_123",
          source_ref: "memory/2026-04-15.md#L12-L18",
          snippet_structured: {},
          score: 0.8,
        },
      ],
    });
    await markGraphHitsUsedFromMemoryGet({
      cfg,
      agentId: "main",
      sessionKey: "agent:main:thread",
      path: "memory/2026-04-15.md",
      from: 12,
      lines: 7,
    });
    await markGraphHitsUsedFromAssistantTexts({
      cfg,
      agentId: "main",
      sessionKey: "agent:main:thread",
      assistantTexts: ["verified memory/2026-04-15.md#L12-L18 in the answer"],
    });

    expect(store.getStatus().metrics).toMatchObject({
      hitsReturned: 2,
      hitsUsedRaw: 4,
      hitsUsedUniqueRefs: 2,
      hitsUsed: 2,
    });
    expect(store.getRecentGraphHits("agent:main:thread")).toHaveLength(2);
  });
});
