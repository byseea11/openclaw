import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { CanonicalStore, closeAllCanonicalStores } from "./store.js";

const V5_LEGACY_SCHEMA_SQL = `
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
  object_type       TEXT,
  status_before     TEXT,
  status_after      TEXT,
  session_id        TEXT,
  covered_until_entry_id TEXT,
  confidence        REAL NOT NULL DEFAULT 0.5,
  extractor_version TEXT NOT NULL,
  created_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_states (
  entity_id        TEXT PRIMARY KEY,
  latest_status    TEXT,
  latest_owner     TEXT,
  last_event_id    TEXT NOT NULL,
  last_updated_at  INTEGER NOT NULL,
  entity_type      TEXT NOT NULL DEFAULT 'other',
  supporting_event_ids TEXT NOT NULL DEFAULT '[]',
  confidence       REAL NOT NULL DEFAULT 0.5
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

CREATE TABLE IF NOT EXISTS canonical_entities (
  entity_id       TEXT PRIMARY KEY,
  entity_type     TEXT NOT NULL,
  canonical_name  TEXT NOT NULL,
  status          TEXT,
  last_seen_at    TEXT,
  confidence      REAL NOT NULL DEFAULT 0.5,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  provenance_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS entity_aliases (
  alias        TEXT NOT NULL,
  entity_id    TEXT NOT NULL,
  alias_type   TEXT NOT NULL,
  confidence   REAL NOT NULL DEFAULT 0.5,
  source_ref   TEXT,
  session_id   TEXT,
  created_at   INTEGER NOT NULL,
  PRIMARY KEY (alias, entity_id, alias_type)
);
`;

describe("canonical graph v5 to v6 migration", () => {
  let rootDir = "";

  beforeEach(async () => {
    rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-canonical-migration-v6-"));
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    await fs.rm(rootDir, { recursive: true, force: true });
  });

  it("migrates legacy semantic rows into v2 and drops legacy tables", async () => {
    const dbPath = path.join(rootDir, "main.graph.sqlite");
    const db = openMemoryDatabaseAtPath(dbPath, false);
    db.exec(V5_LEGACY_SCHEMA_SQL);
    db.prepare("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)").run("schema_version", "v5");
    db.prepare(
      `INSERT INTO canonical_entities(
        entity_id, entity_type, canonical_name, status, last_seen_at, confidence, created_at, updated_at, provenance_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      "ent_task",
      "task",
      "FEISHU-231",
      "blocked",
      "2026-04-20T00:00:00.000Z",
      0.9,
      1_765_000_000_000,
      1_765_000_000_000,
      "[]",
    );
    db.prepare(
      `INSERT INTO entity_aliases(alias, entity_id, alias_type, confidence, source_ref, session_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      "feishu-231",
      "ent_task",
      "normalized",
      0.9,
      "memory/2026-04-15.md#L12-L18",
      "agent:channel:thread",
      1_765_000_000_000,
    );
    db.prepare(
      `INSERT INTO event_records(
        event_id, source_type, source_ref, occurred_at, entity_id, actor, action, object,
        object_type, status_before, status_after, session_id, covered_until_entry_id, confidence,
        extractor_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      "evt_v5",
      "transcript",
      "transcripts/main.txt#L1-L1",
      "2026-04-20T00:00:00.000Z",
      "ent_task",
      "Alice",
      "changed_status",
      "FEISHU-231 blocked by AP-778",
      "task",
      "in_progress",
      "blocked",
      "agent:channel:thread",
      "entry-9",
      0.9,
      "v1-2026.04-llm",
      1_765_000_000_000,
    );
    db.close();

    const store = new CanonicalStore("main", dbPath);
    expect(store.getStatus()).toMatchObject({
      schemaVersion: "v6",
      eventRecordsV2Total: 1,
      workflowStatesV2Total: 1,
      graphEntitiesV2Total: 3,
      graphEdgesV2Total: 1,
    });
    expect(store.getWorkflowStateV2("task:FEISHU-231")).toMatchObject({
      current_stage: "blocked",
      current_blocker_ref: "approval:AP-778",
    });

    const reopened = openMemoryDatabaseAtPath(dbPath, false);
    const legacyEventTable = reopened
      .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'event_records'")
      .get() as { name?: string } | undefined;
    const legacyStateTable = reopened
      .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'entity_states'")
      .get() as { name?: string } | undefined;
    expect(legacyEventTable).toBeUndefined();
    expect(legacyStateTable).toBeUndefined();
    reopened.close();

    store.close();
  });
});
