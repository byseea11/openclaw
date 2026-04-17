import os from "node:os";
import path from "node:path";
import type { DatabaseSync, SQLInputValue } from "node:sqlite";
import {
  createSubsystemLogger,
  resolveStateDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { runV0ToV1Migration } from "./migrations/v0-to-v1.js";
import { runV1ToV2Migration } from "./migrations/v1-to-v2.js";
import { reduce } from "./reducer.js";
import {
  CANONICAL_SCHEMA_SQL,
  CANONICAL_SCHEMA_VERSION,
  type EntityAlias,
  EXTRACTOR_VERSION,
  type EntityState,
  type EventRecord,
  GRAPH_PROJECTION_VERSION,
  GRAPH_METRIC_KEYS,
  GRAPH_RECALL_TTL_MS,
  type GraphExportData,
  type GraphHit,
  type GraphMetricKey,
  type GraphMetricsSnapshot,
  parseSourceRef,
  type ProjectionInboxEntry,
  type ProjectionInboxWrite,
  type ProjectionSourceState,
  type RecentGraphCandidate,
} from "./schema.js";

const log = createSubsystemLogger("memory");
const stores = new Map<string, CanonicalStore>();

type EventRow = EventRecord & { fts_score?: number };
type GraphMetricRow = { key?: string; value?: number | string };
type PendingProjectionSummary = {
  source_kind: "transcript";
  source_id: string;
  pending_spans: number;
  pending_entries: number;
  estimated_tokens: number;
  strong_event: boolean;
  first_entry_id: string | null;
  last_entry_id: string | null;
  oldest_created_at: number;
};

function graphDbPathForAgent(agentId: string): string {
  return path.join(resolveStateDir(process.env, os.homedir), "memory", `${agentId}.graph.sqlite`);
}

function rowToEvent(row: Record<string, unknown>): EventRecord {
  const sourceType =
    row.source_type === "transcript" ||
    row.source_type === "tool_result" ||
    row.source_type === "flush" ||
    row.source_type === "flush_turn" ||
    row.source_type === "promotion" ||
    row.source_type === "memory_file"
      ? row.source_type === "flush_turn"
        ? "flush"
        : row.source_type
      : "memory_file";
  return {
    event_id: String(row.event_id),
    source_type: sourceType,
    source_ref: String(row.source_ref),
    occurred_at: String(row.occurred_at),
    entity_id: String(row.entity_id),
    actor: typeof row.actor === "string" ? row.actor : null,
    action: String(row.action),
    object: typeof row.object === "string" ? row.object : null,
    status_before: typeof row.status_before === "string" ? row.status_before : null,
    status_after: typeof row.status_after === "string" ? row.status_after : null,
    session_id: typeof row.session_id === "string" ? row.session_id : null,
    covered_until_entry_id:
      typeof row.covered_until_entry_id === "string" ? row.covered_until_entry_id : null,
    confidence: typeof row.confidence === "number" ? row.confidence : Number(row.confidence ?? 0.5),
    extractor_version: String(row.extractor_version),
    created_at: typeof row.created_at === "number" ? row.created_at : Number(row.created_at ?? 0),
  };
}

function rowToProjectionState(row: Record<string, unknown>): ProjectionSourceState {
  const status =
    row.status === "dirty" ||
    row.status === "draining" ||
    row.status === "failed" ||
    row.status === "clean"
      ? row.status
      : "clean";
  return {
    source_kind: "transcript",
    source_id: String(row.source_id),
    covered_until_entry_id:
      typeof row.covered_until_entry_id === "string" ? row.covered_until_entry_id : null,
    dirty_since_entry_id:
      typeof row.dirty_since_entry_id === "string" ? row.dirty_since_entry_id : null,
    last_projected_at:
      typeof row.last_projected_at === "number"
        ? row.last_projected_at
        : row.last_projected_at == null
          ? null
          : Number(row.last_projected_at),
    projection_version:
      typeof row.projection_version === "string" ? row.projection_version : GRAPH_PROJECTION_VERSION,
    status,
  };
}

function rowToProjectionInboxEntry(row: Record<string, unknown>): ProjectionInboxEntry {
  return {
    id: Number(row.id ?? 0),
    source_kind: "transcript",
    source_id: String(row.source_id),
    first_entry_id: String(row.first_entry_id),
    last_entry_id: String(row.last_entry_id),
    entries_json: String(row.entries_json),
    dirty_reason: String(row.dirty_reason),
    signal_strength: Number(row.signal_strength ?? 0),
    strong_event: Number(row.strong_event ?? 0) > 0,
    created_at: Number(row.created_at ?? 0),
    drained_at:
      typeof row.drained_at === "number"
        ? row.drained_at
        : row.drained_at == null
          ? null
          : Number(row.drained_at),
  };
}

function parseSupportingEventIds(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((entry): entry is string => typeof entry === "string");
  }
  if (typeof value !== "string" || !value.trim()) {
    return [];
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string")
      : [];
  } catch {
    return [];
  }
}

