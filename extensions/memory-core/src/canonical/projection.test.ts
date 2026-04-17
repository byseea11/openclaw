import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type {
  MemoryTranscriptSpanEntry,
  OpenClawConfig,
} from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  drainPendingGraphUpdates,
  handleGraphAfterTurn,
  handleGraphBeforeCompaction,
} from "./projection.js";
import { closeAllCanonicalStores, getCanonicalStore } from "./store.js";

function cfg(): OpenClawConfig {
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
    messageContent: "remember task_123 status: pending",
    toolName: null,
    toolResult: null,
    timestamp: "2026-04-17T00:00:00.000Z",
    ...overrides,
  };
}

describe("canonical graph transcript projection", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-projection-"));
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
  });

  it("marks afterTurn spans dirty without per-turn event extraction", async () => {
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
      pendingProjectionSpans: 1,
    });
    expect(store.listPendingProjectionSummaries("agent:channel:thread")).toMatchObject([
      {
        pending_spans: 1,
        pending_entries: 1,
        strong_event: false,
      },
    ]);
  });

  it("deduplicates repeated afterTurn inbox writes", async () => {
    const params = {
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    };

    await handleGraphAfterTurn(params);
    await handleGraphAfterTurn(params);

    const store = getCanonicalStore("main");
    expect(store.getStatus().pendingProjectionSpans).toBe(1);
  });

  it("drains dirty spans in a batch on recall", async () => {
    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    });

    await expect(
      drainPendingGraphUpdates({
        cfg: cfg(),
        agentId: "main",
        sourceId: "agent:channel:thread",
        reason: "recall",
      }),
    ).resolves.toMatchObject({ drainedSources: 1, parsedEvents: 1, persistedEvents: 1 });

    const store = getCanonicalStore("main");
    expect(store.getStatus()).toMatchObject({
      eventsTotal: 1,
      pendingProjectionSpans: 0,
    });
    await expect(store.exportData()).resolves.toMatchObject({
      events: [
        expect.objectContaining({
          source_type: "transcript",
          session_id: "agent:channel:thread",
          covered_until_entry_id: "entry-1",
        }),
      ],
    });
  });

  it("forces a synchronous drain before compaction", async () => {
    await handleGraphBeforeCompaction({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-2",
          messageContent: "task_456 is blocked",
        }),
      ],
    });

    const store = getCanonicalStore("main");
    expect(store.getStatus()).toMatchObject({
      eventsTotal: 1,
      pendingProjectionSpans: 0,
    });
    await expect(store.searchEvents("task_456", 5)).resolves.toEqual([
      expect.objectContaining({
        source_type: "transcript",
        session_id: "agent:channel:thread",
        covered_until_entry_id: "entry-2",
      }),
    ]);
  });
});
