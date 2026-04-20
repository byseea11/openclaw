import type { DatabaseSync } from "node:sqlite";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";

const log = createSubsystemLogger("memory");

const V4_TO_V5_SQL = `
CREATE TABLE IF NOT EXISTS evidence_records (
  evidence_id          TEXT PRIMARY KEY,
  evidence_fingerprint TEXT NOT NULL UNIQUE,
  source_platform      TEXT NOT NULL,
  source_kind          TEXT NOT NULL,
  session_key          TEXT,
  message_id           TEXT,
  chat_id              TEXT,
  chat_type            TEXT,
  thread_id            TEXT,
  root_id              TEXT,
  parent_id            TEXT,
  first_entry_id       TEXT,
  last_entry_id        TEXT,
  content_text         TEXT,
  content_json         TEXT NOT NULL DEFAULT '{}',
  source_locator_json  TEXT NOT NULL DEFAULT '{}',
  occurred_at          TEXT,
  created_at           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS event_type_registry (
  event_type          TEXT PRIMARY KEY,
  subject_type        TEXT NOT NULL,
  object_type         TEXT,
  payload_schema_json TEXT NOT NULL,
  description         TEXT NOT NULL,
  enabled             INTEGER NOT NULL DEFAULT 1,
  created_at          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS event_records_v2 (
  event_id            TEXT PRIMARY KEY,
  event_fingerprint   TEXT NOT NULL UNIQUE,
  evidence_id         TEXT NOT NULL,
  event_type          TEXT NOT NULL,
  subject_ref         TEXT NOT NULL,
  actor_ref           TEXT,
  object_ref          TEXT,
  related_refs_json   TEXT NOT NULL DEFAULT '[]',
  occurred_at         TEXT NOT NULL,
  payload_json        TEXT NOT NULL DEFAULT '{}',
  confidence          REAL NOT NULL DEFAULT 0.5,
  extraction_version  TEXT NOT NULL,
  created_at          INTEGER NOT NULL,
  FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id),
  FOREIGN KEY(event_type) REFERENCES event_type_registry(event_type)
);

CREATE TABLE IF NOT EXISTS workflow_state_view_v2 (
  task_ref              TEXT PRIMARY KEY,
  current_owner_ref     TEXT,
  current_stage         TEXT,
  current_approval_ref  TEXT,
  approval_status       TEXT,
  current_blocker_ref   TEXT,
  next_action_json      TEXT NOT NULL DEFAULT '{}',
  last_event_id         TEXT NOT NULL,
  last_event_time       TEXT NOT NULL,
  slot_versions_json    TEXT NOT NULL DEFAULT '{}',
  supporting_event_ids  TEXT NOT NULL DEFAULT '[]',
  updated_at            INTEGER NOT NULL,
  FOREIGN KEY(last_event_id) REFERENCES event_records_v2(event_id)
);

CREATE TABLE IF NOT EXISTS graph_entities_v2 (
  entity_ref         TEXT PRIMARY KEY,
  entity_type        TEXT NOT NULL,
  canonical_name     TEXT NOT NULL,
  alias_json         TEXT NOT NULL DEFAULT '[]',
  first_seen_at      TEXT NOT NULL,
  last_seen_at       TEXT NOT NULL,
  last_evidence_id   TEXT,
  updated_at         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges_v2 (
  edge_id                TEXT PRIMARY KEY,
  edge_key               TEXT NOT NULL UNIQUE,
  src_ref                TEXT NOT NULL,
  edge_type              TEXT NOT NULL,
  dst_ref                TEXT NOT NULL,
  derived_from_event_id  TEXT NOT NULL,
  active                 INTEGER NOT NULL,
  valid_from             TEXT NOT NULL,
  valid_to               TEXT,
  updated_at             INTEGER NOT NULL,
  FOREIGN KEY(derived_from_event_id) REFERENCES event_records_v2(event_id)
);
`;

export function runV4ToV5Migration(db: DatabaseSync): void {
  log.info("[canonical] migration.start from=v4 to=v5");
  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec(V4_TO_V5_SQL);
    db.exec("COMMIT");
    log.info("[canonical] migration.done from=v4 to=v5");
  } catch (err) {
    db.exec("ROLLBACK");
    log.warn(`[canonical] migration.fallback from=v4 to=v5 error=${String(err)}`);
    throw err;
  }
}