function rowToState(row: Record<string, unknown>): EntityState {
  return {
    entity_id: String(row.entity_id),
    latest_status: typeof row.latest_status === "string" ? row.latest_status : null,
    latest_owner: typeof row.latest_owner === "string" ? row.latest_owner : null,
    last_event_id: String(row.last_event_id),
    last_updated_at:
      typeof row.last_updated_at === "number"
        ? row.last_updated_at
        : Number(row.last_updated_at ?? 0),
    entity_type:
      row.entity_type === "task" ||
      row.entity_type === "project" ||
      row.entity_type === "person" ||
      row.entity_type === "decision"
        ? row.entity_type
        : "other",
    supporting_event_ids: parseSupportingEventIds(row.supporting_event_ids),
    confidence: typeof row.confidence === "number" ? row.confidence : Number(row.confidence ?? 0.5),
  };
}

function rowToRecentGraphCandidate(row: Record<string, unknown>): RecentGraphCandidate {
  return {
    session_key: String(row.session_key),
    source_ref: String(row.source_ref),
    path: String(row.path),
    start_line: Number(row.start_line ?? 0),
    end_line: Number(row.end_line ?? 0),
    entity_id: String(row.entity_id),
    hit_type: row.hit_type === "state" ? "state" : "event",
    query: typeof row.query === "string" ? row.query : null,
    first_returned_at: Number(row.first_returned_at ?? 0),
    last_returned_at: Number(row.last_returned_at ?? 0),
    expires_at: Number(row.expires_at ?? 0),
    used_at:
      typeof row.used_at === "number"
        ? row.used_at
        : row.used_at == null
          ? null
          : Number(row.used_at),
  };
}

function rowToEntityAlias(row: Record<string, unknown>): EntityAlias {
  return {
    alias_id: String(row.alias_id),
    canonical_id: String(row.canonical_id),
    source:
      row.source === "rule" || row.source === "manual" || row.source === "llm"
        ? row.source
        : "rule",
    created_at:
      typeof row.created_at === "number" ? row.created_at : Number(row.created_at ?? Date.now()),
  };
}

function quoteFtsToken(token: string): string {
  return `"${token.replaceAll('"', '""')}"`;
}

function buildFtsQuery(query: string): string {
  const tokens = query
    .split(/[^\p{L}\p{N}_-]+/u)
    .map((token) => token.trim())
    .filter(Boolean)
    .slice(0, 8);
  return tokens.map(quoteFtsToken).join(" OR ");
}

export class CanonicalStore {
  readonly dbPath: string;
  private readonly db: DatabaseSync;

  constructor(agentId: string, dbPath = graphDbPathForAgent(agentId)) {
    this.dbPath = dbPath;
    this.db = openMemoryDatabaseAtPath(dbPath, false);
    log.info(`canonical.store.open agent=${agentId} path=${dbPath}`);
    this.ensureSchema();
  }

