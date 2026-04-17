import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { OpenClawConfig } from "openclaw/plugin-sdk/core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  resetMemoryToolMockState,
  setMemoryReadFileImpl,
  setMemorySearchImpl,
} from "../memory-tool-manager-mock.js";
import { createMemoryGetToolOrThrow, createMemorySearchToolOrThrow } from "../tools.test-helpers.js";
import { resetLogger, setLoggerOverride } from "../../../../src/logging.js";
import {
  closeAllCanonicalStores,
  getCanonicalStatus,
  getCanonicalStore,
  handleGraphFlushResult,
  noteGraphUsageFromAssistantOutput,
  noteGraphUsageFromMemoryGet,
  search_graph,
} from "./index.js";

function createConfig(workspaceDir: string): OpenClawConfig {
  return {
    agents: {
      list: [{ id: "main", default: true, workspace: workspaceDir }],
    },
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

describe("canonical graph integration", () => {
  let workspaceDir = "";
  let stateDir = "";
  let logPath = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    workspaceDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-int-workspace-"));
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-int-state-"));
    logPath = path.join(stateDir, "graph-integration.log");
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    setLoggerOverride({ level: "info", file: logPath });
    resetMemoryToolMockState({ searchImpl: async () => [] });
    setMemorySearchImpl(async () => []);
    setMemoryReadFileImpl(async (params) => {
      const filePath = path.join(workspaceDir, params.relPath);
      const allLines = (await fs.readFile(filePath, "utf8")).split(/\r?\n/);
      const from = Math.max(1, params.from ?? 1);
      const lines = Math.max(1, params.lines ?? allLines.length);
      return {
        path: params.relPath,
        text: allLines.slice(from - 1, from - 1 + lines).join("\n"),
      };
    });

    const memoryDir = path.join(workspaceDir, "memory");
    await fs.mkdir(memoryDir, { recursive: true });
    const lines = Array.from({ length: 20 }, (_, index) => `line ${index + 1}: filler`);
    lines[11] = "line 12: task_123 is blocked by Alice";
    lines[12] = "line 13: owner: Alice";
    lines[13] = "line 14: status: blocked";
    lines[14] = "line 15: Alice decided to ship task_123";
    lines[15] = "line 16: supporting note";
    lines[16] = "line 17: more context";
    lines[17] = "line 18: end of source span.";
    await fs.writeFile(path.join(memoryDir, "2026-04-15.md"), `${lines.join("\n")}\n`, "utf8");
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    resetLogger();
    setLoggerOverride(null);
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(workspaceDir, { recursive: true, force: true });
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("proves the full flush -> store -> search -> memory_get path in logs", async () => {
    const cfg = createConfig(workspaceDir);
    const sessionKey = "agent:main:integration";
    const outputText = [
      "NO_REPLY",
      "```json",
      JSON.stringify({
        events: [
          {
            actor: "Alice",
            action: "changed_status",
            object: "task_123",
            status_after: "blocked",
            occurred_at: "2026-04-15",
            source_ref: "memory/2026-04-15.md#L12-L18",
          },
        ],
      }),
      "```",
    ].join("\n");

    await expect(
      handleGraphFlushResult({
        cfg,
        agentId: "main",
        outputText,
      }),
    ).resolves.toMatchObject({ parsedEvents: 1, persistedEvents: 1 });

    expect(getCanonicalStatus({ cfg, agentId: "main" })).toMatchObject({
      eventsTotal: 1,
      entitiesTotal: 1,
      extractorVersion: "v0-2026.04",
    });

    const store = getCanonicalStore("main");
    const directHits = await search_graph(store, "task_123", 5);
    expect(directHits.length).toBeGreaterThan(0);

    const searchTool = createMemorySearchToolOrThrow({
      config: cfg,
      agentSessionKey: sessionKey,
    });
    const searchResult = await searchTool.execute("graph", { query: "task_123" });
    const details = searchResult.details as {
      results: Array<{
        corpus?: string;
        path: string;
        startLine: number;
        endLine: number;
        snippet: string;
      }>;
      debug?: { graph?: { hits: number; renderedHits: number } };
    };
    const graphHit = details.results.find((result) => result.corpus === "graph");
    expect(graphHit).toMatchObject({
      corpus: "graph",
      path: "memory/2026-04-15.md",
      startLine: 12,
      endLine: 18,
    });
    expect(graphHit?.snippet).toMatch(/\[Graph (state|event)\]/);
    expect(details.debug?.graph?.hits).toBeGreaterThan(0);

    const getTool = createMemoryGetToolOrThrow({
      config: cfg,
      agentSessionKey: sessionKey,
    });
    const memoryGetResult = await getTool.execute("graph-get", {
      path: graphHit?.path,
      from: graphHit?.startLine,
      lines: graphHit ? graphHit.endLine - graphHit.startLine + 1 : undefined,
    });
    const readDetails = memoryGetResult.details as { text: string; path: string };
    expect(readDetails.path).toBe("memory/2026-04-15.md");
    expect(readDetails.text).toContain("line 12: task_123 is blocked by Alice");
    expect(readDetails.text).toContain("line 18: end of source span.");

    await noteGraphUsageFromMemoryGet({
      cfg,
      agentId: "main",
      sessionKey,
      path: graphHit?.path ?? "memory/2026-04-15.md",
      from: graphHit?.startLine,
      lines: graphHit ? graphHit.endLine - graphHit.startLine + 1 : undefined,
    });
    await noteGraphUsageFromAssistantOutput({
      cfg,
      agentId: "main",
      sessionKey,
      assistantTexts: ["citing memory/2026-04-15.md#L12-L18"],
    });

    const logText = await fs.readFile(logPath, "utf8");
    expect(logText).toContain("canonical.flush.parsed");
    expect(logText).toContain("canonical.store.upsert_events");
    expect(logText).toContain("canonical.reduce");
    expect(logText).toContain("canonical.search");
    expect(logText).toContain("canonical.memory_search.graph_hits");
    expect(logText).toContain("canonical.usage.used");
  });
});
