import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { CanonicalStore, closeAllCanonicalStores } from "./store.js";

const V0_SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_records (
  event_id          TEXT PRIMARY KEY,
  source_type       TEXT NOT NULL,
  source_ref        TEXT NOT NULL,
  occurred_at       TEXT NOT NULL,
  entity_id         TEXT NOT NULL,
  actor             TEXT,
  action            TEXT NOT NULL,
  object            TEXT,
  status_after      TEXT,
  confidence        REAL NOT NULL DEFAULT 0.5,
  extractor_version TEXT NOT NULL,
  created_at        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_entity ON event_records(entity_id);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON event_records(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_source ON event_records(source_ref);

CREATE TABLE IF NOT EXISTS entity_states (
  entity_id        TEXT PRIMARY KEY,
  latest_status    TEXT,
  latest_owner     TEXT,
  last_event_id    TEXT NOT NULL,
  last_updated_at  INTEGER NOT NULL,
  FOREIGN KEY(last_event_id) REFERENCES event_records(event_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
  event_id UNINDEXED,
  entity_id,
  actor,
  action,
  object,
  status_after,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS graph_metrics (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recent_graph_hits (
  session_key       TEXT NOT NULL,
  source_ref        TEXT NOT NULL,
  path              TEXT NOT NULL,
  start_line        INTEGER NOT NULL,
  end_line          INTEGER NOT NULL,
  entity_id         TEXT NOT NULL,
  hit_type          TEXT NOT NULL,
  query             TEXT,
  first_returned_at INTEGER NOT NULL,
  last_returned_at  INTEGER NOT NULL,
  expires_at        INTEGER NOT NULL,
  used_at           INTEGER,
  PRIMARY KEY(session_key, source_ref, path, start_line, end_line, hit_type)
);
`;

describe("canonical graph v0 to v4 migration", () => {
  let rootDir = "";

  beforeEach(async () => {
    rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-canonical-migration-"));
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    await fs.rm(rootDir, { recursive: true, force: true });
  });

  it("upgrades a v0 sidecar in place", async () => {
    const dbPath = path.join(rootDir, "main.graph.sqlite");
    const db = openMemoryDatabaseAtPath(dbPath, false);
    db.exec(V0_SCHEMA_SQL);
    db.prepare("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)").run("schema_version", "v0");
    db.prepare("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)").run(
      "extractor_version",
      "v0-2026.04",
    );
    db.prepare(
      `INSERT INTO event_records(
        event_id, source_type, source_ref, occurred_at, entity_id, actor, action, object,
        status_after, confidence, extractor_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      "evt_v0",
      "memory_file",
      "memory/2026-04-15.md#L12-L18",
      "2026-04-15T00:00:00.000Z",
      "ent_task",
      "Alice",
      "changed_status",
      "task_123",
      "blocked",
      0.8,
      "v0-2026.04",
      1_765_000_000_000,
    );
    db.prepare(
      `INSERT INTO entity_states(
        entity_id, latest_status, latest_owner, last_event_id, last_updated_at
      ) VALUES (?, ?, ?, ?, ?)`,
    ).run("ent_task", "blocked", "Alice", "evt_v0", 1_765_000_000_000);
    db.close();

    const store = new CanonicalStore("main", dbPath);

    expect(store.getStatus()).toMatchObject({
      schemaVersion: "v4",
      extractorVersion: "v1-2026.04-llm",
      projectionVersion: "v1-2026.04",
      eventsTotal: 1,
      entitiesTotal: 1,
      canonicalEntitiesTotal: 0,
      graphEdgesTotal: 0,
      workflowStatesTotal: 0,
    });
    await expect(store.searchEvents("task_123", 5)).resolves.toEqual([
      expect.objectContaining({
        event_id: "evt_v0",
        object_type: null,
        status_before: null,
        session_id: null,
        covered_until_entry_id: null,
      }),
    ]);
    await expect(store.getEntityState("ent_task")).resolves.toMatchObject({
      entity_type: "other",
      supporting_event_ids: [],
      confidence: 0.5,
    });
    expect(store.listAliases()).toEqual([]);
    await expect(store.backfillGraphObjectsFromEvents()).resolves.toMatchObject({
      processedEvents: 1,
      entities: 2,
    });
    expect(store.getStatus()).toMatchObject({
      canonicalEntitiesTotal: 2,
      graphEdgesTotal: 1,
    });
    store.close();
  });
});
