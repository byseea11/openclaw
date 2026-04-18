import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { OpenClawConfig } from "openclaw/plugin-sdk/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetLogger, setLoggerOverride } from "../../../../src/logging.js";
import { createHookRunnerWithRegistry } from "../../../../src/plugins/hooks.test-helpers.js";
import memoryCorePlugin from "../../index.js";
import {
  resetMemoryToolMockState,
  setMemoryReadFileImpl,
  setMemorySearchImpl,
} from "../memory-tool-manager-mock.js";
import {
  createMemoryGetToolOrThrow,
  createMemorySearchToolOrThrow,
} from "../tools.test-helpers.js";
import {
  closeAllCanonicalStores,
  getCanonicalStatus,
  getCanonicalStore,
  handleGraphFlushResult,
  noteGraphUsageFromAssistantOutput,
  noteGraphUsageFromMemoryGet,
  search_graph,
} from "./index.js";

function createMemoryCoreHookRunner(cfg: OpenClawConfig) {
  const hooks: Array<{
    hookName: string;
    handler: (...args: unknown[]) => unknown;
    pluginId: string;
  }> = [];
  const api = new Proxy(
    {
      config: cfg,
      logger: {
        warn: vi.fn(),
        error: vi.fn(),
        info: vi.fn(),
        debug: vi.fn(),
      },
      on: (hookName: string, handler: (...args: unknown[]) => unknown) => {
        hooks.push({ pluginId: "memory-core", hookName, handler });
      },
      registerCli: vi.fn(),
      registerMemoryCapability: vi.fn(),
      registerMemoryEmbeddingProvider: vi.fn(),
      registerTool: vi.fn(),
    },
    {
      get(target, prop) {
        if (prop in target) {
          return target[prop as keyof typeof target];
        }
        return vi.fn();
      },
    },
  );
  memoryCorePlugin.register(api as never);
  return createHookRunnerWithRegistry(hooks);
}

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
    await fs.writeFile(logPath, "", "utf8");
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    resetLogger();
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
            status_before: "in_progress",
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
      schemaVersion: "v2",
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
    expect(logText).toContain("GRAPH_INDEX canonical.memory_search.graph_hits");
    expect(logText).toContain("[canonical] usage.used");
    expect(getCanonicalStatus({ cfg, agentId: "main" }).metrics).toMatchObject({
      hitsUsedRaw: 4,
      hitsUsedUniqueRefs: 2,
      hitsUsed: 2,
    });
  });

  it("rejects missing and overflowing flush source refs without failing flush", async () => {
    const cfg = createConfig(workspaceDir);
    const outputText = [
      "NO_REPLY",
      "```json",
      JSON.stringify({
        events: [
          {
            action: "changed_status",
            object: "task_valid",
            status_before: "open",
            status_after: "blocked",
            source_ref: "memory/2026-04-15.md#L12-L18",
          },
          {
            action: "changed_status",
            object: "task_missing",
            source_ref: "memory/2026-04-16.md#L1-L1",
          },
          {
            action: "changed_status",
            object: "task_overflow",
            source_ref: "memory/2026-04-15.md#L12-L200",
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

    const status = getCanonicalStatus({ cfg, agentId: "main" });
    expect(status).toMatchObject({
      eventsTotal: 1,
      entitiesTotal: 1,
      metrics: expect.objectContaining({
        sourceRefValidated: 1,
        sourceRefRejected: 2,
      }),
    });
    const hits = await search_graph(getCanonicalStore("main"), "task_missing task_overflow", 5);
    expect(hits).toHaveLength(0);
  });

  it("marks graph hits used through the real hook runner dispatcher", async () => {
    const cfg = createConfig(workspaceDir);
    const sessionKey = "agent:main:hook-dispatch";
    const records = [
      {
        action: "changed_status",
        object: "task_123",
        status_before: "open",
        status_after: "blocked",
        source_ref: "memory/2026-04-15.md#L12-L18",
      },
    ];
    await handleGraphFlushResult({
      cfg,
      agentId: "main",
      outputText: ["```json", JSON.stringify({ events: records }), "```"].join("\n"),
    });

    const searchTool = createMemorySearchToolOrThrow({
      config: cfg,
      agentSessionKey: sessionKey,
    });
    await searchTool.execute("hook-search", { query: "task_123" });

    const { runner } = createMemoryCoreHookRunner(cfg);
    await runner.runAfterToolCall(
      {
        toolName: "memory_get",
        params: { path: "memory/2026-04-15.md", from: 12, lines: 7 },
        runId: "run-hook",
        toolCallId: "tool-hook",
      },
      {
        toolName: "memory_get",
        agentId: "main",
        sessionKey,
        runId: "run-hook",
        toolCallId: "tool-hook",
      },
    );
    await runner.runLlmOutput(
      {
        runId: "run-hook",
        sessionId: "session-hook",
        provider: "test",
        model: "test",
        assistantTexts: ["verified memory/2026-04-15.md#L12-L18"],
        lastAssistant: { role: "assistant", content: "verified" },
      },
      {
        runId: "run-hook",
        agentId: "main",
        sessionKey,
      },
    );

    expect(getCanonicalStatus({ cfg, agentId: "main" }).metrics).toMatchObject({
      hitsUsedRaw: 4,
      hitsUsedUniqueRefs: 2,
      hitsUsed: 2,
    });
  });
});
