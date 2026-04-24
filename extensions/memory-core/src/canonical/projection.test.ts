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
    messageContent: "FEISHU-231 blocked by AP-778",
    toolName: null,
    toolResult: null,
    timestamp: "2026-04-17T00:00:00.000Z",
    ...overrides,
  };
}

function createMockExtractorClient(): CanonicalExtractorClient {
  return {
    async extractGraphEvents(params) {
      if (params.prompt.includes("AP-778")) {
        return JSON.stringify({
          events: [
            {
              actor: "Bob",
              action: "changed_status",
              object: "FEISHU-231",
              status_after: "blocked",
              occurred_at: "2026-04-17T00:00:00.000Z",
              source_ref: "#L1-L1",
            },
          ],
        });
      }
      return JSON.stringify({ events: [] });
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

describe("canonical graph transcript projection v2", () => {
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
      eventsTotal: 0,
      evidenceRecordsV2Total: 0,
      pendingProjectionSpans: 1,
    });
  });

  it("drains transcript spans into v2 semantic tables", async () => {
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
      eventRecordsV2Total: 1,
      workflowStatesV2Total: 1,
      graphEntitiesV2Total: 4,
      graphEdgesV2Total: 1,
      pendingProjectionSpans: 0,
    });
    expect(store.getWorkflowStateV2("task:FEISHU-231")).toMatchObject({
      current_stage: "blocked",
      current_blocker_ref: "approval:AP-778",
    });
    await expect(store.exportData()).resolves.toMatchObject({
      evidence: [expect.objectContaining({ source_platform: "transcript" })],
      events: [expect.objectContaining({ event_type: "blocked", subject_ref: "task:FEISHU-231" })],
      workflowStates: [expect.objectContaining({ task_ref: "task:FEISHU-231" })],
    });
  });

  it("forces a synchronous v2 drain before compaction", async () => {
    await handleGraphBeforeCompaction({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-2",
          messageContent: "FEISHU-231 blocked by AP-778",
          timestamp: "2026-04-17T00:05:00.000Z",
        }),
      ],
    });

    const store = getCanonicalStore("main");
    const status = store.getStatus();
    expect(status.eventRecordsV2Total).toBeGreaterThanOrEqual(1);
    expect(status.pendingProjectionSpans).toBe(0);
    expect(store.getWorkflowStateV2("task:FEISHU-231")).toMatchObject({
      current_stage: "blocked",
    });
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
      eventRecordsV2Total: 1,
      pendingProjectionSpans: 0,
    });
  });
});
