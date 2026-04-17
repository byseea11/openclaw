import type { DatabaseSync } from "node:sqlite";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";

const log = createSubsystemLogger("memory");

const V1_TO_V2_SQL = `
CREATE TABLE IF NOT EXISTS source_projection_state (
  source_kind              TEXT NOT NULL,
  source_id                TEXT NOT NULL,
  covered_until_entry_id   TEXT,
  dirty_since_entry_id     TEXT,
  last_projected_at        INTEGER,
  projection_version       TEXT NOT NULL,
  status                   TEXT NOT NULL DEFAULT 'clean',
  PRIMARY KEY (source_kind, source_id)
);

CREATE INDEX IF NOT EXISTS idx_projection_state_status
  ON source_projection_state(status, source_kind);

CREATE TABLE IF NOT EXISTS projection_inbox (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  source_kind     TEXT NOT NULL,
  source_id       TEXT NOT NULL,
  first_entry_id  TEXT NOT NULL,
  last_entry_id   TEXT NOT NULL,
  entries_json    TEXT NOT NULL,
  dirty_reason    TEXT NOT NULL,
  signal_strength REAL NOT NULL DEFAULT 0,
  strong_event    INTEGER NOT NULL DEFAULT 0,
  created_at      INTEGER NOT NULL,
  drained_at      INTEGER,
  UNIQUE(source_kind, source_id, first_entry_id, last_entry_id)
);

CREATE INDEX IF NOT EXISTS idx_projection_inbox_pending
  ON projection_inbox(source_kind, source_id, drained_at, created_at);
`;

export function runV1ToV2Migration(db: DatabaseSync): void {
  log.info("[canonical] migration.start from=v1 to=v2");
  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec(V1_TO_V2_SQL);
    db.exec("COMMIT");
    log.info("[canonical] migration.done from=v1 to=v2");
  } catch (err) {
    db.exec("ROLLBACK");
    log.warn(`[canonical] migration.fallback from=v1 to=v2 error=${String(err)}`);
    throw err;
  }
}