  private ensureSchema(): void {
    this.db.exec(CANONICAL_SCHEMA_SQL);
    const currentSchemaVersion = this.getMeta("schema_version");
    if (currentSchemaVersion === "v0") {
      runV0ToV1Migration(this.db);
    }
    if (currentSchemaVersion === "v0" || currentSchemaVersion === "v1") {
      runV1ToV2Migration(this.db);
    }
    this.setMeta("schema_version", CANONICAL_SCHEMA_VERSION);
    this.setMeta("extractor_version", EXTRACTOR_VERSION);
    this.setMeta("projection_version", GRAPH_PROJECTION_VERSION);
    const ensureMetric = this.db.prepare(
      "INSERT OR IGNORE INTO graph_metrics(key, value) VALUES (?, 0)",
    );
    for (const key of GRAPH_METRIC_KEYS) {
      ensureMetric.run(key);
    }
    log.info("canonical.store.schema_ready");
  }

  close(): void {
    this.db.close();
  }

  getMeta(key: string): string | undefined {
    const row = this.db.prepare("SELECT value FROM meta WHERE key = ?").get(key) as
      | { value?: string }
      | undefined;
    return row?.value;
  }

  setMeta(key: string, value: string): void {
    this.db.prepare("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)").run(key, value);
  }

  reset(): void {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.db.exec("DELETE FROM event_fts");
      this.db.exec("DELETE FROM entity_states");
      this.db.exec("DELETE FROM entity_aliases");
      this.db.exec("DELETE FROM event_records");
      this.db.exec("DELETE FROM recent_graph_hits");
      this.db.exec("DELETE FROM source_projection_state");
      this.db.exec("DELETE FROM projection_inbox");
      this.db.exec("DELETE FROM graph_metrics");
      const ensureMetric = this.db.prepare(
        "INSERT OR IGNORE INTO graph_metrics(key, value) VALUES (?, 0)",
      );
      for (const key of GRAPH_METRIC_KEYS) {
        ensureMetric.run(key);
      }
      this.setMeta("schema_version", CANONICAL_SCHEMA_VERSION);
      this.setMeta("extractor_version", EXTRACTOR_VERSION);
      this.setMeta("projection_version", GRAPH_PROJECTION_VERSION);
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    log.info("canonical.store.reset");
  }

  bumpMetric(key: GraphMetricKey, delta = 1): number {
    this.db
      .prepare(
        `INSERT INTO graph_metrics(key, value)
         VALUES (?, ?)
         ON CONFLICT(key) DO UPDATE SET value = value + excluded.value`,
      )
      .run(key, delta);
    const row = this.db.prepare("SELECT value FROM graph_metrics WHERE key = ?").get(key) as
      | { value?: number | string }
      | undefined;
    return Number(row?.value ?? 0);
  }

  recordExtractorLatency(durationMs: number): void {
    const normalized = Number.isFinite(durationMs) ? Math.max(0, durationMs) : 0;
    this.bumpMetric("extractLatencyMsSum", normalized);
    this.bumpMetric("extractLatencyMsCount", 1);
  }

  getMetrics(): GraphMetricsSnapshot {
    const rows = this.db.prepare("SELECT key, value FROM graph_metrics").all() as GraphMetricRow[];
    const base = Object.fromEntries(GRAPH_METRIC_KEYS.map((key) => [key, 0])) as Record<
      GraphMetricKey,
      number
    >;
    let legacyHitsUsed: number | null = null;
    for (const row of rows) {
      const key = typeof row.key === "string" ? (row.key as GraphMetricKey) : null;
      if (key && key in base) {
        base[key] = Number(row.value ?? 0);
      } else if (row.key === "hitsUsed") {
        legacyHitsUsed = Number(row.value ?? 0);
      }
    }
    if (legacyHitsUsed !== null && base.hitsUsedRaw === 0 && base.hitsUsedUniqueRefs === 0) {
      base.hitsUsedRaw = legacyHitsUsed;
      base.hitsUsedUniqueRefs = legacyHitsUsed;
    }
    const count = base.extractLatencyMsCount;
    return {
      ...base,
      hitsUsed: base.hitsUsedUniqueRefs,
      extractLatencyMsAvg: count > 0 ? base.extractLatencyMsSum / count : 0,
    };
  }

