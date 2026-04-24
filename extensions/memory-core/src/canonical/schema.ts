import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";

export const EXTRACTOR_VERSION = "v2-2026.04-llm-workflow-only";
export const CANONICAL_SCHEMA_VERSION = "v6";
export const GRAPH_PROJECTION_VERSION = "v1-2026.04";
export const GRAPH_RECALL_TTL_MS = 30 * 60 * 1000;

export const STRONG_GRAPH_RELATIONS = [
  "assigned_to",
  "owned_by",
  "depends_on",
  "blocks",
  "decided_by",
  "scheduled_for",
  "participated_in",
] as const;

export const WEAK_GRAPH_RELATIONS = ["about", "mentions", "related_to"] as const;

export type StrongGraphRelation = (typeof STRONG_GRAPH_RELATIONS)[number];
export type WeakGraphRelation = (typeof WEAK_GRAPH_RELATIONS)[number];
export type GraphRelation = StrongGraphRelation | WeakGraphRelation;

export type GraphMetricKey =
  | "hitsReturned"
  | "hitsUsedRaw"
  | "hitsUsedUniqueRefs"
  | "sourceRefValidated"
  | "sourceRefRejected"
  | "extractSuccesses"
  | "extractFailures"
  | "extractLatencyMsSum"
  | "extractLatencyMsCount";

export type GraphMetricsSnapshot = Record<GraphMetricKey, number> & {
  /**
   * V0 compatibility alias. M0-fix semantics are unique source_ref usage.
   */
  hitsUsed: number;
  extractLatencyMsAvg: number;
};

export type RawEvent = {
  actor?: string;
  action: string;
  object?: string;
  object_type?: string;
  status_before?: string;
  status_after?: string;
  occurred_at?: string;
  source_ref: string;
  confidence?: number;
};

export type EventRecord = {
  event_id: string;
  source_type: "transcript" | "tool_result" | "flush" | "promotion" | "memory_file";
  source_ref: string;
  occurred_at: string;
  entity_id: string;
  actor: string | null;
  action: string;
  object: string | null;
  object_type?: CanonicalEntityType | null;
  status_before: string | null;
  status_after: string | null;
  session_id: string | null;
  covered_until_entry_id: string | null;
  confidence: number;
  extractor_version: string;
  created_at: number;
};

export type EntityState = {
  entity_id: string;
  latest_status: string | null;
  latest_owner: string | null;
  last_event_id: string;
  last_updated_at: number;
  entity_type: "task" | "project" | "person" | "decision" | "other";
  supporting_event_ids: string[];
  confidence: number;
};

export type EntityAlias = {
  alias: string;
  entity_id: string;
  alias_type: "exact" | "normalized" | "heuristic";
  confidence: number;
  source_ref: string | null;
  session_id: string | null;
  created_at: number;
};

export type CanonicalEntityType =
  | "person"
  | "team"
  | "project"
  | "task"
  | "decision"
  | "document"
  | "meeting"
  | "customer"
  | "other";

export type CanonicalEntity = {
  entity_id: string;
  entity_type: CanonicalEntityType;
  canonical_name: string;
  status: string | null;
  last_seen_at: string | null;
  confidence: number;
  created_at: number;
  updated_at: number;
  provenance_json: string;
};

export type GraphEdge = {
  edge_id: string;
  src_entity_id: string;
  relation: GraphRelation;
  dst_entity_id: string;
  occurred_at: string;
  source_ref: string;
  session_id: string | null;
  evidence_event_id: string;
  confidence: number;
  created_at: number;
};

export type GraphObjectSet = {
  entities: CanonicalEntity[];
  aliases: EntityAlias[];
  edges: GraphEdge[];
};

export type KgBackfillState = {
  scope: string;
  last_event_created_at: number | null;
  last_event_id: string | null;
  status: "idle" | "running" | "failed" | "complete";
  last_error: string | null;
  retry_marker_json: string | null;
  updated_at: number;
};

export type WorkflowObjectType =
  | "task"
  | "project"
  | "approval"
  | "meeting"
  | "document"
  | "artifact";
export type WorkflowSourceKind = "transcript" | "tool_result" | "flush" | "backfill" | "doc_parse";
export type WorkflowAdmission = "current_state_patch" | "evidence_only" | "reject";
export type WorkflowRelationStrength = "strong" | "weak" | "none";
export type WorkflowResolutionStatus = "stable" | "ambiguous" | "unresolved";

export type WorkflowStateView = {
  object_type: WorkflowObjectType;
  object_id: string;
  stage: string | null;
  owner_entity_id: string | null;
  blocker_status: "unknown" | "none" | "blocked" | "resolved";
  blocker_reason: string | null;
  approval_status: "unknown" | "pending" | "approved" | "rejected" | "needs_review";
  next_action: string | null;
  last_event_id: string;
  last_updated_at: number;
  supporting_event_ids: string[];
  conflict_flags: string[];
  slot_versions: Record<string, unknown>;
};

