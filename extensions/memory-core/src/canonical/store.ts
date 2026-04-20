import os from "node:os";
import path from "node:path";
import type { DatabaseSync } from "node:sqlite";
import {
  createSubsystemLogger,
  resolveStateDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { generateUlid } from "./id-v2.js";
import { runV0ToV1Migration } from "./migrations/v0-to-v1.js";
import { runV1ToV2Migration } from "./migrations/v1-to-v2.js";
import { runV2ToV3Migration } from "./migrations/v2-to-v3.js";
import { runV3ToV4Migration } from "./migrations/v3-to-v4.js";
import { runV4ToV5Migration } from "./migrations/v4-to-v5.js";
import { runV5ToV6Migration } from "./migrations/v5-to-v6.js";
import { deriveGraphEdgeMutationsV2, reopenOrCreateEdgeV2 } from "./projector-edges-v2.js";
import { deriveGraphEntitiesV2 } from "./projector-entities-v2.js";
import { deriveWorkflowPatchesV2, type WorkflowSlotVersionV2 } from "./projector-workflow-v2.js";
import {
  buildEventFingerprint,
  EVENT_TYPE_REGISTRY_SEED,
  type EvidenceRecordV2,
  type EventRecordV2,
  type GraphEdgeV2,
  type GraphEntityV2,
  type WorkflowStateViewV2,
} from "./schema-v2.js";
import {
  CANONICAL_SCHEMA_SQL,
  CANONICAL_SCHEMA_VERSION,
  EXTRACTOR_VERSION,
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
      typeof row.projection_version === "string"
        ? row.projection_version
        : GRAPH_PROJECTION_VERSION,
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

function parseStringArray(value: unknown): string[] {
  return [...new Set(parseSupportingEventIds(value))];
}

function rowToEvidenceV2(row: Record<string, unknown>): EvidenceRecordV2 {
  return {
    evidence_id: String(row.evidence_id),
    evidence_fingerprint: String(row.evidence_fingerprint),
    source_platform: String(row.source_platform) as EvidenceRecordV2["source_platform"],
    source_kind: String(row.source_kind) as EvidenceRecordV2["source_kind"],
    session_key: typeof row.session_key === "string" ? row.session_key : null,
    message_id: typeof row.message_id === "string" ? row.message_id : null,
    chat_id: typeof row.chat_id === "string" ? row.chat_id : null,
    chat_type: typeof row.chat_type === "string" ? row.chat_type : null,
    thread_id: typeof row.thread_id === "string" ? row.thread_id : null,
    root_id: typeof row.root_id === "string" ? row.root_id : null,
    parent_id: typeof row.parent_id === "string" ? row.parent_id : null,
    first_entry_id: typeof row.first_entry_id === "string" ? row.first_entry_id : null,
    last_entry_id: typeof row.last_entry_id === "string" ? row.last_entry_id : null,
    content_text: typeof row.content_text === "string" ? row.content_text : null,
    content_json: typeof row.content_json === "string" ? row.content_json : "{}",
    source_locator_json:
      typeof row.source_locator_json === "string" ? row.source_locator_json : "{}",
    occurred_at: typeof row.occurred_at === "string" ? row.occurred_at : null,
    created_at: Number(row.created_at ?? 0),
  };
}

function rowToEventV2(row: Record<string, unknown>): EventRecordV2 {
  return {
    event_id: String(row.event_id),
    event_fingerprint: String(row.event_fingerprint),
    evidence_id: String(row.evidence_id),
    event_type: String(row.event_type) as EventRecordV2["event_type"],
    subject_ref: String(row.subject_ref),
    actor_ref: typeof row.actor_ref === "string" ? row.actor_ref : null,
    object_ref: typeof row.object_ref === "string" ? row.object_ref : null,
    related_refs_json: typeof row.related_refs_json === "string" ? row.related_refs_json : "[]",
    occurred_at: String(row.occurred_at),
    payload_json: typeof row.payload_json === "string" ? row.payload_json : "{}",
    confidence: Number(row.confidence ?? 0.5),
    extraction_version: String(row.extraction_version),
    created_at: Number(row.created_at ?? 0),
  };
}

function rowToWorkflowStateV2(row: Record<string, unknown>): WorkflowStateViewV2 {
  return {
    task_ref: String(row.task_ref),
    current_owner_ref: typeof row.current_owner_ref === "string" ? row.current_owner_ref : null,
    current_stage: typeof row.current_stage === "string" ? row.current_stage : null,
    current_approval_ref:
      typeof row.current_approval_ref === "string" ? row.current_approval_ref : null,
    approval_status: typeof row.approval_status === "string" ? row.approval_status : null,
    current_blocker_ref:
      typeof row.current_blocker_ref === "string" ? row.current_blocker_ref : null,
    next_action_json: typeof row.next_action_json === "string" ? row.next_action_json : "{}",
    last_event_id: String(row.last_event_id),
    last_event_time: String(row.last_event_time),
    slot_versions_json: typeof row.slot_versions_json === "string" ? row.slot_versions_json : "{}",
    supporting_event_ids:
      typeof row.supporting_event_ids === "string" ? row.supporting_event_ids : "[]",
    updated_at: Number(row.updated_at ?? 0),
  };
}

function rowToGraphEntityV2(row: Record<string, unknown>): GraphEntityV2 {
  return {
    entity_ref: String(row.entity_ref),
    entity_type: String(row.entity_type) as GraphEntityV2["entity_type"],
    canonical_name: String(row.canonical_name),
    alias_json: typeof row.alias_json === "string" ? row.alias_json : "[]",
    first_seen_at: String(row.first_seen_at),
    last_seen_at: String(row.last_seen_at),
    last_evidence_id: typeof row.last_evidence_id === "string" ? row.last_evidence_id : null,
    updated_at: Number(row.updated_at ?? 0),
  };
}

function rowToGraphEdgeV2(row: Record<string, unknown>): GraphEdgeV2 {
  return {
    edge_id: String(row.edge_id),
    edge_key: String(row.edge_key),
    src_ref: String(row.src_ref),
    edge_type: String(row.edge_type) as GraphEdgeV2["edge_type"],
    dst_ref: String(row.dst_ref),
    derived_from_event_id: String(row.derived_from_event_id),
    active: Number(row.active ?? 0) > 0 ? 1 : 0,
    valid_from: String(row.valid_from),
    valid_to: typeof row.valid_to === "string" ? row.valid_to : null,
    updated_at: Number(row.updated_at ?? 0),
  };
}

function parseSlotVersionsV2(value: string): Record<string, WorkflowSlotVersionV2> {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const result: Record<string, WorkflowSlotVersionV2> = {};
    for (const [slot, raw] of Object.entries(parsed)) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        continue;
      }
      const record = raw as Record<string, unknown>;
      if (
        typeof record.event_id === "string" &&
        typeof record.event_fingerprint === "string" &&
        typeof record.occurred_at === "string"
      ) {
        result[slot] = {
          event_id: record.event_id,
          event_fingerprint: record.event_fingerprint,
          occurred_at: record.occurred_at,
        };
      }
    }
    return result;
  } catch {
    return {};
  }
}