  private deleteExpiredRecentHits(nowMs = Date.now()): void {
    this.db.prepare("DELETE FROM recent_graph_hits WHERE expires_at < ?").run(nowMs);
  }

  async upsertEvents(records: EventRecord[]): Promise<void> {
    if (records.length === 0) {
      log.info("canonical.store.upsert_events records=0");
      return;
    }
    const upsert = this.db.prepare(
      `INSERT OR REPLACE INTO event_records(
        event_id, source_type, source_ref, occurred_at, entity_id, actor, action, object,
        status_before, status_after, session_id, covered_until_entry_id, confidence,
        extractor_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const deleteFts = this.db.prepare("DELETE FROM event_fts WHERE event_id = ?");
    const insertFts = this.db.prepare(
      `INSERT INTO event_fts(event_id, entity_id, actor, action, object, status_after)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const record of records) {
        const values: SQLInputValue[] = [
          record.event_id,
          record.source_type,
          record.source_ref,
          record.occurred_at,
          record.entity_id,
          record.actor,
          record.action,
          record.object,
          record.status_before,
          record.status_after,
          record.session_id,
          record.covered_until_entry_id,
          record.confidence,
          record.extractor_version,
          record.created_at,
        ];
        upsert.run(...values);
        deleteFts.run(record.event_id);
        insertFts.run(
          record.event_id,
          record.entity_id,
          record.actor,
          record.action,
          record.object,
          record.status_after,
        );
      }
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    log.info(`canonical.store.upsert_events records=${records.length}`);
  }

