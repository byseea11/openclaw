import type { DatabaseSync } from "node:sqlite";

export function runV6ToV7Migration(db: DatabaseSync): void {
  db.exec(`
ALTER TABLE evidence_records ADD COLUMN linked_event_ids_json TEXT;

CREATE TABLE IF NOT EXISTS decision_state_view_v2 (
  topic_ref                        TEXT PRIMARY KEY,
  decision_axis_key                TEXT NOT NULL,
  decision_axis_text               TEXT NOT NULL,
  decision_axis_instance_id        TEXT,
  active_conclusion_event_id       TEXT,
  active_rationale_event_ids_json  TEXT NOT NULL DEFAULT '[]',
  active_objection_event_ids_json  TEXT NOT NULL DEFAULT '[]',
  active_stage_event_id            TEXT,
  active_time_point_event_ids_json TEXT NOT NULL DEFAULT '[]',
  slot_versions_json               TEXT NOT NULL DEFAULT '{}',
  last_event_id                    TEXT NOT NULL,
  updated_at                       INTEGER NOT NULL,
  FOREIGN KEY(active_conclusion_event_id) REFERENCES event_records_v2(event_id),
  FOREIGN KEY(active_stage_event_id) REFERENCES event_records_v2(event_id),
  FOREIGN KEY(last_event_id) REFERENCES event_records_v2(event_id)
);

CREATE INDEX IF NOT EXISTS idx_decision_state_v2_axis
  ON decision_state_view_v2(decision_axis_key, updated_at);
CREATE INDEX IF NOT EXISTS idx_decision_state_v2_instance
  ON decision_state_view_v2(decision_axis_instance_id, updated_at);
`);
}
