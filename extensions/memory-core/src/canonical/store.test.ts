import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { EventRecord, GraphHit } from "./schema.js";
import { CanonicalStore, closeAllCanonicalStores } from "./store.js";

function record(overrides: Partial<EventRecord> = {}): EventRecord {
  return {
    event_id: "evt_task",
    source_type: "memory_file",
    source_ref: "memory/2026-04-15.md#L12-L18",
    occurred_at: "2026-04-15T00:00:00.000Z",
    entity_id: "ent_task",
    actor: "Alice",
    action: "changed_status",
    object: "task_123",
    status_before: null,
    status_after: "blocked",
    session_id: null,
    covered_until_entry_id: null,
    confidence: 0.8,
    extractor_version: "v-test",
    created_at: 1_765_000_000_000,
    ...overrides,
  };
}

describe("canonical graph store", () => {
  let rootDir = "";

  beforeEach(async () => {
    rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-canonical-store-"));
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    await fs.rm(rootDir, { recursive: true, force: true });
  });

  it("creates schema and upserts events, fts rows, and states", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.upsertEvents([record()]);
    await store.upsertEvents([record({ status_after: "done", created_at: 1_765_000_001_000 })]);
    const states = await store.refreshEntityStates([
      record({ status_after: "done", created_at: 1_765_000_001_000 }),
    ]);

    expect(states).toHaveLength(1);
    await expect(store.getEntityState("ent_task")).resolves.toMatchObject({
      latest_status: "done",
      latest_owner: "Alice",
      last_event_id: "evt_task",
      entity_type: "task",
      supporting_event_ids: ["evt_task"],
      confidence: 0.8,
    });
    await expect(store.searchEvents("task_123", 5)).resolves.toEqual([
      expect.objectContaining({
        event_id: "evt_task",
        object: "task_123",
        status_after: "done",
      }),
    ]);
    expect(store.getStatus()).toMatchObject({
      eventsTotal: 1,
      entitiesTotal: 1,
      schemaVersion: "v3",
      metrics: expect.objectContaining({
        hitsReturned: 0,
        hitsUsedRaw: 0,
        hitsUsedUniqueRefs: 0,
        hitsUsed: 0,
        sourceRefValidated: 0,
        sourceRefRejected: 0,
      }),
    });
    store.close();
  });

  it("persists events, KG objects, and states in one batch", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));

    await expect(
      store.persistCanonicalBatch([
        record({
          action: "assigned_owner",
          object: "FEISHU-231",
          object_type: "task",
          status_after: "blocked",
        }),
      ]),
    ).resolves.toMatchObject({
      states: [expect.objectContaining({ entity_id: "ent_task" })],
      graphObjects: {
        entities: expect.arrayContaining([
          expect.objectContaining({ entity_id: "ent_task", entity_type: "task" }),
        ]),
        aliases: expect.arrayContaining([
          expect.objectContaining({ alias: "feishu-231", entity_id: "ent_task" }),
        ]),
        edges: expect.arrayContaining([
          expect.objectContaining({ relation: "owned_by", src_entity_id: "ent_task" }),
        ]),
      },
    });
    expect(store.getStatus()).toMatchObject({
      eventsTotal: 1,
      entitiesTotal: 1,
      canonicalEntitiesTotal: 2,
      graphEdgesTotal: 1,
    });
    expect(store.resolveEntityIds("FEISHU-231")).toContain("ent_task");
    store.close();
  });

  it("rolls back events and states when KG persistence fails", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    const testDb = (store as unknown as { db: { exec(sql: string): void } }).db;
    testDb.exec(
      "CREATE TRIGGER fail_graph_edges BEFORE INSERT ON graph_edges BEGIN SELECT RAISE(ABORT, 'kg fail'); END;",
    );

    await expect(store.persistCanonicalBatch([record()])).rejects.toThrow("kg fail");
    expect(store.getStatus()).toMatchObject({
      eventsTotal: 0,
      entitiesTotal: 0,
      canonicalEntitiesTotal: 0,
      graphEdgesTotal: 0,
    });
    store.close();
  });

  it("resets records and tracks metrics plus recent graph hits", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.upsertEvents([record()]);
    await store.refreshEntityStates([record()]);
    store.recordExtractorLatency(15);
    store.bumpMetric("extractSuccesses", 2);
    const hits: GraphHit[] = [
      {
        type: "state",
        entity_id: "ent_task",
        source_ref: "memory/2026-04-15.md#L12-L18",
        snippet_structured: {},
        score: 0.9,
      },
    ];
    const nowMs = Date.now();
    expect(
      store.recordRecentGraphHits({
        sessionKey: "session:main",
        query: "task_123",
        hits,
        nowMs,
      }),
    ).toBe(1);
    expect(store.getRecentGraphHits("session:main", nowMs)).toHaveLength(1);
    expect(
      store.markRecentGraphHitsUsedByRead({
        sessionKey: "session:main",
        path: "memory/2026-04-15.md",
        from: 12,
        lines: 3,
        nowMs: nowMs + 100,
      }),
    ).toHaveLength(1);
    expect(store.getStatus().metrics).toMatchObject({
      extractSuccesses: 2,
      extractLatencyMsSum: 15,
      extractLatencyMsCount: 1,
      extractLatencyMsAvg: 15,
    });

    store.reset();

    expect(store.getStatus()).toMatchObject({
      eventsTotal: 0,
      entitiesTotal: 0,
      metrics: expect.objectContaining({
        hitsReturned: 0,
        hitsUsedRaw: 0,
        hitsUsedUniqueRefs: 0,
        hitsUsed: 0,
        sourceRefValidated: 0,
        sourceRefRejected: 0,
        extractSuccesses: 0,
      }),
    });
    expect(store.listAliases()).toEqual([]);
    expect(store.getRecentGraphHits("session:main", nowMs + 100)).toEqual([]);
    store.close();
  });

  it("exports events and states as JSONL", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.upsertEvents([record()]);
    await store.refreshEntityStates([record()]);
    store.bumpMetric("hitsReturned", 3);

    const jsonl = await store.exportJsonl();
    const exported = await store.exportData();

    expect(jsonl).toContain('"type":"event"');
    expect(jsonl).toContain('"type":"state"');
    expect(exported.metrics.hitsReturned).toBe(3);
    expect(exported.events).toHaveLength(1);
    expect(exported.states).toHaveLength(1);
    store.close();
  });
});
