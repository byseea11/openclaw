import type { DatabaseSync } from "node:sqlite";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";

const log = createSubsystemLogger("memory");

const V3_TO_V4_SQL = `
CREATE TABLE IF NOT EXISTS workflow_state_view (
  object_type               TEXT NOT NULL,
  object_id                 TEXT NOT NULL,
  stage                     TEXT,
  owner_entity_id           TEXT,
  blocker_status            TEXT NOT NULL DEFAULT 'unknown',
  blocker_reason            TEXT,
  approval_status           TEXT NOT NULL DEFAULT 'unknown',
  next_action               TEXT,
  last_event_id             TEXT NOT NULL,
  last_updated_at           INTEGER NOT NULL,
  supporting_event_ids_json TEXT NOT NULL DEFAULT '[]',
  conflict_flags_json       TEXT NOT NULL DEFAULT '[]',
  slot_versions_json        TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (object_type, object_id),
  FOREIGN KEY(last_event_id) REFERENCES event_records(event_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_state_unique_object_id
  ON workflow_state_view(object_id);
CREATE INDEX IF NOT EXISTS idx_workflow_state_type_stage
  ON workflow_state_view(object_type, stage);
CREATE INDEX IF NOT EXISTS idx_workflow_state_owner
  ON workflow_state_view(owner_entity_id);
CREATE INDEX IF NOT EXISTS idx_workflow_state_blocker
  ON workflow_state_view(blocker_status, last_updated_at);
CREATE INDEX IF NOT EXISTS idx_workflow_state_approval
  ON workflow_state_view(approval_status, last_updated_at);
CREATE INDEX IF NOT EXISTS idx_workflow_state_last_event
  ON workflow_state_view(last_event_id);
`;

export function runV3ToV4Migration(db: DatabaseSync): void {
  log.info("[canonical] migration.start from=v3 to=v4");
  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec(V3_TO_V4_SQL);
    db.exec("COMMIT");
    log.info("[canonical] migration.done from=v3 to=v4");
  } catch (err) {
    db.exec("ROLLBACK");
    log.warn(`[canonical] migration.fallback from=v3 to=v4 error=${String(err)}`);
    throw err;
  }
}
