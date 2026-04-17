import type { DatabaseSync } from "node:sqlite";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";

const log = createSubsystemLogger("memory");

const V0_TO_V1_SQL = `
ALTER TABLE event_records ADD COLUMN status_before TEXT;
ALTER TABLE event_records ADD COLUMN session_id TEXT;
ALTER TABLE event_records ADD COLUMN covered_until_entry_id TEXT;

ALTER TABLE entity_states ADD COLUMN entity_type TEXT NOT NULL DEFAULT 'other';
ALTER TABLE entity_states ADD COLUMN supporting_event_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE entity_states ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5;

CREATE TABLE IF NOT EXISTS entity_aliases (
  alias_id       TEXT NOT NULL,
  canonical_id   TEXT NOT NULL,
  source         TEXT NOT NULL,
  created_at     INTEGER NOT NULL,
  PRIMARY KEY (alias_id, canonical_id)
);

CREATE INDEX IF NOT EXISTS idx_alias_canonical ON entity_aliases(canonical_id);

DELETE FROM event_fts;
INSERT INTO event_fts(event_id, entity_id, actor, action, object, status_after)
SELECT event_id, entity_id, actor, action, object, status_after
FROM event_records;
`;

export function runV0ToV1Migration(db: DatabaseSync): void {
  log.info("[canonical] migration.start from=v0 to=v1");
  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec(V0_TO_V1_SQL);
    db.exec("COMMIT");
    log.info("[canonical] migration.done from=v0 to=v1");
  } catch (err) {
    db.exec("ROLLBACK");
    log.warn(`[canonical] migration.fallback from=v0 to=v1 error=${String(err)}`);
    throw err;
  }
}
