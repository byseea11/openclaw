import type { DatabaseSync } from "node:sqlite";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";

const log = createSubsystemLogger("memory");

function hasColumn(db: DatabaseSync, table: string, column: string): boolean {
  const rows = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name?: string }>;
  return rows.some((row) => row.name === column);
}

function hasLegacyAliasSchema(db: DatabaseSync): boolean {
  return (
    hasColumn(db, "entity_aliases", "alias_id") || hasColumn(db, "entity_aliases", "canonical_id")
  );
}

const V2_TO_V3_SQL = `
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

CREATE INDEX IF NOT EXISTS idx_canonical_entities_type_name
  ON canonical_entities(entity_type, canonical_name);

CREATE TABLE IF NOT EXISTS graph_edges (
  edge_id           TEXT PRIMARY KEY,
  src_entity_id     TEXT NOT NULL,
  relation          TEXT NOT NULL,
  dst_entity_id     TEXT NOT NULL,
  occurred_at       TEXT NOT NULL,
  source_ref        TEXT NOT NULL,
  session_id        TEXT,
  evidence_event_id TEXT NOT NULL,
  confidence        REAL NOT NULL DEFAULT 0.5,
  created_at        INTEGER NOT NULL,
  FOREIGN KEY(evidence_event_id) REFERENCES event_records(event_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_src_relation_time
  ON graph_edges(src_entity_id, relation, occurred_at);
CREATE INDEX IF NOT EXISTS idx_graph_edges_dst_relation_time
  ON graph_edges(dst_entity_id, relation, occurred_at);
CREATE INDEX IF NOT EXISTS idx_graph_edges_evidence
  ON graph_edges(evidence_event_id);

CREATE TABLE IF NOT EXISTS kg_backfill_state (
  scope                 TEXT PRIMARY KEY,
  last_event_created_at INTEGER,
  last_event_id         TEXT,
  status                TEXT NOT NULL DEFAULT 'idle',
  last_error            TEXT,
  retry_marker_json     TEXT,
  updated_at            INTEGER NOT NULL
);
`;

const NEW_ALIAS_SQL = `
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

CREATE INDEX IF NOT EXISTS idx_alias_canonical ON entity_aliases(entity_id);
CREATE INDEX IF NOT EXISTS idx_alias_lookup ON entity_aliases(alias);
`;

export function runV2ToV3Migration(db: DatabaseSync): void {
  log.info("[canonical] migration.start from=v2 to=v3");
  db.exec("BEGIN IMMEDIATE");
  try {
    if (!hasColumn(db, "event_records", "object_type")) {
      db.exec("ALTER TABLE event_records ADD COLUMN object_type TEXT");
    }
    if (hasLegacyAliasSchema(db)) {
      db.exec("ALTER TABLE entity_aliases RENAME TO entity_aliases_legacy_v2");
      db.exec("DROP INDEX IF EXISTS idx_alias_canonical");
    }
    db.exec(NEW_ALIAS_SQL);
    db.exec(V2_TO_V3_SQL);
    db.exec("COMMIT");
    log.info("[canonical] migration.done from=v2 to=v3");
  } catch (err) {
    db.exec("ROLLBACK");
    log.warn(`[canonical] migration.fallback from=v2 to=v3 error=${String(err)}`);
    throw err;
  }
}