  enqueueProjectionInbox(entry: ProjectionInboxWrite): boolean {
    const insert = this.db.prepare(
      `INSERT OR IGNORE INTO projection_inbox(
        source_kind, source_id, first_entry_id, last_entry_id, entries_json, dirty_reason,
        signal_strength, strong_event, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const upsertState = this.db.prepare(
      `INSERT INTO source_projection_state(
        source_kind, source_id, covered_until_entry_id, dirty_since_entry_id,
        last_projected_at, projection_version, status
      ) VALUES (?, ?, NULL, ?, NULL, ?, 'dirty')
      ON CONFLICT(source_kind, source_id) DO UPDATE SET
        dirty_since_entry_id = COALESCE(source_projection_state.dirty_since_entry_id, excluded.dirty_since_entry_id),
        projection_version = excluded.projection_version,
        status = 'dirty'`,
    );
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const result = insert.run(
        entry.source_kind,
        entry.source_id,
        entry.first_entry_id,
        entry.last_entry_id,
        entry.entries_json,
        entry.dirty_reason,
        entry.signal_strength,
        entry.strong_event ? 1 : 0,
        entry.created_at,
      );
      upsertState.run(
        entry.source_kind,
        entry.source_id,
        entry.first_entry_id,
        GRAPH_PROJECTION_VERSION,
      );
      this.db.exec("COMMIT");
      return result.changes > 0;
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  getProjectionState(sourceId: string): ProjectionSourceState | null {
    const row = this.db
      .prepare(
        `SELECT * FROM source_projection_state
         WHERE source_kind = 'transcript' AND source_id = ?`,
      )
      .get(sourceId) as Record<string, unknown> | undefined;
    return row ? rowToProjectionState(row) : null;
  }

  hasPendingProjection(sourceId?: string): boolean {
    const row = sourceId?.trim()
      ? (this.db
          .prepare(
            `SELECT 1 AS pending FROM projection_inbox
             WHERE source_kind = 'transcript' AND source_id = ? AND drained_at IS NULL
             LIMIT 1`,
          )
          .get(sourceId.trim()) as { pending?: number } | undefined)
      : (this.db
          .prepare(
            `SELECT 1 AS pending FROM projection_inbox
             WHERE source_kind = 'transcript' AND drained_at IS NULL
             LIMIT 1`,
          )
          .get() as { pending?: number } | undefined);
    return row?.pending === 1;
  }

  listPendingProjectionSummaries(sourceId?: string): PendingProjectionSummary[] {
    const sourceFilter = sourceId?.trim();
    const rows = sourceFilter
      ? (this.db
          .prepare(
            `SELECT
               source_kind,
               source_id,
               COUNT(*) AS pending_spans,
               SUM(json_array_length(entries_json)) AS pending_entries,
               SUM((LENGTH(entries_json) + 3) / 4) AS estimated_tokens,
               MAX(strong_event) AS strong_event,
               MIN(first_entry_id) AS first_entry_id,
               MAX(last_entry_id) AS last_entry_id,
               MIN(created_at) AS oldest_created_at
             FROM projection_inbox
             WHERE drained_at IS NULL AND source_kind = 'transcript' AND source_id = ?
             GROUP BY source_kind, source_id
             ORDER BY oldest_created_at ASC`,
          )
          .all(sourceFilter) as Array<Record<string, unknown>>)
      : (this.db
          .prepare(
            `SELECT
               source_kind,
               source_id,
               COUNT(*) AS pending_spans,
               SUM(json_array_length(entries_json)) AS pending_entries,
               SUM((LENGTH(entries_json) + 3) / 4) AS estimated_tokens,
               MAX(strong_event) AS strong_event,
               MIN(first_entry_id) AS first_entry_id,
               MAX(last_entry_id) AS last_entry_id,
               MIN(created_at) AS oldest_created_at
             FROM projection_inbox
             WHERE drained_at IS NULL AND source_kind = 'transcript'
             GROUP BY source_kind, source_id
             ORDER BY oldest_created_at ASC`,
          )
          .all() as Array<Record<string, unknown>>);
    return rows.map((row) => ({
      source_kind: "transcript",
      source_id: String(row.source_id),
      pending_spans: Number(row.pending_spans ?? 0),
      pending_entries: Number(row.pending_entries ?? 0),
      estimated_tokens: Number(row.estimated_tokens ?? 0),
      strong_event: Number(row.strong_event ?? 0) > 0,
      first_entry_id: typeof row.first_entry_id === "string" ? row.first_entry_id : null,
      last_entry_id: typeof row.last_entry_id === "string" ? row.last_entry_id : null,
      oldest_created_at: Number(row.oldest_created_at ?? 0),
    }));
  }

  listPendingProjectionInbox(sourceId?: string): ProjectionInboxEntry[] {
    const sourceFilter = sourceId?.trim();
    const rows = sourceFilter
      ? (this.db
          .prepare(
            `SELECT * FROM projection_inbox
             WHERE drained_at IS NULL AND source_kind = 'transcript' AND source_id = ?
             ORDER BY created_at ASC, id ASC`,
          )
          .all(sourceFilter) as Array<Record<string, unknown>>)
      : (this.db
          .prepare(
            `SELECT * FROM projection_inbox
             WHERE drained_at IS NULL AND source_kind = 'transcript'
             ORDER BY created_at ASC, id ASC`,
          )
          .all() as Array<Record<string, unknown>>);
    return rows.map(rowToProjectionInboxEntry);
  }

  markProjectionSourceDraining(sourceId: string): void {
    this.db
      .prepare(
        `UPDATE source_projection_state
         SET status = 'draining'
         WHERE source_kind = 'transcript' AND source_id = ?`,
      )
      .run(sourceId);
  }

  markProjectionDrained(params: { sourceId: string; coveredUntilEntryId: string; nowMs?: number }): void {
    const nowMs = Number.isFinite(params.nowMs) ? (params.nowMs as number) : Date.now();
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.db
        .prepare(
          `UPDATE projection_inbox
           SET drained_at = ?
           WHERE source_kind = 'transcript' AND source_id = ? AND drained_at IS NULL`,
        )
        .run(nowMs, params.sourceId);
      this.db
        .prepare(
          `INSERT INTO source_projection_state(
            source_kind, source_id, covered_until_entry_id, dirty_since_entry_id,
            last_projected_at, projection_version, status
          ) VALUES ('transcript', ?, ?, NULL, ?, ?, 'clean')
          ON CONFLICT(source_kind, source_id) DO UPDATE SET
            covered_until_entry_id = excluded.covered_until_entry_id,
            dirty_since_entry_id = NULL,
            last_projected_at = excluded.last_projected_at,
            projection_version = excluded.projection_version,
            status = 'clean'`,
        )
        .run(params.sourceId, params.coveredUntilEntryId, nowMs, GRAPH_PROJECTION_VERSION);
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  markProjectionFailed(sourceId: string): void {
    this.db
      .prepare(
        `UPDATE source_projection_state
         SET status = 'failed'
         WHERE source_kind = 'transcript' AND source_id = ?`,
      )
      .run(sourceId);
  }

  async refreshEntityStates(records: EventRecord[]): Promise<EntityState[]> {
    const entityIds = [...new Set(records.map((record) => record.entity_id))];
    const prevStates = new Map<string, EntityState>();
    for (const entityId of entityIds) {
      const state = await this.getEntityState(entityId);
      if (state) {
        prevStates.set(entityId, state);
      }
    }
    const states = reduce(records, prevStates);
    if (states.length === 0) {
      log.info("canonical.store.refresh_states states=0");
      return states;
    }
    const upsert = this.db.prepare(
      `INSERT OR REPLACE INTO entity_states(
        entity_id, latest_status, latest_owner, last_event_id, last_updated_at, entity_type,
        supporting_event_ids, confidence
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const state of states) {
        upsert.run(
          state.entity_id,
          state.latest_status,
          state.latest_owner,
          state.last_event_id,
          state.last_updated_at,
          state.entity_type,
          JSON.stringify(state.supporting_event_ids),
          state.confidence,
        );
      }
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    log.info(`canonical.store.refresh_states states=${states.length}`);
    return states;
  }

  async getEntityState(entityId: string): Promise<EntityState | null> {
    const row = this.db.prepare("SELECT * FROM entity_states WHERE entity_id = ?").get(entityId) as
      | Record<string, unknown>
      | undefined;
    return row ? rowToState(row) : null;
  }

  async searchEvents(query: string, limit: number): Promise<EventRow[]> {
    const ftsQuery = buildFtsQuery(query);
    if (!ftsQuery) {
      const rows = this.db
        .prepare("SELECT * FROM event_records ORDER BY occurred_at DESC, created_at DESC LIMIT ?")
        .all(Math.max(1, limit)) as Array<Record<string, unknown>>;
      return rows.map((row) => ({ ...rowToEvent(row), fts_score: 0 }));
    }
    try {
      const rows = this.db
        .prepare(
          `SELECT e.*, bm25(event_fts) AS fts_score
           FROM event_fts
           JOIN event_records e ON e.event_id = event_fts.event_id
           WHERE event_fts MATCH ?
           ORDER BY fts_score
           LIMIT ?`,
        )
        .all(ftsQuery, Math.max(1, limit)) as Array<Record<string, unknown>>;
      return rows.map((row) => ({
        ...rowToEvent(row),
        fts_score: typeof row.fts_score === "number" ? row.fts_score : Number(row.fts_score ?? 0),
      }));
    } catch (err) {
      log.warn(`canonical.search fts_failed ${String(err)}`);
      return [];
    }
  }

  recordRecentGraphHits(params: {
    sessionKey: string;
    query: string;
    hits: GraphHit[];
    ttlMs?: number;
    nowMs?: number;
  }): number {
    const sessionKey = params.sessionKey.trim();
    if (!sessionKey || params.hits.length === 0) {
      return 0;
    }
    const nowMs = Number.isFinite(params.nowMs) ? (params.nowMs as number) : Date.now();
    const ttlMs = Number.isFinite(params.ttlMs)
      ? Math.max(1, params.ttlMs as number)
      : GRAPH_RECALL_TTL_MS;
    this.deleteExpiredRecentHits(nowMs);
    const upsert = this.db.prepare(
      `INSERT INTO recent_graph_hits(
        session_key, source_ref, path, start_line, end_line, entity_id, hit_type, query,
        first_returned_at, last_returned_at, expires_at, used_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
      ON CONFLICT(session_key, source_ref, path, start_line, end_line, hit_type)
      DO UPDATE SET
        query = excluded.query,
        last_returned_at = excluded.last_returned_at,
        expires_at = excluded.expires_at`,
    );
    let recorded = 0;
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const hit of params.hits) {
        const parsed = parseSourceRef(hit.source_ref);
        if (!parsed) {
          continue;
        }
        upsert.run(
          sessionKey,
          hit.source_ref,
          parsed.path,
          parsed.startLine,
          parsed.endLine,
          hit.entity_id,
          hit.type,
          params.query,
          nowMs,
          nowMs,
          nowMs + ttlMs,
        );
        recorded += 1;
      }
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    return recorded;
  }

