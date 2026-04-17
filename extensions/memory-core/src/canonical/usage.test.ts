import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { OpenClawConfig } from "openclaw/plugin-sdk/core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { canonicalize, closeAllCanonicalStores, getCanonicalStore } from "./index.js";
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
    const records = canonicalize(
      [
        {
          actor: "Alice",
          action: "changed_status",
          object: "task_123",
          status_after: "blocked",
          occurred_at: "2026-04-15",
          source_ref: "memory/2026-04-15.md#L12-L18",
        },
      ],
      "v-test",
    );
    await store.upsertEvents(records);
    await store.refreshEntityStates(records);

    await recordReturnedGraphHits({
      cfg,
      agentId: "main",
      sessionKey: "agent:main:thread",
      query: "task_123",
      hits: [
        {
          type: "state",
          entity_id: records[0]?.entity_id ?? "ent_task",
          source_ref: "memory/2026-04-15.md#L12-L18",
          snippet_structured: {},
          score: 0.9,
        },
        {
          type: "event",
          entity_id: records[0]?.entity_id ?? "ent_task",
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