export type WorkflowUpdate = {
  update_id?: string;
  object_type: WorkflowObjectType;
  object_id: string;
  occurred_at: string;
  source: {
    source_kind: WorkflowSourceKind;
    source_ref: string;
    session_id?: string | null;
  };
  patch: {
    set?: {
      stage?: string;
      owner_entity_id?: string | null;
      blocker_status?: WorkflowStateView["blocker_status"];
      blocker_reason?: string | null;
      approval_status?: WorkflowStateView["approval_status"];
      next_action?: string | null;
    };
    clear?: Array<
      "stage" | "owner_entity_id" | "blocker_reason" | "approval_status" | "next_action"
    >;
    resolve?: {
      blocker?: boolean;
      approval?: boolean;
    };
    append?: {
      supporting_event_ids?: string[];
      conflict_flags?: string[];
    };
  };
  evidence: {
    event_id: string;
    supporting_event_ids?: string[];
    edge_ids?: string[];
    confidence: number;
    relation_strength: WorkflowRelationStrength;
    resolution_status: WorkflowResolutionStatus;
  };
  derived: {
    canonical_entity_id: string;
    canonical_entity_type: string;
    workflow_type_source:
      | "canonical_type"
      | "event_object_type"
      | "strong_relation"
      | "explicit_semantics";
  };
};

export type WorkflowUpdateResult = {
  update_id: string;
  object_type: string;
  object_id: string;
  admission: WorkflowAdmission;
  applied: boolean;
  changed_slots: string[];
  ignored_slots: Array<{
    slot: string;
    reason:
      | "stale"
      | "duplicate"
      | "lower_priority"
      | "ambiguous"
      | "weak_relation"
      | "type_conflict";
  }>;
  conflict_flags_added: string[];
};

export type GraphHit = {
  type: "event" | "state" | "edge";
  entity_id: string;
  source_ref: string;
  snippet_structured: Record<string, unknown>;
  score: number;
};

export type GraphIndexConfig = {
  enabled: boolean;
  bootstrapOnStart: boolean;
  trace: GraphIndexTraceConfig;
};

export type GraphIndexTraceConfig = {
  enabled: boolean;
  filePath: string | null;
  includeEntryPreview: boolean;
  maxPreviewChars: number;
};

export type ProjectionSourceState = {
  source_kind: "transcript";
  source_id: string;
  covered_until_entry_id: string | null;
  dirty_since_entry_id: string | null;
  last_projected_at: number | null;
  projection_version: string;
  status: "clean" | "dirty" | "draining" | "failed";
};

export type ProjectionInboxEntry = {
  id: number;
  source_kind: "transcript";
  source_id: string;
  first_entry_id: string;
  last_entry_id: string;
  entries_json: string;
  dirty_reason: string;
  signal_strength: number;
  strong_event: boolean;
  created_at: number;
  drained_at: number | null;
};

export type ProjectionInboxWrite = Omit<ProjectionInboxEntry, "id" | "drained_at">;

export type RecentGraphCandidate = {
  session_key: string;
  source_ref: string;
  path: string;
  start_line: number;
  end_line: number;
  entity_id: string;
  hit_type: GraphHit["type"];
  query: string | null;
  first_returned_at: number;
  last_returned_at: number;
  expires_at: number;
  used_at: number | null;
};

export type GraphExportData = {
  evidence: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  workflowStates: Array<Record<string, unknown>>;
  entities: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  metrics: GraphMetricsSnapshot;
};

export type SourceRefValidationResult =
  | {
      ok: true;
      path: string;
      startLine: number;
      endLine: number;
      totalLines: number;
    }
  | {
      ok: false;
      reason:
        | "invalid_syntax"
        | "unsafe_path"
        | "not_memory_source"
        | "file_missing"
        | "line_range";
      sourceRef: string;
      totalLines?: number;
    };

export const GRAPH_METRIC_KEYS: GraphMetricKey[] = [
  "hitsReturned",
  "hitsUsedRaw",
  "hitsUsedUniqueRefs",
  "sourceRefValidated",
  "sourceRefRejected",
  "extractSuccesses",
  "extractFailures",
  "extractLatencyMsSum",
  "extractLatencyMsCount",
];

export const CANONICAL_SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_recent_graph_hits_session
  ON recent_graph_hits(session_key, expires_at);
CREATE INDEX IF NOT EXISTS idx_recent_graph_hits_path
  ON recent_graph_hits(session_key, path, start_line, end_line);

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

