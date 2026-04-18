import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";

export const EXTRACTOR_VERSION = "v1-2026.04-llm";
export const CANONICAL_SCHEMA_VERSION = "v2";
export const GRAPH_PROJECTION_VERSION = "v1-2026.04";
export const GRAPH_RECALL_TTL_MS = 30 * 60 * 1000;

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
  alias_id: string;
  canonical_id: string;
  source: "rule" | "manual" | "llm";
  created_at: number;
};

export type GraphHit = {
  type: "event" | "state";
  entity_id: string;
  source_ref: string;
  snippet_structured: Record<string, unknown>;
  score: number;
};

export type GraphIndexConfig = {
  enabled: boolean;
  bootstrapOnStart: boolean;
  extractDuringFlush: boolean;
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
  events: EventRecord[];
  states: EntityState[];
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

CREATE TABLE IF NOT EXISTS event_records (
  event_id          TEXT PRIMARY KEY,
  source_type       TEXT NOT NULL,
  source_ref        TEXT NOT NULL,
  occurred_at       TEXT NOT NULL,
  entity_id         TEXT NOT NULL,
  actor             TEXT,
  action            TEXT NOT NULL,
  object            TEXT,
  status_before     TEXT,
  status_after      TEXT,
  session_id        TEXT,
  covered_until_entry_id TEXT,
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
  entity_type      TEXT NOT NULL DEFAULT 'other',
  supporting_event_ids TEXT NOT NULL DEFAULT '[]',
  confidence       REAL NOT NULL DEFAULT 0.5,
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

CREATE TABLE IF NOT EXISTS entity_aliases (
  alias_id       TEXT NOT NULL,
  canonical_id   TEXT NOT NULL,
  source         TEXT NOT NULL,
  created_at     INTEGER NOT NULL,
  PRIMARY KEY (alias_id, canonical_id)
);

CREATE INDEX IF NOT EXISTS idx_alias_canonical ON entity_aliases(canonical_id);
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
    extractDuringFlush: normalizeBoolean(graphIndex?.extractDuringFlush, true),
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
