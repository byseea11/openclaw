import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { search_graph } from "./retriever.js";
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

describe("canonical graph retriever", () => {
  let rootDir = "";

  beforeEach(async () => {
    rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-canonical-retriever-"));
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    await fs.rm(rootDir, { recursive: true, force: true });
  });

  it("returns state and event hits with source refs", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.upsertEvents([
      record(),
      record({
        event_id: "evt_other",
        entity_id: "ent_other",
        object: "task_999",
        source_ref: "memory/2026-04-01.md#L2-L2",
        occurred_at: "2026-04-01T00:00:00.000Z",
        created_at: 1_765_000_000_100,
      }),
    ]);
    await store.refreshEntityStates([record(), record({ event_id: "evt_other", entity_id: "ent_other", object: "task_999" })]);

    const hits = await search_graph(store, "task_123", 5);

    expect(hits).toEqual([
      expect.objectContaining({
        type: "state",
        entity_id: "ent_task",
        source_ref: "memory/2026-04-15.md#L12-L18",
      }),
      expect.objectContaining({
        type: "event",
        entity_id: "ent_task",
        source_ref: "memory/2026-04-15.md#L12-L18",
      }),
    ]);
    store.close();
  });
});
