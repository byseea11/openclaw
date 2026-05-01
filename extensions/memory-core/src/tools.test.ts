import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { generateUlid } from "./canonical/id-v2.js";
import { closeAllCanonicalStores, getCanonicalStore } from "./canonical/index.js";
import { buildEvidenceFingerprint, buildEventFingerprint } from "./canonical/schema-v2.js";
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
      const evidenceId = generateUlid();
      const occurredAt = "2026-04-15T00:00:00.000Z";
      await store.persistSemanticBatchV2({
        evidence: [{
          evidence_id: evidenceId,
          evidence_fingerprint: buildEvidenceFingerprint({
            sourcePlatform: "transcript",
            sourceKind: "transcript_span",
            sessionKey: "agent:main:test:graph",
            firstEntryId: "e1",
            lastEntryId: "e1",
            occurredAt,
            contentText: "FEISHU-231 blocked",
            contentJson: {},
          }),
          source_platform: "transcript",
          source_kind: "transcript_span",
          session_key: "agent:main:test:graph",
          message_id: null,
          chat_id: null,
          chat_type: null,
          thread_id: null,
          root_id: null,
          parent_id: null,
          first_entry_id: "e1",
          last_entry_id: "e1",
          content_text: "FEISHU-231 blocked",
          content_json: "{}",
          source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L1-L1" }),
          occurred_at: occurredAt,
          created_at: Date.now(),
        }],
        events: [
          {
            event_id: generateUlid(),
            event_fingerprint: buildEventFingerprint({
              evidenceId,
              eventType: "constraint_event",
              subjectRef: "task:FEISHU-231",
              objectRef: "blocker:test",
              occurredAt,
              payloadJson: {
                task_ref: "task:FEISHU-231",
                claim: "FEISHU-231 blocked",
                constraint: "blocker:test",
              },
            }),
            evidence_id: evidenceId,
            event_type: "constraint_event",
            subject_ref: "task:FEISHU-231",
            actor_ref: "person_name:alice",
            object_ref: "blocker:test",
            related_refs_json: JSON.stringify(["person_name:alice", "blocker:test"]),
            occurred_at: occurredAt,
            payload_json: JSON.stringify({
              task_ref: "task:FEISHU-231",
              claim: "FEISHU-231 blocked",
              constraint: "blocker:test",
            }),
            confidence: 0.9,
            extraction_version: "v-test",
            created_at: Date.now(),
          },
        ],
      });

      const tool = createMemorySearchToolOrThrow({
        config: {
          agents: { list: [{ id: "main", default: true }] },
          plugins: {
            entries: {
              "memory-core": {
                config: {
                  feishuTaskWiki: {
                    enabled: true,
                  },
                },
              },
            },
          },
        },
        agentSessionKey: "agent:main:test:graph",
      });
      const result = await tool.execute("graph", { query: "FEISHU-231" });
      const details = result.details as {
        results: Array<{ corpus?: string; snippet: string; graphMeta?: unknown }>;
        debug?: { graph?: { hits: number; renderedHits: number } };
      };

      expect(details.results).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            corpus: "memory",
            snippet: expect.stringContaining("chunk hit"),
          }),
        ]),
      );
      expect(details.results).toContainEqual(
        expect.objectContaining({
          corpus: "graph",
          snippet: expect.stringContaining("[Graph state]"),
          graphMeta: {
            type: "state",
            entity_id: "task:FEISHU-231",
          },
        }),
      );
      expect(details.debug?.graph).toMatchObject({ hits: 1, renderedHits: 1 });
      expect(store.getStatus().metrics.hitsReturned).toBe(1);
      expect(store.getRecentGraphHits("agent:main:test:graph")).toHaveLength(1);
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