CREATE INDEX IF NOT EXISTS idx_evidence_records_session
  ON evidence_records(session_key, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_records_message
  ON evidence_records(message_id);
CREATE INDEX IF NOT EXISTS idx_evidence_records_thread
  ON evidence_records(thread_id, created_at);

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

CREATE INDEX IF NOT EXISTS idx_event_records_v2_subject
  ON event_records_v2(subject_ref, occurred_at);
CREATE INDEX IF NOT EXISTS idx_event_records_v2_object
  ON event_records_v2(object_ref, occurred_at);
CREATE INDEX IF NOT EXISTS idx_event_records_v2_type
  ON event_records_v2(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_event_records_v2_evidence
  ON event_records_v2(evidence_id);

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

CREATE INDEX IF NOT EXISTS idx_workflow_state_v2_owner
  ON workflow_state_view_v2(current_owner_ref, updated_at);
CREATE INDEX IF NOT EXISTS idx_workflow_state_v2_stage
  ON workflow_state_view_v2(current_stage, updated_at);
CREATE INDEX IF NOT EXISTS idx_workflow_state_v2_approval
  ON workflow_state_view_v2(approval_status, updated_at);
CREATE INDEX IF NOT EXISTS idx_workflow_state_v2_blocker
  ON workflow_state_view_v2(current_blocker_ref, updated_at);

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

CREATE INDEX IF NOT EXISTS idx_graph_entities_v2_type_name
  ON graph_entities_v2(entity_type, canonical_name);
CREATE INDEX IF NOT EXISTS idx_graph_entities_v2_last_seen
  ON graph_entities_v2(last_seen_at);

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

CREATE INDEX IF NOT EXISTS idx_graph_edges_v2_src
  ON graph_edges_v2(src_ref, edge_type, active);
CREATE INDEX IF NOT EXISTS idx_graph_edges_v2_dst
  ON graph_edges_v2(dst_ref, edge_type, active);
CREATE INDEX IF NOT EXISTS idx_graph_edges_v2_event
  ON graph_edges_v2(derived_from_event_id);
`;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeString(value: unknown, fallback: string | null): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback;
}

function normalizePositiveInteger(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : fallback;
}

export function resolveGraphIndexConfig(cfg?: OpenClawConfig): GraphIndexConfig {
  const plugins = asRecord(cfg?.plugins);
  const entries = asRecord(plugins?.entries);
  const memoryEntry = asRecord(entries?.["memory-core"]);
  const pluginConfig = asRecord(memoryEntry?.config);
  const graphIndex = asRecord(pluginConfig?.graphIndex);
  const trace = asRecord(graphIndex?.trace);
  return {
    enabled: normalizeBoolean(graphIndex?.enabled, false),
    bootstrapOnStart: normalizeBoolean(graphIndex?.bootstrapOnStart, true),
    trace: {
      enabled: normalizeBoolean(trace?.enabled, false),
      filePath: normalizeString(trace?.filePath, null),
      includeEntryPreview: normalizeBoolean(trace?.includeEntryPreview, true),
      maxPreviewChars: normalizePositiveInteger(trace?.maxPreviewChars, 180),
    },
  };
}

export function describeGraphIndexConfig(cfg?: OpenClawConfig) {
  return {
    ...resolveGraphIndexConfig(cfg),
    schemaVersion: CANONICAL_SCHEMA_VERSION,
    extractorVersion: EXTRACTOR_VERSION,
    projectionVersion: GRAPH_PROJECTION_VERSION,
  };
}

export function isMemorySourceRef(sourceRef: string): boolean {
  const trimmed = sourceRef.trim();
  return (
    trimmed === "MEMORY.md" || trimmed.startsWith("MEMORY.md#") || trimmed.startsWith("memory/")
  );
}

export function isSafeMemorySourcePath(sourcePath: string): boolean {
  const normalized = sourcePath.replaceAll("\\", "/").trim();
  if (
    !normalized ||
    normalized.startsWith("/") ||
    normalized.includes("\0") ||
    normalized.split("/").includes("..")
  ) {
    return false;
  }
  return normalized === "MEMORY.md" || normalized.startsWith("memory/");
}

export function isSafeGraphSourcePath(sourcePath: string): boolean {
  const normalized = sourcePath.replaceAll("\\", "/").trim();
  if (
    !normalized ||
    normalized.startsWith("/") ||
    normalized.includes("\0") ||
    normalized.split("/").includes("..")
  ) {
    return false;
  }
  return (
    normalized === "MEMORY.md" ||
    normalized.startsWith("memory/") ||
    normalized.startsWith("transcripts/")
  );
}

export function parseSourceRef(
  sourceRef: string,
): { path: string; startLine: number; endLine: number } | null {
  const trimmed = sourceRef.trim();
  const match = trimmed.match(/^(.+?)#L(\d+)(?:-L?(\d+))?$/);
  if (!match) {
    return null;
  }
  const startLine = Number(match[2]);
  const endLine = Number(match[3] ?? match[2]);
  if (
    !Number.isInteger(startLine) ||
    !Number.isInteger(endLine) ||
    startLine <= 0 ||
    endLine <= 0
  ) {
    return null;
  }
  if (endLine < startLine) {
    return null;
  }
  const sourcePath = (match[1] ?? "").replaceAll("\\", "/").replace(/^\.\//, "");
  if (!isSafeGraphSourcePath(sourcePath)) {
    return null;
  }
  return {
    path: sourcePath,
    startLine,
    endLine,
  };
}