  markRecentGraphHitsUsedByRead(params: {
    sessionKey: string;
    path: string;
    from?: number;
    lines?: number;
    nowMs?: number;
  }): RecentGraphCandidate[] {
    const sessionKey = params.sessionKey.trim();
    if (!sessionKey) {
      return [];
    }
    const nowMs = Number.isFinite(params.nowMs) ? (params.nowMs as number) : Date.now();
    this.deleteExpiredRecentHits(nowMs);
    const startLine = Number.isFinite(params.from)
      ? Math.max(1, Math.floor(params.from as number))
      : 1;
    const requestedLines = Number.isFinite(params.lines)
      ? Math.max(1, Math.floor(params.lines as number))
      : Number.MAX_SAFE_INTEGER;
    const endLine =
      requestedLines === Number.MAX_SAFE_INTEGER
        ? Number.MAX_SAFE_INTEGER
        : startLine + requestedLines - 1;
    const rows = this.db
      .prepare(
        `SELECT * FROM recent_graph_hits
         WHERE session_key = ?
           AND path = ?
           AND expires_at >= ?
           AND end_line >= ?
           AND start_line <= ?`,
      )
      .all(sessionKey, params.path, nowMs, startLine, endLine) as Array<Record<string, unknown>>;
    if (rows.length === 0) {
      return [];
    }
    this.db
      .prepare(
        `UPDATE recent_graph_hits
         SET used_at = ?
         WHERE session_key = ?
           AND path = ?
           AND expires_at >= ?
           AND end_line >= ?
           AND start_line <= ?`,
      )
      .run(nowMs, sessionKey, params.path, nowMs, startLine, endLine);
    return rows.map(rowToRecentGraphCandidate);
  }

