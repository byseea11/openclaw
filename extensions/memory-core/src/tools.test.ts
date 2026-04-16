import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { canonicalize, closeAllCanonicalStores, getCanonicalStore } from "./canonical/index.js";
import {
  resetMemoryToolMockState,
  setMemoryBackend,
  setMemorySearchImpl,
} from "./memory-tool-manager-mock.js";
import {
  createMemorySearchToolOrThrow,
  expectUnavailableMemorySearchDetails,
} from "./tools.test-helpers.js";

describe("memory_search unavailable payloads", () => {
  beforeEach(() => {
    resetMemoryToolMockState({ searchImpl: async () => [] });
  });

  it("returns explicit unavailable metadata for quota failures", async () => {
    setMemorySearchImpl(async () => {
      throw new Error("openai embeddings failed: 429 insufficient_quota");
    });

    const tool = createMemorySearchToolOrThrow();
    const result = await tool.execute("quota", { query: "hello" });
    expectUnavailableMemorySearchDetails(result.details, {
      error: "openai embeddings failed: 429 insufficient_quota",
      warning: "Memory search is unavailable because the embedding provider quota is exhausted.",
      action: "Top up or switch embedding provider, then retry memory_search.",
    });
  });

  it("returns explicit unavailable metadata for non-quota failures", async () => {
    setMemorySearchImpl(async () => {
      throw new Error("embedding provider timeout");
    });

    const tool = createMemorySearchToolOrThrow();
    const result = await tool.execute("generic", { query: "hello" });
    expectUnavailableMemorySearchDetails(result.details, {
      error: "embedding provider timeout",
      warning: "Memory search is unavailable due to an embedding/provider error.",
      action: "Check embedding provider configuration and retry memory_search.",
    });
  });

  it("returns structured search debug metadata for qmd results", async () => {
    setMemoryBackend("qmd");
    setMemorySearchImpl(async (opts) => {
      opts?.onDebug?.({
        backend: "qmd",
        configuredMode: opts.qmdSearchModeOverride ?? "query",
        effectiveMode: "query",
        fallback: "unsupported-search-flags",
      });
      return [
        {
          path: "MEMORY.md",
          startLine: 1,
          endLine: 2,
          score: 0.9,
          snippet: "ramen",
          source: "memory",
        },
      ];
    });

    const tool = createMemorySearchToolOrThrow({
      config: {
        plugins: {
          entries: {
            "active-memory": {
              config: {
                qmd: {
                  searchMode: "search",
                },
              },
            },
          },
        },
        memory: {
          backend: "qmd",
          qmd: {
            searchMode: "query",
            limits: {
              maxInjectedChars: 1000,
            },
          },
        },
      },
      agentSessionKey: "agent:main:main:active-memory:debug",
    });
    const result = await tool.execute("debug", { query: "favorite food" });
    expect(result.details).toMatchObject({
      mode: "query",
      debug: {
        backend: "qmd",
        configuredMode: "search",
        effectiveMode: "query",
        fallback: "unsupported-search-flags",
        hits: 1,
      },
    });
    expect((result.details as { debug?: { searchMs?: number } }).debug?.searchMs).toEqual(
      expect.any(Number),
    );
  });

  it("appends graph hits when graph index is enabled", async () => {
    const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-tools-graph-"));
    const previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    try {
      setMemorySearchImpl(async () => [
        {
          path: "MEMORY.md",
          startLine: 1,
          endLine: 1,
          score: 0.9,
          snippet: "chunk hit",
          source: "memory",
        },
      ]);
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

      const tool = createMemorySearchToolOrThrow({
        config: {
          agents: { list: [{ id: "main", default: true }] },
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
        },
      });
      const result = await tool.execute("graph", { query: "task_123" });
      const details = result.details as {
        results: Array<{ corpus?: string; snippet: string; graphMeta?: unknown }>;
        debug?: { graph?: { hits: number; renderedHits: number } };
      };

      expect(details.results[0]).toMatchObject({ corpus: "memory" });
      expect(details.results[0]?.snippet).toContain("chunk hit");
      expect(details.results).toContainEqual(
        expect.objectContaining({
          corpus: "graph",
          snippet: expect.stringContaining("[Graph state]"),
          graphMeta: {
            type: "state",
            entity_id: expect.stringMatching(/^ent_/),
          },
        }),
      );
      expect(details.debug?.graph).toMatchObject({ hits: 2, renderedHits: 2 });
    } finally {
      await closeAllCanonicalStores();
      if (previousStateDir === undefined) {
        delete process.env.OPENCLAW_STATE_DIR;
      } else {
        process.env.OPENCLAW_STATE_DIR = previousStateDir;
      }
      await fs.rm(stateDir, { recursive: true, force: true });
    }
  });
});
