import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";

export const EXTRACTOR_VERSION = "v0-2026.04";
export const CANONICAL_SCHEMA_VERSION = "v0";
export const GRAPH_RECALL_TTL_MS = 30 * 60 * 1000;

export type GraphMetricKey =
  | "hitsReturned"
  | "hitsUsed"
  | "extractSuccesses"
  | "extractFailures"
  | "extractLatencyMsSum"
  | "extractLatencyMsCount";

export type GraphMetricsSnapshot = Record<GraphMetricKey, number> & {
  extractLatencyMsAvg: number;
};

export type RawEvent = {
  actor?: string;
  action: string;
  object?: string;
  status_after?: string;
  occurred_at?: string;
  source_ref: string;
  confidence?: number;
};

export type EventRecord = {
  event_id: string;
  source_type: "memory_file" | "flush_turn";
  source_ref: string;
  occurred_at: string;
  entity_id: string;
  actor: string | null;
  action: string;
  object: string | null;
  status_after: string | null;
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
};

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

export const GRAPH_METRIC_KEYS: GraphMetricKey[] = [
  "hitsReturned",
  "hitsUsed",
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

CREATE INDEX IF NOT EXISTS idx_recent_graph_hits_session
  ON recent_graph_hits(session_key, expires_at);
CREATE INDEX IF NOT EXISTS idx_recent_graph_hits_path
  ON recent_graph_hits(session_key, path, start_line, end_line);
`;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function resolveGraphIndexConfig(cfg?: OpenClawConfig): GraphIndexConfig {
  const plugins = asRecord(cfg?.plugins);
  const entries = asRecord(plugins?.entries);
  const memoryEntry = asRecord(entries?.["memory-core"]);
  const pluginConfig = asRecord(memoryEntry?.config);
  const graphIndex = asRecord(pluginConfig?.graphIndex);
  return {
    enabled: normalizeBoolean(graphIndex?.enabled, false),
    bootstrapOnStart: normalizeBoolean(graphIndex?.bootstrapOnStart, true),
    extractDuringFlush: normalizeBoolean(graphIndex?.extractDuringFlush, true),
  };
}

export function describeGraphIndexConfig(cfg?: OpenClawConfig) {
  return {
    ...resolveGraphIndexConfig(cfg),
    schemaVersion: CANONICAL_SCHEMA_VERSION,
    extractorVersion: EXTRACTOR_VERSION,
  };
}

export function isMemorySourceRef(sourceRef: string): boolean {
  const trimmed = sourceRef.trim();
  return trimmed === "MEMORY.md" || trimmed.startsWith("MEMORY.md#") || trimmed.startsWith("memory/");
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
  return {
    path: (match[1] ?? "").replaceAll("\\", "/").replace(/^\.\//, ""),
    startLine,
    endLine: Math.max(startLine, endLine),
  };
}