function rowToRecentGraphCandidate(row: Record<string, unknown>): RecentGraphCandidate {
  return {
    session_key: String(row.session_key),
    source_ref: String(row.source_ref),
    path: String(row.path),
    start_line: Number(row.start_line ?? 0),
    end_line: Number(row.end_line ?? 0),
    entity_id: String(row.entity_id),
    hit_type: row.hit_type === "state" || row.hit_type === "edge" ? row.hit_type : "event",
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
    if (
      currentSchemaVersion === "v0" ||
      currentSchemaVersion === "v1" ||
      currentSchemaVersion === "v2"
    ) {
      runV2ToV3Migration(this.db);
    }
    if (
      currentSchemaVersion === "v0" ||
      currentSchemaVersion === "v1" ||
      currentSchemaVersion === "v2" ||
      currentSchemaVersion === "v3"
    ) {
      runV3ToV4Migration(this.db);
    }
    if (
      currentSchemaVersion === "v0" ||
      currentSchemaVersion === "v1" ||
      currentSchemaVersion === "v2" ||
      currentSchemaVersion === "v3" ||
      currentSchemaVersion === "v4"
    ) {
      runV4ToV5Migration(this.db);
    }
    if (
      currentSchemaVersion === "v0" ||
      currentSchemaVersion === "v1" ||
      currentSchemaVersion === "v2" ||
      currentSchemaVersion === "v3" ||
      currentSchemaVersion === "v4" ||
      currentSchemaVersion === "v5"
    ) {
      runV5ToV6Migration(this.db);
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
    this.seedEventTypeRegistryV2();
    log.info("canonical.store.schema_ready");
  }

  private seedEventTypeRegistryV2(): void {
    const insert = this.db.prepare(
      `INSERT OR IGNORE INTO event_type_registry(
        event_type, subject_type, object_type, payload_schema_json, description, enabled, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)`,
    );
    const nowMs = Date.now();
    for (const record of EVENT_TYPE_REGISTRY_SEED) {
      insert.run(
        record.event_type,
        record.subject_type,
        record.object_type,
        record.payload_schema_json,
        record.description,
        record.enabled,
        record.created_at ?? nowMs,
      );
    }
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
      this.db.exec("DELETE FROM graph_edges_v2");
      this.db.exec("DELETE FROM graph_entities_v2");
      this.db.exec("DELETE FROM workflow_state_view_v2");
      this.db.exec("DELETE FROM event_records_v2");
      this.db.exec("DELETE FROM event_type_registry");
      this.db.exec("DELETE FROM evidence_records");
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
      this.seedEventTypeRegistryV2();
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

  markProjectionDrained(params: {
    sourceId: string;
    coveredUntilEntryId: string;
    nowMs?: number;
  }): void {
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

  recordKgRetryMarker(params: {
    scope: string;
    status: "failed" | "running" | "complete" | "idle";
    error?: string;
    retryMarker?: Record<string, unknown>;
    lastEventCreatedAt?: number | null;
    lastEventId?: string | null;
    nowMs?: number;
  }): void {
    void params;
  }

  listProjectionStates(): ProjectionSourceState[] {
    const rows = this.db
      .prepare("SELECT * FROM source_projection_state ORDER BY source_id ASC")
      .all() as Array<Record<string, unknown>>;
    return rows.map(rowToProjectionState);
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

  private getEvidenceByFingerprintInTransaction(fingerprint: string): EvidenceRecordV2 | null {
    const row = this.db
      .prepare("SELECT * FROM evidence_records WHERE evidence_fingerprint = ?")
      .get(fingerprint) as Record<string, unknown> | undefined;
    return row ? rowToEvidenceV2(row) : null;
  }

  private upsertEvidenceRecordV2InTransaction(evidence: EvidenceRecordV2): EvidenceRecordV2 {
    const existing = this.getEvidenceByFingerprintInTransaction(evidence.evidence_fingerprint);
    if (existing) {
      this.db
        .prepare(
          `UPDATE evidence_records
           SET message_id = COALESCE(message_id, ?),
               thread_id = COALESCE(thread_id, ?),
               root_id = COALESCE(root_id, ?),
               parent_id = COALESCE(parent_id, ?),
               content_json = CASE
                 WHEN content_json = '{}' AND ? <> '{}' THEN ?
                 ELSE content_json
               END
           WHERE evidence_id = ?`,
        )
        .run(
          evidence.message_id,
          evidence.thread_id,
          evidence.root_id,
          evidence.parent_id,
          evidence.content_json,
          evidence.content_json,
          existing.evidence_id,
        );
      const refreshed = this.db
        .prepare("SELECT * FROM evidence_records WHERE evidence_id = ?")
        .get(existing.evidence_id) as Record<string, unknown>;
      return rowToEvidenceV2(refreshed);
    }
    const persisted: EvidenceRecordV2 = {
      ...evidence,
      evidence_id: evidence.evidence_id || generateUlid(),
      created_at: evidence.created_at || Date.now(),
    };
    this.db
      .prepare(
        `INSERT INTO evidence_records(
          evidence_id, evidence_fingerprint, source_platform, source_kind, session_key, message_id,
          chat_id, chat_type, thread_id, root_id, parent_id, first_entry_id, last_entry_id,
          content_text, content_json, source_locator_json, occurred_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        persisted.evidence_id,
        persisted.evidence_fingerprint,
        persisted.source_platform,
        persisted.source_kind,
        persisted.session_key,
        persisted.message_id,
        persisted.chat_id,
        persisted.chat_type,
        persisted.thread_id,
        persisted.root_id,
        persisted.parent_id,
        persisted.first_entry_id,
        persisted.last_entry_id,
        persisted.content_text,
        persisted.content_json,
        persisted.source_locator_json,
        persisted.occurred_at,
        persisted.created_at,
      );
    return persisted;
  }

  private insertEventsV2InTransaction(events: EventRecordV2[]): EventRecordV2[] {
    const inserted: EventRecordV2[] = [];
    const lookup = this.db.prepare("SELECT * FROM event_records_v2 WHERE event_fingerprint = ?");
    const insert = this.db.prepare(
      `INSERT INTO event_records_v2(
        event_id, event_fingerprint, evidence_id, event_type, subject_ref, actor_ref, object_ref,
        related_refs_json, occurred_at, payload_json, confidence, extraction_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    for (const event of events) {
      const existing = lookup.get(event.event_fingerprint) as Record<string, unknown> | undefined;
      if (existing) {
        inserted.push(rowToEventV2(existing));
        continue;
      }
      const persisted: EventRecordV2 = {
        ...event,
        event_id: event.event_id || generateUlid(),
        created_at: event.created_at || Date.now(),
      };
      insert.run(
        persisted.event_id,
        persisted.event_fingerprint,
        persisted.evidence_id,
        persisted.event_type,
        persisted.subject_ref,
        persisted.actor_ref,
        persisted.object_ref,
        persisted.related_refs_json,
        persisted.occurred_at,
        persisted.payload_json,
        persisted.confidence,
        persisted.extraction_version,
        persisted.created_at,
      );
      inserted.push(persisted);
    }
    return inserted;
  }

  private getWorkflowStateV2InTransaction(taskRef: string): WorkflowStateViewV2 | null {
    const row = this.db
      .prepare("SELECT * FROM workflow_state_view_v2 WHERE task_ref = ?")
      .get(taskRef) as Record<string, unknown> | undefined;
    return row ? rowToWorkflowStateV2(row) : null;
  }

  private upsertWorkflowStateV2InTransaction(events: EventRecordV2[]): WorkflowStateViewV2[] {
    const patches = deriveWorkflowPatchesV2(events);
    const grouped = new Map<string, typeof patches>();
    for (const patch of patches) {
      const list = grouped.get(patch.task_ref) ?? [];
      list.push(patch);
      grouped.set(patch.task_ref, list);
    }
    const results: WorkflowStateViewV2[] = [];
    for (const [taskRef, taskPatches] of grouped.entries()) {
      let state =
        this.getWorkflowStateV2InTransaction(taskRef) ??
        ({
          task_ref: taskRef,
          current_owner_ref: null,
          current_stage: null,
          current_approval_ref: null,
          approval_status: null,
          current_blocker_ref: null,
          next_action_json: "{}",
          last_event_id: taskPatches[0].event.event_id,
          last_event_time: taskPatches[0].event.occurred_at,
          slot_versions_json: "{}",
          supporting_event_ids: "[]",
          updated_at: Date.now(),
        } satisfies WorkflowStateViewV2);
      const slotVersions = parseSlotVersionsV2(state.slot_versions_json);
      const supportingIds = new Set(parseStringArray(state.supporting_event_ids));
      taskPatches.sort(
        (left, right) =>
          left.event.occurred_at.localeCompare(right.event.occurred_at) ||
          left.event.event_fingerprint.localeCompare(right.event.event_fingerprint),
      );
      for (const patch of taskPatches) {
        supportingIds.add(patch.event.event_id);
        for (const slot of patch.slots) {
          const previous = slotVersions[slot];
          const nextKey = `${patch.event.occurred_at}|${patch.event.event_fingerprint}`;
          const previousKey = previous
            ? `${previous.occurred_at}|${previous.event_fingerprint}`
            : "";
          if (!previous || nextKey >= previousKey) {
            (state as Record<string, unknown>)[slot] = patch.set[slot] ?? null;
            slotVersions[slot] = {
              event_id: patch.event.event_id,
              event_fingerprint: patch.event.event_fingerprint,
              occurred_at: patch.event.occurred_at,
            };
          }
        }
        const lastKey = `${state.last_event_time}|${state.last_event_id}`;
        const eventKey = `${patch.event.occurred_at}|${patch.event.event_id}`;
        if (eventKey >= lastKey) {
          state.last_event_id = patch.event.event_id;
          state.last_event_time = patch.event.occurred_at;
        }
      }
      state.slot_versions_json = JSON.stringify(slotVersions);
      state.supporting_event_ids = JSON.stringify([...supportingIds]);
      state.updated_at = Date.now();
      this.db
        .prepare(
          `INSERT INTO workflow_state_view_v2(
            task_ref, current_owner_ref, current_stage, current_approval_ref, approval_status,
            current_blocker_ref, next_action_json, last_event_id, last_event_time,
            slot_versions_json, supporting_event_ids, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(task_ref) DO UPDATE SET
            current_owner_ref = excluded.current_owner_ref,
            current_stage = excluded.current_stage,
            current_approval_ref = excluded.current_approval_ref,
            approval_status = excluded.approval_status,
            current_blocker_ref = excluded.current_blocker_ref,
            next_action_json = excluded.next_action_json,
            last_event_id = excluded.last_event_id,
            last_event_time = excluded.last_event_time,
            slot_versions_json = excluded.slot_versions_json,
            supporting_event_ids = excluded.supporting_event_ids,
            updated_at = excluded.updated_at`,
        )
        .run(
          state.task_ref,
          state.current_owner_ref,
          state.current_stage,
          state.current_approval_ref,
          state.approval_status,
          state.current_blocker_ref,
          state.next_action_json,
          state.last_event_id,
          state.last_event_time,
          state.slot_versions_json,
          state.supporting_event_ids,
          state.updated_at,
        );
      results.push(state);
    }
    return results;
  }

  private upsertGraphEntitiesV2InTransaction(
    evidence: EvidenceRecordV2,
    events: EventRecordV2[],
  ): GraphEntityV2[] {
    const entities = deriveGraphEntitiesV2(evidence, events);
    const upsert = this.db.prepare(
      `INSERT INTO graph_entities_v2(
        entity_ref, entity_type, canonical_name, alias_json, first_seen_at, last_seen_at,
        last_evidence_id, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(entity_ref) DO UPDATE SET
        entity_type = excluded.entity_type,
        canonical_name = excluded.canonical_name,
        alias_json = excluded.alias_json,
        first_seen_at = MIN(graph_entities_v2.first_seen_at, excluded.first_seen_at),
        last_seen_at = MAX(graph_entities_v2.last_seen_at, excluded.last_seen_at),
        last_evidence_id = excluded.last_evidence_id,
        updated_at = excluded.updated_at`,
    );
    for (const entity of entities) {
      upsert.run(
        entity.entity_ref,
        entity.entity_type,
        entity.canonical_name,
        entity.alias_json,
        entity.first_seen_at,
        entity.last_seen_at,
        entity.last_evidence_id,
        entity.updated_at,
      );
    }
    return entities;
  }

  private upsertGraphEdgesV2InTransaction(events: EventRecordV2[]): GraphEdgeV2[] {
    const mutations = deriveGraphEdgeMutationsV2(events);
    if (mutations.closes.length > 0) {
      const close = this.db.prepare(
        `UPDATE graph_edges_v2
         SET active = 0, valid_to = ?, updated_at = ?
         WHERE src_ref = ? AND edge_type = ? AND active = 1`,
      );
      for (const mutation of mutations.closes) {
        close.run(mutation.closed_at, Date.now(), mutation.src_ref, mutation.edge_type);
      }
    }
    const persisted: GraphEdgeV2[] = [];
    const lookup = this.db.prepare("SELECT * FROM graph_edges_v2 WHERE edge_key = ?");
    const insert = this.db.prepare(
      `INSERT INTO graph_edges_v2(
        edge_id, edge_key, src_ref, edge_type, dst_ref, derived_from_event_id, active,
        valid_from, valid_to, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const update = this.db.prepare(
      `UPDATE graph_edges_v2
       SET src_ref = ?, edge_type = ?, dst_ref = ?, derived_from_event_id = ?, active = ?,
           valid_from = ?, valid_to = ?, updated_at = ?
       WHERE edge_key = ?`,
    );
    for (const mutation of mutations.upserts) {
      const existingRow = lookup.get(mutation.edge_key) as Record<string, unknown> | undefined;
      const existing = existingRow ? rowToGraphEdgeV2(existingRow) : null;
      const next = reopenOrCreateEdgeV2({ existing, upsert: mutation });
      const edgeId = existing?.edge_id || generateUlid();
      if (existing) {
        update.run(
          next.src_ref,
          next.edge_type,
          next.dst_ref,
          next.derived_from_event_id,
          next.active,
          next.valid_from,
          next.valid_to,
          next.updated_at,
          next.edge_key,
        );
      } else {
        insert.run(
          edgeId,
          next.edge_key,
          next.src_ref,
          next.edge_type,
          next.dst_ref,
          next.derived_from_event_id,
          next.active,
          next.valid_from,
          next.valid_to,
          next.updated_at,
        );
      }
      persisted.push({ ...next, edge_id: edgeId });
    }
    return persisted;
  }

  async persistSemanticBatchV2(params: {
    evidence: EvidenceRecordV2;
    events: EventRecordV2[];
  }): Promise<{
    evidence: EvidenceRecordV2;
    events: EventRecordV2[];
    states: WorkflowStateViewV2[];
    entities: GraphEntityV2[];
    edges: GraphEdgeV2[];
  }> {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const evidence = this.upsertEvidenceRecordV2InTransaction(params.evidence);
      const normalizedEvents = params.events.map((event) => {
        const payloadJson = (() => {
          try {
            return JSON.parse(event.payload_json) as unknown;
          } catch {
            return {};
          }
        })();
        return {
          ...event,
          evidence_id: evidence.evidence_id,
          event_fingerprint: buildEventFingerprint({
            evidenceId: evidence.evidence_id,
            eventType: event.event_type,
            subjectRef: event.subject_ref,
            objectRef: event.object_ref,
            occurredAt: event.occurred_at,
            payloadJson,
          }),
        };
      });
      const events = this.insertEventsV2InTransaction(normalizedEvents);
      const entities = this.upsertGraphEntitiesV2InTransaction(evidence, events);
      const states = this.upsertWorkflowStateV2InTransaction(events);
      const edges = this.upsertGraphEdgesV2InTransaction(events);
      this.db.exec("COMMIT");
      return { evidence, events, states, entities, edges };
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  getEvidenceByIdV2(evidenceId: string): EvidenceRecordV2 | null {
    const row = this.db
      .prepare("SELECT * FROM evidence_records WHERE evidence_id = ?")
      .get(evidenceId) as Record<string, unknown> | undefined;
    return row ? rowToEvidenceV2(row) : null;
  }

  getEventByIdV2(eventId: string): EventRecordV2 | null {
    const row = this.db
      .prepare("SELECT * FROM event_records_v2 WHERE event_id = ?")
      .get(eventId) as Record<string, unknown> | undefined;
    return row ? rowToEventV2(row) : null;
  }

  getEventsByIdsV2(eventIds: string[]): EventRecordV2[] {
    const unique = [...new Set(eventIds.filter(Boolean))];
    if (unique.length === 0) {
      return [];
    }
    const placeholders = unique.map(() => "?").join(", ");
    const rows = this.db
      .prepare(`SELECT * FROM event_records_v2 WHERE event_id IN (${placeholders})`)
      .all(...unique) as Array<Record<string, unknown>>;
    return rows.map(rowToEventV2);
  }

  getWorkflowStateV2(taskRef: string): WorkflowStateViewV2 | null {
    return this.getWorkflowStateV2InTransaction(taskRef);
  }

  listWorkflowStatesV2(filters?: {
    ownerRef?: string;
    stage?: string;
    approvalStatus?: string;
  }): WorkflowStateViewV2[] {
    const clauses: string[] = [];
    const values: string[] = [];
    if (filters?.ownerRef) {
      clauses.push("current_owner_ref = ?");
      values.push(filters.ownerRef);
    }
    if (filters?.stage) {
      clauses.push("current_stage = ?");
      values.push(filters.stage);
    }
    if (filters?.approvalStatus) {
      clauses.push("approval_status = ?");
      values.push(filters.approvalStatus);
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const rows = this.db
      .prepare(
        `SELECT * FROM workflow_state_view_v2 ${where} ORDER BY updated_at DESC, task_ref ASC`,
      )
      .all(...values) as Array<Record<string, unknown>>;
    return rows.map(rowToWorkflowStateV2);
  }

  listEventsForRefV2(ref: string, limit = 50): EventRecordV2[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM event_records_v2
         WHERE subject_ref = ?
            OR object_ref = ?
            OR related_refs_json LIKE ?
         ORDER BY occurred_at ASC, created_at ASC
         LIMIT ?`,
      )
      .all(ref, ref, `%${ref}%`, Math.max(1, limit)) as Array<Record<string, unknown>>;
    return rows.map(rowToEventV2);
  }

  listActiveEdgesForRefV2(ref: string): GraphEdgeV2[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM graph_edges_v2
         WHERE active = 1 AND (src_ref = ? OR dst_ref = ?)
         ORDER BY edge_type ASC, src_ref ASC, dst_ref ASC`,
      )
      .all(ref, ref) as Array<Record<string, unknown>>;
    return rows.map(rowToGraphEdgeV2);
  }

  findEntityMatchesV2(query: string, limit = 10): GraphEntityV2[] {
    const normalized = query.trim();
    if (!normalized) {
      return [];
    }
    const exactRows = this.db
      .prepare(
        `SELECT * FROM graph_entities_v2
         WHERE entity_ref = ? OR canonical_name = ?
         ORDER BY last_seen_at DESC, entity_ref ASC
         LIMIT ?`,
      )
      .all(normalized, normalized, Math.max(1, limit)) as Array<Record<string, unknown>>;
    if (exactRows.length > 0) {
      return exactRows.map(rowToGraphEntityV2);
    }
    const fuzzyRows = this.db
      .prepare(
        `SELECT * FROM graph_entities_v2
         WHERE canonical_name LIKE ? OR alias_json LIKE ? OR entity_ref LIKE ?
         ORDER BY last_seen_at DESC, entity_ref ASC
         LIMIT ?`,
      )
      .all(`%${normalized}%`, `%${normalized}%`, `%${normalized}%`, Math.max(1, limit)) as Array<
      Record<string, unknown>
    >;
    return fuzzyRows.map(rowToGraphEntityV2);
  }

  getStatus() {
    const evidenceV2Row = this.db
      .prepare("SELECT COUNT(*) AS count FROM evidence_records")
      .get() as { count?: number };
    const eventsV2Row = this.db.prepare("SELECT COUNT(*) AS count FROM event_records_v2").get() as {
      count?: number;
    };
    const entitiesV2Row = this.db
      .prepare("SELECT COUNT(*) AS count FROM graph_entities_v2")
      .get() as { count?: number };
    const edgesV2Row = this.db.prepare("SELECT COUNT(*) AS count FROM graph_edges_v2").get() as {
      count?: number;
    };
    const workflowV2Row = this.db
      .prepare("SELECT COUNT(*) AS count FROM workflow_state_view_v2")
      .get() as { count?: number };
    const pendingProjectionRow = this.db
      .prepare(
        `SELECT COUNT(*) AS count FROM projection_inbox
         WHERE source_kind = 'transcript' AND drained_at IS NULL`,
      )
      .get() as { count?: number } | undefined;
    return {
      dbPath: this.dbPath,
      eventsTotal: eventsV2Row.count ?? 0,
      entitiesTotal: workflowV2Row.count ?? 0,
      canonicalEntitiesTotal: entitiesV2Row.count ?? 0,
      graphEdgesTotal: edgesV2Row.count ?? 0,
      workflowStatesTotal: workflowV2Row.count ?? 0,
      evidenceRecordsV2Total: evidenceV2Row.count ?? 0,
      eventRecordsV2Total: eventsV2Row.count ?? 0,
      graphEntitiesV2Total: entitiesV2Row.count ?? 0,
      graphEdgesV2Total: edgesV2Row.count ?? 0,
      workflowStatesV2Total: workflowV2Row.count ?? 0,
      schemaVersion: this.getMeta("schema_version") ?? CANONICAL_SCHEMA_VERSION,
      extractorVersion: this.getMeta("extractor_version") ?? EXTRACTOR_VERSION,
      projectionVersion: this.getMeta("projection_version") ?? GRAPH_PROJECTION_VERSION,
      pendingProjectionSpans: pendingProjectionRow?.count ?? 0,
      metrics: this.getMetrics(),
    };
  }

  async exportData(): Promise<GraphExportData> {
    const evidenceRows = this.db
      .prepare("SELECT * FROM evidence_records ORDER BY created_at ASC, evidence_id ASC")
      .all() as Array<Record<string, unknown>>;
    const eventRows = this.db
      .prepare(
        "SELECT * FROM event_records_v2 ORDER BY occurred_at ASC, created_at ASC, event_id ASC",
      )
      .all() as Array<Record<string, unknown>>;
    const workflowRows = this.db
      .prepare("SELECT * FROM workflow_state_view_v2 ORDER BY task_ref ASC")
      .all() as Array<Record<string, unknown>>;
    const entityRows = this.db
      .prepare("SELECT * FROM graph_entities_v2 ORDER BY entity_ref ASC")
      .all() as Array<Record<string, unknown>>;
    const edgeRows = this.db
      .prepare("SELECT * FROM graph_edges_v2 ORDER BY src_ref ASC, edge_type ASC, dst_ref ASC")
      .all() as Array<Record<string, unknown>>;
    return {
      evidence: evidenceRows.map(rowToEvidenceV2),
      events: eventRows.map(rowToEventV2),
      workflowStates: workflowRows.map(rowToWorkflowStateV2),
      entities: entityRows.map(rowToGraphEntityV2),
      edges: edgeRows.map(rowToGraphEdgeV2),
      metrics: this.getMetrics(),
    };
  }

  async exportJsonl(): Promise<string> {
    const exported = await this.exportData();
    return [
      ...exported.evidence.map((row) => JSON.stringify({ type: "evidence_v2", ...row })),
      ...exported.events.map((row) => JSON.stringify({ type: "event_v2", ...row })),
      ...exported.workflowStates.map((row) =>
        JSON.stringify({ type: "workflow_state_v2", ...row }),
      ),
      ...exported.entities.map((row) => JSON.stringify({ type: "graph_entity_v2", ...row })),
      ...exported.edges.map((row) => JSON.stringify({ type: "graph_edge_v2", ...row })),
    ].join("\n");
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
