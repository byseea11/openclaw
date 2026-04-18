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

  it("writes graph trace JSONL for dirty then drain", async () => {
    const tracePath = path.join(stateDir, "logs", "graph-index-trace.jsonl");
    const graphCfg = cfg(tracePath);

    await handleGraphAfterTurn({
      cfg: graphCfg,
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [entry()],
      prePromptMessageCount: 3,
    });
    await drainPendingGraphUpdates({
      cfg: graphCfg,
      agentId: "main",
      sourceId: "agent:channel:thread",
      reason: "recall",
    });

    const traceLines = (await fs.readFile(tracePath, "utf8")).trim().split("\n");
    const traceEvents = traceLines.map(
      (line) => JSON.parse(line) as { stage?: string; tag?: string },
    );
    expect(traceEvents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ tag: "GRAPH_INDEX", stage: "after_turn_mark_dirty" }),
        expect.objectContaining({ tag: "GRAPH_INDEX", stage: "drain_started" }),
        expect.objectContaining({ tag: "GRAPH_INDEX", stage: "events_persisted" }),
        expect.objectContaining({ tag: "GRAPH_INDEX", stage: "cursor_advanced" }),
      ]),
    );
  });

  it("updates latest owner from a transcript handoff note", async () => {
    await handleGraphAfterTurn({
      cfg: cfg(),
      agentId: "main",
      sessionId: "session-1",
      sessionKey: "agent:channel:thread",
      sessionFile: "/tmp/session.jsonl",
      entries: [
        entry({
          entryId: "entry-bob",
          messageContent: [
            "**FEISHU-231 飞书机器人权限问题**",
            "- **状态**: blocked（阻塞）",
            "- **跟进人**: Bob（从 Alice 接手）",
          ].join("\n"),
        }),
      ],
      prePromptMessageCount: 3,
    });

    await drainPendingGraphUpdates({
      cfg: cfg(),
      agentId: "main",
      sourceId: "agent:channel:thread",
      reason: "recall",
    });

    const store = getCanonicalStore("main");
    const exported = await store.exportData();
    expect(exported.events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          action: "assigned_owner",
          actor: "Bob",
          object: "FEISHU-231",
        }),
      ]),
    );
    expect(exported.states).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          latest_owner: "Bob",
        }),
      ]),
    );
  });
});