  markRecentGraphHitsUsedBySourceRefs(params: {
    sessionKey: string;
    sourceRefs: string[];
    nowMs?: number;
  }): RecentGraphCandidate[] {
    const sessionKey = params.sessionKey.trim();
    const sourceRefs = [...new Set(params.sourceRefs.map((value) => value.trim()).filter(Boolean))];
    if (!sessionKey || sourceRefs.length === 0) {
      return [];
    }
    const nowMs = Number.isFinite(params.nowMs) ? (params.nowMs as number) : Date.now();
    this.deleteExpiredRecentHits(nowMs);
    const placeholders = sourceRefs.map(() => "?").join(", ");
    const rows = this.db
      .prepare(
        `SELECT * FROM recent_graph_hits
         WHERE session_key = ?
           AND expires_at >= ?
           AND source_ref IN (${placeholders})`,
      )
      .all(sessionKey, nowMs, ...sourceRefs) as Array<Record<string, unknown>>;
    if (rows.length === 0) {
      return [];
    }
    this.db
      .prepare(
        `UPDATE recent_graph_hits
         SET used_at = ?
         WHERE session_key = ?
           AND expires_at >= ?
           AND source_ref IN (${placeholders})`,
      )
      .run(nowMs, sessionKey, nowMs, ...sourceRefs);
    return rows.map(rowToRecentGraphCandidate);
  }

