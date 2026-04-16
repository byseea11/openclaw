import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { EventRecord } from "./schema.js";
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
    status_after: "blocked",
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
      schemaVersion: "v0",
    });
    store.close();
  });

  it("exports events and states as JSONL", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.upsertEvents([record()]);
    await store.refreshEntityStates([record()]);

    const jsonl = await store.exportJsonl();

    expect(jsonl).toContain('"type":"event"');
    expect(jsonl).toContain('"type":"state"');
    store.close();
  });
});
