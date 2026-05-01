import os from "node:os";
import path from "node:path";
import type { DatabaseSync } from "node:sqlite";
import {
  createSubsystemLogger,
  resolveStateDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { generateUlid } from "./id-v2.js";
import {
  buildEdgeKey,
  buildTaskSessionEventFingerprint,
  EVENT_TYPE_REGISTRY_SEED,
  type EvidenceRecordV2,
  type EventRecordV2,
  type GraphEdgeV2,
  type GraphEntityV2,
  type TaskCurrentStateViewV2,
} from "./schema-v2.js";
import {
  EXTRACTOR_VERSION,
  FEISHU_TASK_WIKI_SCHEMA_SQL,
  FEISHU_TASK_WIKI_SCHEMA_VERSION,
  TASK_WIKI_METRIC_KEYS,
  TASK_WIKI_PROJECTION_VERSION,
  TASK_WIKI_RECALL_TTL_MS,
  type GraphHit,
  type RecentTaskWikiHit,
  type TaskSessionIngestQueueEntry,
  type TaskSessionIngestQueueWrite,
  type TaskSourceSessionState,
  type TaskWikiExportData,
  type TaskWikiMetricKey,
  type TaskWikiMetricsSnapshot,
  parseSourceRef,
} from "./schema.js";

const log = createSubsystemLogger("memory");
const stores = new Map<string, FeishuTaskWikiStore>();

type MetricRow = { key?: string; value?: number | string };
type PendingTaskSessionSummary = {
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

type SlotVersion = {
  event_id: string;
  event_fingerprint: string;
  occurred_at: string;
};

function taskWikiDbPathForAgent(agentId: string): string {
  return path.join(
    resolveStateDir(process.env, os.homedir),
    "memory",
    `${agentId}.feishu-task-wiki.sqlite`,
  );
}

function asPayloadRecord(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function parseStringArray(value: unknown): string[] {
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

function parseSlotVersions(value: string): Record<string, SlotVersion> {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const result: Record<string, SlotVersion> = {};
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

function taskRefForEvent(event: EventRecordV2): string | null {
  const payload = asPayloadRecord(event.payload_json);
  if (typeof payload.task_ref === "string" && payload.task_ref.startsWith("task:")) {
    return payload.task_ref;
  }
  if (event.subject_ref.startsWith("task:")) {
    return event.subject_ref;
  }
  return null;
}

function entityTypeForRef(ref: string): GraphEntityV2["entity_type"] {
  const prefix = ref.split(":", 1)[0] ?? "";
  switch (prefix) {
    case "task":
      return "task";
    case "person":
    case "person_name":
      return "person";
    case "topic":
      return "topic";
    case "thread":
      return "thread";
    case "doc":
      return "doc";
    case "project":
      return "project";
    case "memory_block":
      return "memory_block";
    case "session_event":
    case "event":
      return "session_event";
    case "session_wiki":
      return "session_wiki";
    case "evidence":
      return "evidence";
    case "date":
      return "date";
    default:
      return "topic";
  }
}

function canonicalNameForRef(ref: string, payload: Record<string, unknown>, evidence: EvidenceRecordV2): string {
  if (ref.startsWith("task:")) {
    return ref.slice(5);
  }
  if (ref.startsWith("event:")) {
    return typeof payload.claim === "string" ? payload.claim : ref;
  }
  if (ref.startsWith("evidence:")) {
    return typeof payload.evidence_quote === "string"
      ? payload.evidence_quote
      : evidence.content_text ?? ref;
  }
  if (ref.startsWith("date:")) {
    return ref.slice(5);
  }
  return ref.includes(":") ? ref.split(":").slice(1).join(":") : ref;
}

function relatedRefsForEvent(event: EventRecordV2): string[] {
  try {
    const parsed = JSON.parse(event.related_refs_json) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string")
      : [];
  } catch {
    return [];
  }
}

function buildTaskStateSlotVersion(event: EventRecordV2): SlotVersion {
  return {
    event_id: event.event_id,
    event_fingerprint: event.event_fingerprint,
    occurred_at: event.occurred_at,
  };
}

function rowToTaskSourceSessionState(row: Record<string, unknown>): TaskSourceSessionState {
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
        : TASK_WIKI_PROJECTION_VERSION,
    status,
  };
}

function rowToTaskSessionIngestQueueEntry(
  row: Record<string, unknown>,
): TaskSessionIngestQueueEntry {
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

function rowToRecentTaskWikiHit(row: Record<string, unknown>): RecentTaskWikiHit {
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
    linked_event_ids_json:
      typeof row.linked_event_ids_json === "string" ? row.linked_event_ids_json : null,
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

function rowToTaskCurrentStateV2(row: Record<string, unknown>): TaskCurrentStateViewV2 {
  return {
    task_ref: String(row.task_ref),
    primary_topic_ref: typeof row.primary_topic_ref === "string" ? row.primary_topic_ref : null,
    active_conclusion_event_id:
      typeof row.active_conclusion_event_id === "string" ? row.active_conclusion_event_id : null,
    active_rationale_event_ids_json:
      typeof row.active_rationale_event_ids_json === "string"
        ? row.active_rationale_event_ids_json
        : "[]",
    active_objection_event_ids_json:
      typeof row.active_objection_event_ids_json === "string"
        ? row.active_objection_event_ids_json
        : "[]",
    active_constraint_event_ids_json:
      typeof row.active_constraint_event_ids_json === "string"
        ? row.active_constraint_event_ids_json
        : "[]",
    active_commitment_event_ids_json:
      typeof row.active_commitment_event_ids_json === "string"
        ? row.active_commitment_event_ids_json
        : "[]",
    active_status_event_ids_json:
      typeof row.active_status_event_ids_json === "string"
        ? row.active_status_event_ids_json
        : "[]",
    active_scope_event_ids_json:
      typeof row.active_scope_event_ids_json === "string"
        ? row.active_scope_event_ids_json
        : "[]",
    active_stage_event_id:
      typeof row.active_stage_event_id === "string" ? row.active_stage_event_id : null,
    active_time_point_event_ids_json:
      typeof row.active_time_point_event_ids_json === "string"
        ? row.active_time_point_event_ids_json
        : "[]",
    slot_versions_json: typeof row.slot_versions_json === "string" ? row.slot_versions_json : "{}",
    last_event_id: String(row.last_event_id),
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

export class FeishuTaskWikiStore {
  readonly dbPath: string;
  private readonly db: DatabaseSync;

  constructor(agentId: string, dbPath = taskWikiDbPathForAgent(agentId)) {
    this.dbPath = dbPath;
    this.db = openMemoryDatabaseAtPath(dbPath, false);
    log.info(`feishu_task_wiki.store.open agent=${agentId} path=${dbPath}`);
    this.ensureSchema();
  }

  private ensureSchema(): void {
    this.db.exec(FEISHU_TASK_WIKI_SCHEMA_SQL);
    this.setMeta("schema_version", FEISHU_TASK_WIKI_SCHEMA_VERSION);
    this.setMeta("extractor_version", EXTRACTOR_VERSION);
    this.setMeta("projection_version", TASK_WIKI_PROJECTION_VERSION);
    const ensureMetric = this.db.prepare(
      "INSERT OR IGNORE INTO feishu_task_wiki_metrics(key, value) VALUES (?, 0)",
    );
    for (const key of TASK_WIKI_METRIC_KEYS) {
      ensureMetric.run(key);
    }
    const seed = this.db.prepare(
      `INSERT OR IGNORE INTO task_event_type_registry(
        event_type, subject_type, object_type, payload_schema_json, description, enabled, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)`,
    );
    const nowMs = Date.now();
    for (const record of EVENT_TYPE_REGISTRY_SEED) {
      seed.run(
        record.event_type,
        record.subject_type,
        record.object_type,
        record.payload_schema_json,
        record.description,
        record.enabled,
        record.created_at ?? nowMs,
      );
    }
    log.info("feishu_task_wiki.store.schema_ready");
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
      this.db.exec("DELETE FROM task_wiki_relations");
      this.db.exec("DELETE FROM task_wiki_entities");
      this.db.exec("DELETE FROM task_current_state_view");
      this.db.exec("DELETE FROM task_session_events");
      this.db.exec("DELETE FROM task_event_type_registry");
      this.db.exec("DELETE FROM task_evidence_records");
      this.db.exec("DELETE FROM recent_task_wiki_hits");
      this.db.exec("DELETE FROM task_source_session_state");
      this.db.exec("DELETE FROM task_session_ingest_queue");
      this.db.exec("DELETE FROM feishu_task_wiki_metrics");
      const ensureMetric = this.db.prepare(
        "INSERT OR IGNORE INTO feishu_task_wiki_metrics(key, value) VALUES (?, 0)",
      );
      for (const key of TASK_WIKI_METRIC_KEYS) {
        ensureMetric.run(key);
      }
      this.setMeta("schema_version", FEISHU_TASK_WIKI_SCHEMA_VERSION);
      this.setMeta("extractor_version", EXTRACTOR_VERSION);
      this.setMeta("projection_version", TASK_WIKI_PROJECTION_VERSION);
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
    log.info("feishu_task_wiki.store.reset");
  }

  bumpMetric(key: TaskWikiMetricKey, delta = 1): number {
    this.db
      .prepare(
        `INSERT INTO feishu_task_wiki_metrics(key, value)
         VALUES (?, ?)
         ON CONFLICT(key) DO UPDATE SET value = value + excluded.value`,
      )
      .run(key, delta);
    const row = this.db
      .prepare("SELECT value FROM feishu_task_wiki_metrics WHERE key = ?")
      .get(key) as { value?: number | string } | undefined;
    return Number(row?.value ?? 0);
  }

  recordExtractorLatency(durationMs: number): void {
    const normalized = Number.isFinite(durationMs) ? Math.max(0, durationMs) : 0;
    this.bumpMetric("extractLatencyMsSum", normalized);
    this.bumpMetric("extractLatencyMsCount", 1);
  }

  getMetrics(): TaskWikiMetricsSnapshot {
    const rows = this.db
      .prepare("SELECT key, value FROM feishu_task_wiki_metrics")
      .all() as MetricRow[];
    const base = Object.fromEntries(TASK_WIKI_METRIC_KEYS.map((key) => [key, 0])) as Record<
      TaskWikiMetricKey,
      number
    >;
    for (const row of rows) {
      const key = typeof row.key === "string" ? (row.key as TaskWikiMetricKey) : null;
      if (key && key in base) {
        base[key] = Number(row.value ?? 0);
      }
    }
    const count = base.extractLatencyMsCount;
    return {
      ...base,
      hitsUsed: base.hitsUsedUniqueRefs,
      extractLatencyMsAvg: count > 0 ? base.extractLatencyMsSum / count : 0,
    };
  }

  private deleteExpiredRecentHits(nowMs = Date.now()): void {
    this.db.prepare("DELETE FROM recent_task_wiki_hits WHERE expires_at < ?").run(nowMs);
  }

  enqueueProjectionInbox(entry: TaskSessionIngestQueueWrite): boolean {
    const insert = this.db.prepare(
      `INSERT OR IGNORE INTO task_session_ingest_queue(
        source_kind, source_id, first_entry_id, last_entry_id, entries_json, dirty_reason,
        signal_strength, strong_event, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const upsertState = this.db.prepare(
      `INSERT INTO task_source_session_state(
        source_kind, source_id, covered_until_entry_id, dirty_since_entry_id,
        last_projected_at, projection_version, status
      ) VALUES (?, ?, NULL, ?, NULL, ?, 'dirty')
      ON CONFLICT(source_kind, source_id) DO UPDATE SET
        dirty_since_entry_id = COALESCE(task_source_session_state.dirty_since_entry_id, excluded.dirty_since_entry_id),
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
        TASK_WIKI_PROJECTION_VERSION,
      );
      this.db.exec("COMMIT");
      return result.changes > 0;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  getProjectionState(sourceId: string): TaskSourceSessionState | null {
    const row = this.db
      .prepare(
        `SELECT * FROM task_source_session_state
         WHERE source_kind = 'transcript' AND source_id = ?`,
      )
      .get(sourceId) as Record<string, unknown> | undefined;
    return row ? rowToTaskSourceSessionState(row) : null;
  }

  hasPendingProjection(sourceId?: string): boolean {
    const row = sourceId?.trim()
      ? (this.db
          .prepare(
            `SELECT 1 AS pending FROM task_session_ingest_queue
             WHERE source_kind = 'transcript' AND source_id = ? AND drained_at IS NULL
             LIMIT 1`,
          )
          .get(sourceId.trim()) as { pending?: number } | undefined)
      : (this.db
          .prepare(
            `SELECT 1 AS pending FROM task_session_ingest_queue
             WHERE source_kind = 'transcript' AND drained_at IS NULL
             LIMIT 1`,
          )
          .get() as { pending?: number } | undefined);
    return row?.pending === 1;
  }

  listPendingProjectionSummaries(sourceId?: string): PendingTaskSessionSummary[] {
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
             FROM task_session_ingest_queue
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
             FROM task_session_ingest_queue
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

  listPendingProjectionInbox(sourceId?: string): TaskSessionIngestQueueEntry[] {
    const sourceFilter = sourceId?.trim();
    const rows = sourceFilter
      ? (this.db
          .prepare(
            `SELECT * FROM task_session_ingest_queue
             WHERE drained_at IS NULL AND source_kind = 'transcript' AND source_id = ?
             ORDER BY created_at ASC, id ASC`,
          )
          .all(sourceFilter) as Array<Record<string, unknown>>)
      : (this.db
          .prepare(
            `SELECT * FROM task_session_ingest_queue
             WHERE drained_at IS NULL AND source_kind = 'transcript'
             ORDER BY created_at ASC, id ASC`,
          )
          .all() as Array<Record<string, unknown>>);
    return rows.map(rowToTaskSessionIngestQueueEntry);
  }

  markProjectionSourceDraining(sourceId: string): void {
    this.db
      .prepare(
        `UPDATE task_source_session_state
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
          `UPDATE task_session_ingest_queue
           SET drained_at = ?
           WHERE source_kind = 'transcript' AND source_id = ? AND drained_at IS NULL`,
        )
        .run(nowMs, params.sourceId);
      this.db
        .prepare(
          `INSERT INTO task_source_session_state(
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
        .run(params.sourceId, params.coveredUntilEntryId, nowMs, TASK_WIKI_PROJECTION_VERSION);
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  markProjectionFailed(sourceId: string): void {
    this.db
      .prepare(
        `UPDATE task_source_session_state
         SET status = 'failed'
         WHERE source_kind = 'transcript' AND source_id = ?`,
      )
      .run(sourceId);
  }

  recordKgRetryMarker(_params: {
    scope: string;
    status: "failed" | "running" | "complete" | "idle";
    error?: string;
    retryMarker?: Record<string, unknown>;
    lastEventCreatedAt?: number | null;
    lastEventId?: string | null;
    nowMs?: number;
  }): void {}

  listProjectionStates(): TaskSourceSessionState[] {
    const rows = this.db
      .prepare("SELECT * FROM task_source_session_state ORDER BY source_id ASC")
      .all() as Array<Record<string, unknown>>;
    return rows.map(rowToTaskSourceSessionState);
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
      : TASK_WIKI_RECALL_TTL_MS;
    this.deleteExpiredRecentHits(nowMs);
    const upsert = this.db.prepare(
      `INSERT INTO recent_task_wiki_hits(
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
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
    return recorded;
  }

  markRecentGraphHitsUsedByRead(params: {
    sessionKey: string;
    path: string;
    from?: number;
    lines?: number;
    nowMs?: number;
  }): RecentTaskWikiHit[] {
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
        `SELECT * FROM recent_task_wiki_hits
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
        `UPDATE recent_task_wiki_hits
         SET used_at = ?
         WHERE session_key = ?
           AND path = ?
           AND expires_at >= ?
           AND end_line >= ?
           AND start_line <= ?`,
      )
      .run(nowMs, sessionKey, params.path, nowMs, startLine, endLine);
    return rows.map(rowToRecentTaskWikiHit);
  }

  markRecentGraphHitsUsedBySourceRefs(params: {
    sessionKey: string;
    sourceRefs: string[];
    nowMs?: number;
  }): RecentTaskWikiHit[] {
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
        `SELECT * FROM recent_task_wiki_hits
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
        `UPDATE recent_task_wiki_hits
         SET used_at = ?
         WHERE session_key = ?
           AND expires_at >= ?
           AND source_ref IN (${placeholders})`,
      )
      .run(nowMs, sessionKey, nowMs, ...sourceRefs);
    return rows.map(rowToRecentTaskWikiHit);
  }

  getRecentGraphHits(sessionKey: string, nowMs = Date.now()): RecentTaskWikiHit[] {
    if (!sessionKey.trim()) {
      return [];
    }
    this.deleteExpiredRecentHits(nowMs);
    const rows = this.db
      .prepare(
        `SELECT * FROM recent_task_wiki_hits
         WHERE session_key = ?
         ORDER BY last_returned_at DESC, source_ref ASC`,
      )
      .all(sessionKey) as Array<Record<string, unknown>>;
    return rows.map(rowToRecentTaskWikiHit);
  }

  private getEvidenceByFingerprintInTransaction(fingerprint: string): EvidenceRecordV2 | null {
    const row = this.db
      .prepare("SELECT * FROM task_evidence_records WHERE evidence_fingerprint = ?")
      .get(fingerprint) as Record<string, unknown> | undefined;
    return row ? rowToEvidenceV2(row) : null;
  }

  private upsertEvidenceRecordV2InTransaction(evidence: EvidenceRecordV2): EvidenceRecordV2 {
    const existing = this.getEvidenceByFingerprintInTransaction(evidence.evidence_fingerprint);
    if (existing) {
      this.db
        .prepare(
          `UPDATE task_evidence_records
           SET message_id = COALESCE(message_id, ?),
               thread_id = COALESCE(thread_id, ?),
               root_id = COALESCE(root_id, ?),
               parent_id = COALESCE(parent_id, ?),
               linked_event_ids_json = COALESCE(linked_event_ids_json, ?)
           WHERE evidence_id = ?`,
        )
        .run(
          evidence.message_id,
          evidence.thread_id,
          evidence.root_id,
          evidence.parent_id,
          evidence.linked_event_ids_json ?? null,
          existing.evidence_id,
        );
      const refreshed = this.db
        .prepare("SELECT * FROM task_evidence_records WHERE evidence_id = ?")
        .get(existing.evidence_id) as Record<string, unknown>;
      return rowToEvidenceV2(refreshed);
    }
    const persisted: EvidenceRecordV2 = {
      ...evidence,
      evidence_id: evidence.evidence_id || generateUlid(),
      created_at: evidence.created_at || Date.now(),
      linked_event_ids_json: evidence.linked_event_ids_json ?? null,
    };
    this.db
      .prepare(
        `INSERT INTO task_evidence_records(
          evidence_id, evidence_fingerprint, source_platform, source_kind, session_key, message_id,
          chat_id, chat_type, thread_id, root_id, parent_id, first_entry_id, last_entry_id,
          content_text, content_json, source_locator_json, occurred_at, created_at, linked_event_ids_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
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
        persisted.linked_event_ids_json ?? null,
      );
    return persisted;
  }

  private insertEventsV2InTransaction(events: EventRecordV2[]): EventRecordV2[] {
    const inserted: EventRecordV2[] = [];
    const lookup = this.db.prepare("SELECT * FROM task_session_events WHERE event_fingerprint = ?");
    const insert = this.db.prepare(
      `INSERT INTO task_session_events(
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

  private getTaskCurrentStateV2InTransaction(taskRef: string): TaskCurrentStateViewV2 | null {
    const row = this.db
      .prepare("SELECT * FROM task_current_state_view WHERE task_ref = ?")
      .get(taskRef) as Record<string, unknown> | undefined;
    return row ? rowToTaskCurrentStateV2(row) : null;
  }

  private upsertTaskCurrentStateV2InTransaction(events: EventRecordV2[]): TaskCurrentStateViewV2[] {
    const grouped = new Map<string, EventRecordV2[]>();
    for (const event of events) {
      const taskRef = taskRefForEvent(event);
      if (!taskRef) {
        continue;
      }
      const list = grouped.get(taskRef) ?? [];
      list.push(event);
      grouped.set(taskRef, list);
    }
    const results: TaskCurrentStateViewV2[] = [];
    for (const [taskRef, taskEvents] of grouped.entries()) {
      taskEvents.sort(
        (left, right) =>
          left.occurred_at.localeCompare(right.occurred_at) ||
          left.event_fingerprint.localeCompare(right.event_fingerprint),
      );
      const firstPayload = asPayloadRecord(taskEvents[0]?.payload_json ?? "{}");
      const state =
        this.getTaskCurrentStateV2InTransaction(taskRef) ??
        ({
          task_ref: taskRef,
          primary_topic_ref:
            typeof firstPayload.topic_ref === "string" ? firstPayload.topic_ref : null,
          active_conclusion_event_id: null,
          active_rationale_event_ids_json: "[]",
          active_objection_event_ids_json: "[]",
          active_constraint_event_ids_json: "[]",
          active_commitment_event_ids_json: "[]",
          active_status_event_ids_json: "[]",
          active_scope_event_ids_json: "[]",
          active_stage_event_id: null,
          active_time_point_event_ids_json: "[]",
          slot_versions_json: "{}",
          last_event_id: taskEvents[0].event_id,
          updated_at: Date.now(),
        } satisfies TaskCurrentStateViewV2);
      const slotVersions = parseSlotVersions(state.slot_versions_json);
      const rationales = new Set(parseStringArray(state.active_rationale_event_ids_json));
      const objections = new Set(parseStringArray(state.active_objection_event_ids_json));
      const constraints = new Set(parseStringArray(state.active_constraint_event_ids_json));
      const commitments = new Set(parseStringArray(state.active_commitment_event_ids_json));
      const statuses = new Set(parseStringArray(state.active_status_event_ids_json));
      const scopes = new Set(parseStringArray(state.active_scope_event_ids_json));
      const timePoints = new Set(parseStringArray(state.active_time_point_event_ids_json));
      for (const event of taskEvents) {
        const payload = asPayloadRecord(event.payload_json);
        if (typeof payload.topic_ref === "string" && payload.topic_ref) {
          state.primary_topic_ref = payload.topic_ref;
        }
        switch (event.event_type) {
          case "conclusion_event":
            state.active_conclusion_event_id = event.event_id;
            slotVersions.conclusion = buildTaskStateSlotVersion(event);
            break;
          case "rationale_event":
            rationales.add(event.event_id);
            break;
          case "objection_event":
            objections.add(event.event_id);
            break;
          case "constraint_event":
            constraints.add(event.event_id);
            slotVersions.constraint = buildTaskStateSlotVersion(event);
            break;
          case "commitment_event":
            commitments.add(event.event_id);
            slotVersions.commitment = buildTaskStateSlotVersion(event);
            break;
          case "status_event":
            statuses.add(event.event_id);
            slotVersions.status = buildTaskStateSlotVersion(event);
            if (typeof payload.stage === "string" && payload.stage.trim()) {
              state.active_stage_event_id = event.event_id;
              slotVersions.stage = buildTaskStateSlotVersion(event);
            }
            break;
          case "time_event":
            timePoints.add(event.event_id);
            slotVersions.time = buildTaskStateSlotVersion(event);
            break;
          case "scope_event":
            scopes.add(event.event_id);
            slotVersions.scope = buildTaskStateSlotVersion(event);
            state.active_stage_event_id = event.event_id;
            break;
          default:
            break;
        }
        state.last_event_id = event.event_id;
      }
      state.active_rationale_event_ids_json = JSON.stringify([...rationales]);
      state.active_objection_event_ids_json = JSON.stringify([...objections]);
      state.active_constraint_event_ids_json = JSON.stringify([...constraints]);
      state.active_commitment_event_ids_json = JSON.stringify([...commitments]);
      state.active_status_event_ids_json = JSON.stringify([...statuses]);
      state.active_scope_event_ids_json = JSON.stringify([...scopes]);
      state.active_time_point_event_ids_json = JSON.stringify([...timePoints]);
      state.slot_versions_json = JSON.stringify(slotVersions);
      state.updated_at = Date.now();
      this.db
        .prepare(
          `INSERT INTO task_current_state_view(
            task_ref, primary_topic_ref, active_conclusion_event_id, active_rationale_event_ids_json,
            active_objection_event_ids_json, active_constraint_event_ids_json,
            active_commitment_event_ids_json, active_status_event_ids_json,
            active_scope_event_ids_json, active_stage_event_id,
            active_time_point_event_ids_json, slot_versions_json, last_event_id, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(task_ref) DO UPDATE SET
            primary_topic_ref = excluded.primary_topic_ref,
            active_conclusion_event_id = excluded.active_conclusion_event_id,
            active_rationale_event_ids_json = excluded.active_rationale_event_ids_json,
            active_objection_event_ids_json = excluded.active_objection_event_ids_json,
            active_constraint_event_ids_json = excluded.active_constraint_event_ids_json,
            active_commitment_event_ids_json = excluded.active_commitment_event_ids_json,
            active_status_event_ids_json = excluded.active_status_event_ids_json,
            active_scope_event_ids_json = excluded.active_scope_event_ids_json,
            active_stage_event_id = excluded.active_stage_event_id,
            active_time_point_event_ids_json = excluded.active_time_point_event_ids_json,
            slot_versions_json = excluded.slot_versions_json,
            last_event_id = excluded.last_event_id,
            updated_at = excluded.updated_at`,
        )
        .run(
          state.task_ref,
          state.primary_topic_ref,
          state.active_conclusion_event_id,
          state.active_rationale_event_ids_json,
          state.active_objection_event_ids_json,
          state.active_constraint_event_ids_json,
          state.active_commitment_event_ids_json,
          state.active_status_event_ids_json,
          state.active_scope_event_ids_json,
          state.active_stage_event_id,
          state.active_time_point_event_ids_json,
          state.slot_versions_json,
          state.last_event_id,
          state.updated_at,
        );
      results.push(state);
    }
    return results;
  }

  private updateEvidenceLinkedEventIdsInTransaction(
    evidenceRows: EvidenceRecordV2[],
    events: EventRecordV2[],
  ): EvidenceRecordV2[] {
    const idsByEvidence = new Map<string, Set<string>>();
    for (const event of events) {
      const set = idsByEvidence.get(event.evidence_id) ?? new Set<string>();
      set.add(event.event_id);
      idsByEvidence.set(event.evidence_id, set);
    }
    const update = this.db.prepare(
      `UPDATE task_evidence_records SET linked_event_ids_json = ? WHERE evidence_id = ?`,
    );
    const refreshed: EvidenceRecordV2[] = [];
    for (const evidence of evidenceRows) {
      const linked = idsByEvidence.get(evidence.evidence_id);
      if (linked) {
        update.run(JSON.stringify([...linked]), evidence.evidence_id);
      }
      const row = this.db
        .prepare("SELECT * FROM task_evidence_records WHERE evidence_id = ?")
        .get(evidence.evidence_id) as Record<string, unknown>;
      refreshed.push(rowToEvidenceV2(row));
    }
    return refreshed;
  }

  private upsertTaskWikiEntitiesInTransaction(
    evidence: EvidenceRecordV2,
    events: EventRecordV2[],
  ): GraphEntityV2[] {
    const entities = new Map<string, GraphEntityV2>();
    for (const event of events) {
      const payload = asPayloadRecord(event.payload_json);
      const refs = new Set<string>([
        event.subject_ref,
        `event:${event.event_id}`,
        `evidence:${evidence.evidence_id}`,
        ...relatedRefsForEvent(event),
      ]);
      if (event.actor_ref) {
        refs.add(event.actor_ref);
      }
      if (event.object_ref) {
        refs.add(event.object_ref);
      }
      const claimValue =
        payload.claim_value && typeof payload.claim_value === "object"
          ? (payload.claim_value as Record<string, unknown>)
          : payload.claim_value_json && typeof payload.claim_value_json === "object"
            ? (payload.claim_value_json as Record<string, unknown>)
            : {};
      if (typeof claimValue.date === "string" && claimValue.date.trim()) {
        refs.add(`date:${claimValue.date.trim()}`);
      }
      for (const ref of refs) {
        const current = entities.get(ref);
        entities.set(ref, {
          entity_ref: ref,
          entity_type: entityTypeForRef(ref),
          canonical_name:
            current?.canonical_name ?? canonicalNameForRef(ref, payload, evidence),
          alias_json: current?.alias_json ?? "[]",
          first_seen_at: current?.first_seen_at ?? event.occurred_at,
          last_seen_at: event.occurred_at,
          last_evidence_id: evidence.evidence_id,
          updated_at: Date.now(),
        });
      }
    }
    const upsert = this.db.prepare(
      `INSERT INTO task_wiki_entities(
        entity_ref, entity_type, canonical_name, alias_json, first_seen_at, last_seen_at,
        last_evidence_id, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(entity_ref) DO UPDATE SET
        entity_type = excluded.entity_type,
        canonical_name = excluded.canonical_name,
        alias_json = excluded.alias_json,
        first_seen_at = MIN(task_wiki_entities.first_seen_at, excluded.first_seen_at),
        last_seen_at = MAX(task_wiki_entities.last_seen_at, excluded.last_seen_at),
        last_evidence_id = excluded.last_evidence_id,
        updated_at = excluded.updated_at`,
    );
    for (const entity of entities.values()) {
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
    return [...entities.values()];
  }

  private upsertTaskWikiRelationsInTransaction(events: EventRecordV2[]): GraphEdgeV2[] {
    const closes: Array<{ src_ref: string; edge_type: GraphEdgeV2["edge_type"]; closed_at: string }> = [];
    const pending = new Map<string, GraphEdgeV2>();
    for (const event of events) {
      const taskRef = taskRefForEvent(event);
      if (!taskRef) {
        continue;
      }
      const claimRef = `event:${event.event_id}`;
      const evidenceRef = `evidence:${event.evidence_id}`;
      const push = (srcRef: string, edgeType: GraphEdgeV2["edge_type"], dstRef: string) => {
        const edgeKey = buildEdgeKey({ srcRef, edgeType, dstRef });
        pending.set(edgeKey, {
          edge_id: "",
          edge_key: edgeKey,
          src_ref: srcRef,
          edge_type: edgeType,
          dst_ref: dstRef,
          derived_from_event_id: event.event_id,
          active: 1,
          valid_from: event.occurred_at,
          valid_to: null,
          updated_at: Date.now(),
        });
      };
      switch (event.event_type) {
        case "conclusion_event":
          closes.push({ src_ref: taskRef, edge_type: "has_active_conclusion", closed_at: event.occurred_at });
          push(taskRef, "has_active_conclusion", claimRef);
          break;
        case "rationale_event":
          push(taskRef, "has_active_rationale", claimRef);
          break;
        case "objection_event":
          push(taskRef, "has_active_objection", claimRef);
          break;
        case "constraint_event":
          push(taskRef, "has_active_constraint", claimRef);
          break;
        case "commitment_event":
          push(taskRef, "has_active_commitment", claimRef);
          break;
        case "status_event":
          push(taskRef, "has_active_status", claimRef);
          break;
        case "scope_event":
          closes.push({ src_ref: taskRef, edge_type: "has_active_scope", closed_at: event.occurred_at });
          push(taskRef, "has_active_scope", claimRef);
          break;
        case "time_event":
          push(taskRef, "has_active_time_point", claimRef);
          break;
        default:
          break;
      }
      push(claimRef, "supported_by", evidenceRef);
      const payload = asPayloadRecord(event.payload_json);
      const claimValue =
        payload.claim_value && typeof payload.claim_value === "object"
          ? (payload.claim_value as Record<string, unknown>)
          : payload.claim_value_json && typeof payload.claim_value_json === "object"
            ? (payload.claim_value_json as Record<string, unknown>)
            : {};
      if (typeof claimValue.date === "string" && claimValue.date.trim()) {
        push(taskRef, "related_time", `date:${claimValue.date.trim()}`);
      }
    }
    if (closes.length > 0) {
      const close = this.db.prepare(
        `UPDATE task_wiki_relations
         SET active = 0, valid_to = ?, updated_at = ?
         WHERE src_ref = ? AND edge_type = ? AND active = 1`,
      );
      for (const mutation of closes) {
        close.run(mutation.closed_at, Date.now(), mutation.src_ref, mutation.edge_type);
      }
    }
    const lookup = this.db.prepare("SELECT * FROM task_wiki_relations WHERE edge_key = ?");
    const insert = this.db.prepare(
      `INSERT INTO task_wiki_relations(
        edge_id, edge_key, src_ref, edge_type, dst_ref, derived_from_event_id, active,
        valid_from, valid_to, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const update = this.db.prepare(
      `UPDATE task_wiki_relations
       SET src_ref = ?, edge_type = ?, dst_ref = ?, derived_from_event_id = ?, active = ?,
           valid_from = ?, valid_to = ?, updated_at = ?
       WHERE edge_key = ?`,
    );
    const persisted: GraphEdgeV2[] = [];
    for (const relation of pending.values()) {
      const existingRow = lookup.get(relation.edge_key) as Record<string, unknown> | undefined;
      const existing = existingRow ? rowToGraphEdgeV2(existingRow) : null;
      const edgeId = existing?.edge_id ?? generateUlid();
      if (existing) {
        update.run(
          relation.src_ref,
          relation.edge_type,
          relation.dst_ref,
          relation.derived_from_event_id,
          relation.active,
          relation.valid_from,
          relation.valid_to,
          relation.updated_at,
          relation.edge_key,
        );
      } else {
        insert.run(
          edgeId,
          relation.edge_key,
          relation.src_ref,
          relation.edge_type,
          relation.dst_ref,
          relation.derived_from_event_id,
          relation.active,
          relation.valid_from,
          relation.valid_to,
          relation.updated_at,
        );
      }
      persisted.push({ ...relation, edge_id: edgeId });
    }
    return persisted;
  }

  async persistSemanticBatchV2(params: {
    evidence: EvidenceRecordV2[];
    events: EventRecordV2[];
  }): Promise<{
    evidence: EvidenceRecordV2[];
    events: EventRecordV2[];
    taskStates: TaskCurrentStateViewV2[];
    entities: GraphEntityV2[];
    edges: GraphEdgeV2[];
  }> {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const evidenceRows = params.evidence.map((row) =>
        this.upsertEvidenceRecordV2InTransaction(row),
      );
      const evidenceById = new Map(evidenceRows.map((row) => [row.evidence_id, row]));
      const evidenceByFingerprint = new Map(
        evidenceRows.map((row) => [row.evidence_fingerprint, row]),
      );
      const normalizedEvents = params.events.map((event) => {
        const payloadJson = asPayloadRecord(event.payload_json);
        const eventEvidence =
          evidenceById.get(event.evidence_id) ??
          (typeof payloadJson.evidence_fingerprint === "string"
            ? evidenceByFingerprint.get(payloadJson.evidence_fingerprint)
            : null) ??
          evidenceRows[0];
        const taskRef = taskRefForEvent(event) ?? event.subject_ref;
        return {
          ...event,
          evidence_id: eventEvidence.evidence_id,
          event_fingerprint: buildTaskSessionEventFingerprint({
            taskRef,
            eventType: event.event_type,
            claimText:
              typeof payloadJson.claim === "string"
                ? payloadJson.claim
                : typeof payloadJson.claim_text === "string"
                  ? payloadJson.claim_text
                  : "",
            evidenceId: eventEvidence.evidence_id,
          }),
        };
      });
      const events = this.insertEventsV2InTransaction(normalizedEvents);
      const linkedEvidence = this.updateEvidenceLinkedEventIdsInTransaction(evidenceRows, events);
      const entities = linkedEvidence.flatMap((evidence) =>
        this.upsertTaskWikiEntitiesInTransaction(
          evidence,
          events.filter((event) => event.evidence_id === evidence.evidence_id),
        ),
      );
      const taskStates = this.upsertTaskCurrentStateV2InTransaction(events);
      const edges = this.upsertTaskWikiRelationsInTransaction(events);
      this.db.exec("COMMIT");
      return {
        evidence: linkedEvidence,
        events,
        taskStates,
        entities,
        edges,
      };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  getEvidenceByIdV2(evidenceId: string): EvidenceRecordV2 | null {
    const row = this.db
      .prepare("SELECT * FROM task_evidence_records WHERE evidence_id = ?")
      .get(evidenceId) as Record<string, unknown> | undefined;
    return row ? rowToEvidenceV2(row) : null;
  }

  getEventByIdV2(eventId: string): EventRecordV2 | null {
    const row = this.db
      .prepare("SELECT * FROM task_session_events WHERE event_id = ?")
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
      .prepare(`SELECT * FROM task_session_events WHERE event_id IN (${placeholders})`)
      .all(...unique) as Array<Record<string, unknown>>;
    return rows.map(rowToEventV2);
  }

  getTaskCurrentStateV2(taskRef: string): TaskCurrentStateViewV2 | null {
    return this.getTaskCurrentStateV2InTransaction(taskRef);
  }

  listTaskStatesV2(): TaskCurrentStateViewV2[] {
    const rows = this.db
      .prepare("SELECT * FROM task_current_state_view ORDER BY updated_at DESC, task_ref ASC")
      .all() as Array<Record<string, unknown>>;
    return rows.map(rowToTaskCurrentStateV2);
  }

  listEventsForRefV2(ref: string, limit = 50): EventRecordV2[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM task_session_events
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
        `SELECT * FROM task_wiki_relations
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
        `SELECT * FROM task_wiki_entities
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
        `SELECT * FROM task_wiki_entities
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
    const evidenceRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM task_evidence_records")
      .get() as { count?: number };
    const eventRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM task_session_events")
      .get() as { count?: number };
    const entityRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM task_wiki_entities")
      .get() as { count?: number };
    const edgeRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM task_wiki_relations")
      .get() as { count?: number };
    const taskStateRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM task_current_state_view")
      .get() as { count?: number };
    const pendingRow = this.db
      .prepare(
        `SELECT COUNT(*) AS count FROM task_session_ingest_queue
         WHERE source_kind = 'transcript' AND drained_at IS NULL`,
      )
      .get() as { count?: number } | undefined;
    return {
      dbPath: this.dbPath,
      eventsTotal: eventRow.count ?? 0,
      entitiesTotal: entityRow.count ?? 0,
      taskStatesTotal: taskStateRow.count ?? 0,
      evidenceRecordsTotal: evidenceRow.count ?? 0,
      taskSessionEventsTotal: eventRow.count ?? 0,
      taskWikiEntitiesTotal: entityRow.count ?? 0,
      taskWikiRelationsTotal: edgeRow.count ?? 0,
      schemaVersion: this.getMeta("schema_version") ?? FEISHU_TASK_WIKI_SCHEMA_VERSION,
      extractorVersion: this.getMeta("extractor_version") ?? EXTRACTOR_VERSION,
      projectionVersion: this.getMeta("projection_version") ?? TASK_WIKI_PROJECTION_VERSION,
      pendingTaskSessionSpans: pendingRow?.count ?? 0,
      metrics: this.getMetrics(),
    };
  }

  async exportData(): Promise<TaskWikiExportData> {
    const evidenceRows = this.db
      .prepare("SELECT * FROM task_evidence_records ORDER BY created_at ASC, evidence_id ASC")
      .all() as Array<Record<string, unknown>>;
    const eventRows = this.db
      .prepare(
        "SELECT * FROM task_session_events ORDER BY occurred_at ASC, created_at ASC, event_id ASC",
      )
      .all() as Array<Record<string, unknown>>;
    const taskStateRows = this.db
      .prepare("SELECT * FROM task_current_state_view ORDER BY task_ref ASC")
      .all() as Array<Record<string, unknown>>;
    const entityRows = this.db
      .prepare("SELECT * FROM task_wiki_entities ORDER BY entity_ref ASC")
      .all() as Array<Record<string, unknown>>;
    const edgeRows = this.db
      .prepare("SELECT * FROM task_wiki_relations ORDER BY src_ref ASC, edge_type ASC, dst_ref ASC")
      .all() as Array<Record<string, unknown>>;
    return {
      evidence: evidenceRows.map(rowToEvidenceV2),
      events: eventRows.map(rowToEventV2),
      workflowStates: taskStateRows.map(rowToTaskCurrentStateV2),
      decisionStates: [],
      entities: entityRows.map(rowToGraphEntityV2),
      edges: edgeRows.map(rowToGraphEdgeV2),
      metrics: this.getMetrics(),
    };
  }

  async exportJsonl(): Promise<string> {
    const exported = await this.exportData();
    return [
      ...exported.evidence.map((row) => JSON.stringify({ type: "task_evidence_record", ...row })),
      ...exported.events.map((row) => JSON.stringify({ type: "task_session_event", ...row })),
      ...exported.workflowStates.map((row) =>
        JSON.stringify({ type: "task_current_state", ...row }),
      ),
      ...exported.entities.map((row) => JSON.stringify({ type: "task_wiki_entity", ...row })),
      ...exported.edges.map((row) => JSON.stringify({ type: "task_wiki_relation", ...row })),
    ].join("\n");
  }
}

export const CanonicalStore = FeishuTaskWikiStore;

export function getFeishuTaskWikiStore(agentId: string): FeishuTaskWikiStore {
  const cached = stores.get(agentId);
  if (cached) {
    return cached;
  }
  const store = new FeishuTaskWikiStore(agentId);
  stores.set(agentId, store);
  return store;
}

export function getCanonicalStore(agentId: string): FeishuTaskWikiStore {
  return getFeishuTaskWikiStore(agentId);
}

export async function closeAllFeishuTaskWikiStores(): Promise<void> {
  const count = stores.size;
  for (const store of stores.values()) {
    store.close();
  }
  stores.clear();
  log.info(`feishu_task_wiki.store.close_all count=${count}`);
}

export async function closeAllCanonicalStores(): Promise<void> {
  await closeAllFeishuTaskWikiStores();
}