  getRecentGraphHits(sessionKey: string, nowMs = Date.now()): RecentGraphCandidate[] {
    if (!sessionKey.trim()) {
      return [];
    }
    this.deleteExpiredRecentHits(nowMs);
    const rows = this.db
      .prepare(
        `SELECT * FROM recent_graph_hits
         WHERE session_key = ?
         ORDER BY last_returned_at DESC, source_ref ASC`,
      )
      .all(sessionKey) as Array<Record<string, unknown>>;
    return rows.map(rowToRecentGraphCandidate);
  }

  getStatus() {
    const eventRow = this.db.prepare("SELECT COUNT(*) AS count FROM event_records").get() as {
      count?: number;
    };
    const entityRow = this.db.prepare("SELECT COUNT(*) AS count FROM entity_states").get() as {
      count?: number;
    };
    const pendingProjectionRow = this.db
      .prepare(
        `SELECT COUNT(*) AS count FROM projection_inbox
         WHERE source_kind = 'transcript' AND drained_at IS NULL`,
      )
      .get() as { count?: number } | undefined;
    return {
      dbPath: this.dbPath,
      eventsTotal: eventRow.count ?? 0,
      entitiesTotal: entityRow.count ?? 0,
      schemaVersion: this.getMeta("schema_version") ?? CANONICAL_SCHEMA_VERSION,
      extractorVersion: this.getMeta("extractor_version") ?? EXTRACTOR_VERSION,
      projectionVersion: this.getMeta("projection_version") ?? GRAPH_PROJECTION_VERSION,
      pendingProjectionSpans: pendingProjectionRow?.count ?? 0,
      metrics: this.getMetrics(),
    };
  }

  async exportData(): Promise<GraphExportData> {
    const eventRows = this.db
      .prepare("SELECT * FROM event_records ORDER BY occurred_at, event_id")
      .all() as Array<Record<string, unknown>>;
    const stateRows = this.db
      .prepare("SELECT * FROM entity_states ORDER BY entity_id")
      .all() as Array<Record<string, unknown>>;
    return {
      events: eventRows.map(rowToEvent),
      states: stateRows.map(rowToState),
      metrics: this.getMetrics(),
    };
  }

  async exportJsonl(): Promise<string> {
    const exported = await this.exportData();
    return [
      ...exported.events.map((row) => JSON.stringify({ type: "event", ...row })),
      ...exported.states.map((row) => JSON.stringify({ type: "state", ...row })),
    ].join("\n");
  }

  listAliases(canonicalId?: string): EntityAlias[] {
    const rows =
      canonicalId && canonicalId.trim()
        ? (this.db
            .prepare("SELECT * FROM entity_aliases WHERE canonical_id = ? ORDER BY alias_id ASC")
            .all(canonicalId.trim()) as Array<Record<string, unknown>>)
        : (this.db
            .prepare("SELECT * FROM entity_aliases ORDER BY canonical_id ASC, alias_id ASC")
            .all() as Array<Record<string, unknown>>);
    return rows.map(rowToEntityAlias);
  }
}

export function getCanonicalStore(agentId: string): CanonicalStore {
  const cached = stores.get(agentId);
  if (cached) {
    return cached;
  }
  const store = new CanonicalStore(agentId);
  stores.set(agentId, store);
  return store;
}

export async function closeAllCanonicalStores(): Promise<void> {
  const count = stores.size;
  for (const store of stores.values()) {
    store.close();
  }
  stores.clear();
  log.info(`canonical.store.close_all count=${count}`);
}
