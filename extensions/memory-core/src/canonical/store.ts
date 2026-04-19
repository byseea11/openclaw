import os from "node:os";
import path from "node:path";
import type { DatabaseSync, SQLInputValue } from "node:sqlite";
import {
  createSubsystemLogger,
  resolveStateDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { deriveGraphObjects, normalizeEntityAlias } from "./kg.js";
import { runV0ToV1Migration } from "./migrations/v0-to-v1.js";
import { runV1ToV2Migration } from "./migrations/v1-to-v2.js";
import { runV2ToV3Migration } from "./migrations/v2-to-v3.js";
import { runV3ToV4Migration } from "./migrations/v3-to-v4.js";
import { reduce } from "./reducer.js";
import {
  CANONICAL_SCHEMA_SQL,
  CANONICAL_SCHEMA_VERSION,
  type CanonicalEntity,
  type CanonicalEntityType,
  type EntityAlias,
  EXTRACTOR_VERSION,
  type EntityState,
  type EventRecord,
  type GraphEdge,
  type GraphObjectSet,
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
  type WorkflowAdmission,
  type WorkflowObjectType,
  type WorkflowStateView,
  type WorkflowUpdate,
  type WorkflowUpdateResult,
} from "./schema.js";
import {
  deriveWorkflowUpdates,
  isWorkflowStateLayerEnabled,
  preliminaryWorkflowAdmission,
  sortWorkflowUpdatesDeterministically,
  type WorkflowBackfillMode,
  workflowBatchTypeConflictObjectIds,
  workflowSourcePriority,
  workflowUpdateId,
} from "./workflow.js";

const log = createSubsystemLogger("memory");
const stores = new Map<string, CanonicalStore>();

type EventRow = EventRecord & { fts_score?: number };
type EdgeRow = GraphEdge & {
  src_name?: string;
  src_type?: string;
  dst_name?: string;
  dst_type?: string;
};
type WorkflowSlotVersion = {
  event_id: string;
  occurred_at: string;
  source_kind: string;
  source_priority: number;
  confidence: number;
  update_id: string;
};
export type EntityResolutionCandidate = {
  entity_id: string;
  entity_type: CanonicalEntityType;
  canonical_name: string;
  match_kind: "stable_id" | "exact_alias" | "normalized_alias" | "canonical_name";
  matched_text: string;
  confidence: number;
  last_seen_at: string | null;
  updated_at: number;
};
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

export type EntityStateRefreshComputation = {
  entityIds: string[];
  previousStates: EntityState[];
  states: EntityState[];
  events: EventRecord[];
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
    object_type: normalizeEntityType(row.object_type),
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

function normalizeEntityType(value: unknown): CanonicalEntityType | null {
  switch (value) {
    case "person":
    case "team":
    case "project":
    case "task":
    case "decision":
    case "document":
    case "meeting":
    case "customer":
    case "other":
      return value;
    default:
      return null;
  }
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

function parseSlotVersions(value: unknown): Record<string, WorkflowSlotVersion> {
  if (typeof value !== "string" || !value.trim()) {
    return {};
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const versions: Record<string, WorkflowSlotVersion> = {};
    for (const [slot, rawVersion] of Object.entries(parsed)) {
      if (!rawVersion || typeof rawVersion !== "object" || Array.isArray(rawVersion)) {
        continue;
      }
      const version = rawVersion as Record<string, unknown>;
      if (
        typeof version.event_id === "string" &&
        typeof version.occurred_at === "string" &&
        typeof version.source_kind === "string" &&
        typeof version.update_id === "string"
      ) {
        versions[slot] = {
          event_id: version.event_id,
          occurred_at: version.occurred_at,
          source_kind: version.source_kind,
          source_priority: Number(version.source_priority ?? 0),
          confidence: Number(version.confidence ?? 0),
          update_id: version.update_id,
        };
      }
    }
    return versions;
  } catch {
    return {};
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

function normalizeWorkflowObjectType(value: unknown): WorkflowObjectType | null {
  switch (value) {
    case "task":
    case "project":
    case "approval":
    case "meeting":
    case "document":
    case "artifact":
      return value;
    default:
      return null;
  }
}

function normalizeBlockerStatus(value: unknown): WorkflowStateView["blocker_status"] {
  switch (value) {
    case "none":
    case "blocked":
    case "resolved":
    case "unknown":
      return value;
    default:
      return "unknown";
  }
}

function normalizeApprovalStatus(value: unknown): WorkflowStateView["approval_status"] {
  switch (value) {
    case "pending":
    case "approved":
    case "rejected":
    case "needs_review":
    case "unknown":
      return value;
    default:
      return "unknown";
  }
}

function rowToWorkflowState(row: Record<string, unknown>): WorkflowStateView {
  return {
    object_type: normalizeWorkflowObjectType(row.object_type) ?? "task",
    object_id: String(row.object_id),
    stage: typeof row.stage === "string" ? row.stage : null,
    owner_entity_id: typeof row.owner_entity_id === "string" ? row.owner_entity_id : null,
    blocker_status: normalizeBlockerStatus(row.blocker_status),
    blocker_reason: typeof row.blocker_reason === "string" ? row.blocker_reason : null,
    approval_status: normalizeApprovalStatus(row.approval_status),
    next_action: typeof row.next_action === "string" ? row.next_action : null,
    last_event_id: String(row.last_event_id),
    last_updated_at: Number(row.last_updated_at ?? 0),
    supporting_event_ids: parseStringArray(row.supporting_event_ids_json),
    conflict_flags: parseStringArray(row.conflict_flags_json),
    slot_versions: parseSlotVersions(row.slot_versions_json),
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

function rowToEntityAlias(row: Record<string, unknown>): EntityAlias {
  return {
    alias: String(row.alias),
    entity_id: String(row.entity_id),
    alias_type:
      row.alias_type === "normalized" || row.alias_type === "heuristic" ? row.alias_type : "exact",
    confidence: typeof row.confidence === "number" ? row.confidence : Number(row.confidence ?? 0.5),
    source_ref: typeof row.source_ref === "string" ? row.source_ref : null,
    session_id: typeof row.session_id === "string" ? row.session_id : null,
    created_at:
      typeof row.created_at === "number" ? row.created_at : Number(row.created_at ?? Date.now()),
  };
}

function rowToCanonicalEntity(row: Record<string, unknown>): CanonicalEntity {
  return {
    entity_id: String(row.entity_id),
    entity_type: normalizeEntityType(row.entity_type) ?? "other",
    canonical_name: String(row.canonical_name),
    status: typeof row.status === "string" ? row.status : null,
    last_seen_at: typeof row.last_seen_at === "string" ? row.last_seen_at : null,
    confidence: typeof row.confidence === "number" ? row.confidence : Number(row.confidence ?? 0.5),
    created_at: typeof row.created_at === "number" ? row.created_at : Number(row.created_at ?? 0),
    updated_at: typeof row.updated_at === "number" ? row.updated_at : Number(row.updated_at ?? 0),
    provenance_json: typeof row.provenance_json === "string" ? row.provenance_json : "[]",
  };
}

function rowToGraphEdge(row: Record<string, unknown>): EdgeRow {
  const relation = String(row.relation) as GraphEdge["relation"];
  return {
    edge_id: String(row.edge_id),
    src_entity_id: String(row.src_entity_id),
    relation,
    dst_entity_id: String(row.dst_entity_id),
    occurred_at: String(row.occurred_at),
    source_ref: String(row.source_ref),
    session_id: typeof row.session_id === "string" ? row.session_id : null,
    evidence_event_id: String(row.evidence_event_id),
    confidence: typeof row.confidence === "number" ? row.confidence : Number(row.confidence ?? 0.5),
    created_at: typeof row.created_at === "number" ? row.created_at : Number(row.created_at ?? 0),
    src_name: typeof row.src_name === "string" ? row.src_name : undefined,
    src_type: typeof row.src_type === "string" ? row.src_type : undefined,
    dst_name: typeof row.dst_name === "string" ? row.dst_name : undefined,
    dst_type: typeof row.dst_type === "string" ? row.dst_type : undefined,
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

function extractResolutionTokens(query: string): string[] {
  return [
    ...new Set(
      query
        .split(/[^\p{L}\p{N}_@-]+/u)
        .map((token) => normalizeEntityAlias(token))
        .filter((token) => token.length > 1),
    ),
  ].slice(0, 12);
}

function isStableEntityToken(token: string): boolean {
  return /^[a-z][a-z0-9]+-\d+$/i.test(token);
}

function canonicalNameTokenBonus(row: Record<string, unknown>, queryTokens: string[]): number {
  const canonicalName = typeof row.canonical_name === "string" ? row.canonical_name : "";
  const nameTokens = new Set(extractResolutionTokens(canonicalName));
  if (nameTokens.size === 0) {
    return 0;
  }
  const matched = queryTokens.filter((token) => nameTokens.has(token)).length;
  return Math.min(0.2, (matched / nameTokens.size) * 0.2);
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
      this.db.exec("DELETE FROM graph_edges");
      this.db.exec("DELETE FROM workflow_state_view");
      this.db.exec("DELETE FROM canonical_entities");
      this.db.exec("DELETE FROM entity_states");
      this.db.exec("DELETE FROM entity_aliases");
      this.db.exec("DELETE FROM kg_backfill_state");
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

  private upsertEventsInTransaction(records: EventRecord[]): void {
    if (records.length === 0) {
      log.info("canonical.store.upsert_events records=0");
      return;
    }
    const upsert = this.db.prepare(
      `INSERT OR REPLACE INTO event_records(
        event_id, source_type, source_ref, occurred_at, entity_id, actor, action, object, object_type,
        status_before, status_after, session_id, covered_until_entry_id, confidence,
        extractor_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const deleteFts = this.db.prepare("DELETE FROM event_fts WHERE event_id = ?");
    const insertFts = this.db.prepare(
      `INSERT INTO event_fts(event_id, entity_id, actor, action, object, status_after)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );
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
        record.object_type ?? null,
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
    log.info(`canonical.store.upsert_events records=${records.length}`);
  }

  async upsertEvents(records: EventRecord[]): Promise<void> {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.upsertEventsInTransaction(records);
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  private upsertGraphObjectsInTransaction(objects: GraphObjectSet): void {
    const upsertEntity = this.db.prepare(
      `INSERT INTO canonical_entities(
        entity_id, entity_type, canonical_name, status, last_seen_at, confidence,
        created_at, updated_at, provenance_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(entity_id) DO UPDATE SET
        entity_type = excluded.entity_type,
        canonical_name = excluded.canonical_name,
        status = COALESCE(excluded.status, canonical_entities.status),
        last_seen_at = CASE
          WHEN canonical_entities.last_seen_at IS NULL THEN excluded.last_seen_at
          WHEN excluded.last_seen_at IS NULL THEN canonical_entities.last_seen_at
          WHEN excluded.last_seen_at >= canonical_entities.last_seen_at THEN excluded.last_seen_at
          ELSE canonical_entities.last_seen_at
        END,
        confidence = MAX(canonical_entities.confidence, excluded.confidence),
        updated_at = excluded.updated_at,
        provenance_json = excluded.provenance_json`,
    );
    const upsertAlias = this.db.prepare(
      `INSERT INTO entity_aliases(
        alias, entity_id, alias_type, confidence, source_ref, session_id, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(alias, entity_id, alias_type) DO UPDATE SET
        confidence = MAX(entity_aliases.confidence, excluded.confidence),
        source_ref = COALESCE(entity_aliases.source_ref, excluded.source_ref),
        session_id = COALESCE(entity_aliases.session_id, excluded.session_id)`,
    );
    const upsertEdge = this.db.prepare(
      `INSERT INTO graph_edges(
        edge_id, src_entity_id, relation, dst_entity_id, occurred_at, source_ref,
        session_id, evidence_event_id, confidence, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(edge_id) DO UPDATE SET
        confidence = MAX(graph_edges.confidence, excluded.confidence)`,
    );
    for (const entity of objects.entities) {
      upsertEntity.run(
        entity.entity_id,
        entity.entity_type,
        entity.canonical_name,
        entity.status,
        entity.last_seen_at,
        entity.confidence,
        entity.created_at,
        entity.updated_at,
        entity.provenance_json,
      );
    }
    for (const alias of objects.aliases) {
      upsertAlias.run(
        alias.alias,
        alias.entity_id,
        alias.alias_type,
        alias.confidence,
        alias.source_ref,
        alias.session_id,
        alias.created_at,
      );
    }
    for (const edge of objects.edges) {
      upsertEdge.run(
        edge.edge_id,
        edge.src_entity_id,
        edge.relation,
        edge.dst_entity_id,
        edge.occurred_at,
        edge.source_ref,
        edge.session_id,
        edge.evidence_event_id,
        edge.confidence,
        edge.created_at,
      );
    }
    log.info(
      `canonical.store.upsert_kg entities=${objects.entities.length} aliases=${objects.aliases.length} edges=${objects.edges.length}`,
    );
  }

  async upsertGraphObjects(objects: GraphObjectSet): Promise<void> {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.upsertGraphObjectsInTransaction(objects);
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  private getWorkflowStateByObjectIdInTransaction(objectId: string): WorkflowStateView | null {
    const row = this.db
      .prepare("SELECT * FROM workflow_state_view WHERE object_id = ?")
      .get(objectId) as Record<string, unknown> | undefined;
    return row ? rowToWorkflowState(row) : null;
  }

  private compareWorkflowSlotVersion(
    update: WorkflowUpdate,
    updateId: string,
    previous: WorkflowSlotVersion | undefined,
  ): { apply: boolean; reason?: WorkflowUpdateResult["ignored_slots"][number]["reason"] } {
    if (!previous) {
      return { apply: true };
    }
    const sourcePriority = workflowSourcePriority(update.source.source_kind);
    const fields: Array<[number | string, number | string]> = [
      [Date.parse(update.occurred_at), Date.parse(previous.occurred_at)],
      [sourcePriority, previous.source_priority],
      [update.evidence.confidence, previous.confidence],
      [update.evidence.event_id, previous.event_id],
      [updateId, previous.update_id],
    ];
    for (const [next, current] of fields) {
      if (typeof next === "number" && typeof current === "number") {
        if (next > current) {
          return { apply: true };
        }
        if (next < current) {
          return {
            apply: false,
            reason: next < Date.parse(previous.occurred_at) ? "stale" : "lower_priority",
          };
        }
      } else {
        const delta = String(next).localeCompare(String(current));
        if (delta > 0) {
          return { apply: true };
        }
        if (delta < 0) {
          return { apply: false, reason: "lower_priority" };
        }
      }
    }
    return { apply: false, reason: "duplicate" };
  }

  private workflowAdmissionForUpdate(
    update: WorkflowUpdate,
    existing: WorkflowStateView | null,
    hasBatchTypeConflict: boolean,
    hadPreexistingRow: boolean,
  ): {
    admission: WorkflowAdmission;
    ignored: WorkflowUpdateResult["ignored_slots"];
  } {
    const ignored: WorkflowUpdateResult["ignored_slots"] = [];
    if (update.object_id !== update.derived.canonical_entity_id) {
      ignored.push({ slot: "object_id", reason: "type_conflict" });
      return { admission: "reject", ignored };
    }
    if (hasBatchTypeConflict) {
      ignored.push({ slot: "object_type", reason: "type_conflict" });
      return { admission: hadPreexistingRow ? "evidence_only" : "reject", ignored };
    }
    if (existing && existing.object_type !== update.object_type) {
      ignored.push({ slot: "object_type", reason: "type_conflict" });
      return { admission: "evidence_only", ignored };
    }
    if (update.evidence.resolution_status !== "stable") {
      ignored.push({ slot: "object_id", reason: "ambiguous" });
      return { admission: existing ? "evidence_only" : "reject", ignored };
    }
    if (update.evidence.relation_strength === "weak") {
      ignored.push({ slot: "patch", reason: "weak_relation" });
      return { admission: existing ? "evidence_only" : "reject", ignored };
    }
    if (update.source.source_kind === "backfill") {
      return { admission: existing ? "evidence_only" : "current_state_patch", ignored };
    }
    return { admission: preliminaryWorkflowAdmission(update), ignored };
  }

  private applyWorkflowUpdateInTransaction(
    update: WorkflowUpdate,
    hasBatchTypeConflict: boolean,
    hadPreexistingRow: boolean,
  ): WorkflowUpdateResult {
    const updateId = update.update_id ?? workflowUpdateId(update);
    const existing = this.getWorkflowStateByObjectIdInTransaction(update.object_id);
    const { admission, ignored } = this.workflowAdmissionForUpdate(
      update,
      existing,
      hasBatchTypeConflict,
      hadPreexistingRow,
    );
    const supportingEventIds = new Set(existing?.supporting_event_ids ?? []);
    const conflictFlags = new Set(existing?.conflict_flags ?? []);
    for (const eventId of [
      update.evidence.event_id,
      ...(update.evidence.supporting_event_ids ?? []),
      ...(update.patch.append?.supporting_event_ids ?? []),
    ]) {
      if (eventId) {
        supportingEventIds.add(eventId);
      }
    }
    const conflictFlagsAdded: string[] = [];
    for (const flag of update.patch.append?.conflict_flags ?? []) {
      if (!conflictFlags.has(flag)) {
        conflictFlags.add(flag);
        conflictFlagsAdded.push(flag);
      }
    }
    if (admission === "reject") {
      return {
        update_id: updateId,
        object_type: update.object_type,
        object_id: update.object_id,
        admission,
        applied: false,
        changed_slots: [],
        ignored_slots: ignored,
        conflict_flags_added: [],
      };
    }

    const next: WorkflowStateView = existing ?? {
      object_type: update.object_type,
      object_id: update.object_id,
      stage: null,
      owner_entity_id: null,
      blocker_status: "unknown",
      blocker_reason: null,
      approval_status: "unknown",
      next_action: null,
      last_event_id: update.evidence.event_id,
      last_updated_at: Date.parse(update.occurred_at) || Date.now(),
      supporting_event_ids: [],
      conflict_flags: [],
      slot_versions: {},
    };
    const slotVersions = parseSlotVersions(JSON.stringify(next.slot_versions));
    const changedSlots: string[] = [];
    const setSlot = <
      K extends keyof Pick<
        WorkflowStateView,
        | "stage"
        | "owner_entity_id"
        | "blocker_status"
        | "blocker_reason"
        | "approval_status"
        | "next_action"
      >,
    >(
      slot: K,
      value: WorkflowStateView[K],
    ) => {
      if (admission !== "current_state_patch") {
        ignored.push({ slot, reason: "lower_priority" });
        return;
      }
      const decision = this.compareWorkflowSlotVersion(update, updateId, slotVersions[slot]);
      if (!decision.apply) {
        ignored.push({ slot, reason: decision.reason ?? "lower_priority" });
        return;
      }
      if (next[slot] !== value) {
        next[slot] = value;
        changedSlots.push(slot);
      }
      slotVersions[slot] = {
        event_id: update.evidence.event_id,
        occurred_at: update.occurred_at,
        source_kind: update.source.source_kind,
        source_priority: workflowSourcePriority(update.source.source_kind),
        confidence: update.evidence.confidence,
        update_id: updateId,
      };
    };
    const patchSet = update.patch.set ?? {};
    if ("stage" in patchSet) {
      setSlot("stage", patchSet.stage ?? null);
    }
    if ("owner_entity_id" in patchSet) {
      setSlot("owner_entity_id", patchSet.owner_entity_id ?? null);
    }
    if ("blocker_status" in patchSet) {
      setSlot("blocker_status", patchSet.blocker_status ?? "unknown");
    }
    if ("blocker_reason" in patchSet) {
      setSlot("blocker_reason", patchSet.blocker_reason ?? null);
    }
    if ("approval_status" in patchSet) {
      setSlot("approval_status", patchSet.approval_status ?? "unknown");
    }
    if ("next_action" in patchSet) {
      setSlot("next_action", patchSet.next_action ?? null);
    }
    for (const clearSlot of update.patch.clear ?? []) {
      switch (clearSlot) {
        case "approval_status":
          setSlot("approval_status", "unknown");
          break;
        case "stage":
        case "owner_entity_id":
        case "blocker_reason":
        case "next_action":
          setSlot(clearSlot, null);
          break;
      }
    }
    if (update.patch.resolve?.blocker) {
      setSlot("blocker_status", "resolved");
    }
    if (update.patch.resolve?.approval) {
      setSlot("approval_status", "approved");
    }
    const changedOrNew = changedSlots.length > 0 || !existing;
    if (changedSlots.length > 0) {
      next.last_event_id = update.evidence.event_id;
      next.last_updated_at = Date.parse(update.occurred_at) || Date.now();
    }
    next.supporting_event_ids = [...supportingEventIds].toSorted();
    next.conflict_flags = [...conflictFlags].toSorted();
    next.slot_versions = slotVersions;
    const upsert = this.db.prepare(
      `INSERT INTO workflow_state_view(
        object_type, object_id, stage, owner_entity_id, blocker_status, blocker_reason,
        approval_status, next_action, last_event_id, last_updated_at, supporting_event_ids_json,
        conflict_flags_json, slot_versions_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(object_type, object_id) DO UPDATE SET
        stage = excluded.stage,
        owner_entity_id = excluded.owner_entity_id,
        blocker_status = excluded.blocker_status,
        blocker_reason = excluded.blocker_reason,
        approval_status = excluded.approval_status,
        next_action = excluded.next_action,
        last_event_id = excluded.last_event_id,
        last_updated_at = excluded.last_updated_at,
        supporting_event_ids_json = excluded.supporting_event_ids_json,
        conflict_flags_json = excluded.conflict_flags_json,
        slot_versions_json = excluded.slot_versions_json`,
    );
    upsert.run(
      next.object_type,
      next.object_id,
      next.stage,
      next.owner_entity_id,
      next.blocker_status,
      next.blocker_reason,
      next.approval_status,
      next.next_action,
      next.last_event_id,
      next.last_updated_at,
      JSON.stringify(next.supporting_event_ids),
      JSON.stringify(next.conflict_flags),
      JSON.stringify(next.slot_versions),
    );
    return {
      update_id: updateId,
      object_type: update.object_type,
      object_id: update.object_id,
      admission,
      applied: changedOrNew || conflictFlagsAdded.length > 0,
      changed_slots: changedSlots,
      ignored_slots: ignored,
      conflict_flags_added: conflictFlagsAdded,
    };
  }

  private applyWorkflowUpdatesInTransaction(updates: WorkflowUpdate[]): WorkflowUpdateResult[] {
    const sorted = sortWorkflowUpdatesDeterministically(updates);
    const conflictObjectIds = workflowBatchTypeConflictObjectIds(sorted);
    const preexistingObjectIds = new Set(
      [...conflictObjectIds].filter((objectId) =>
        this.getWorkflowStateByObjectIdInTransaction(objectId),
      ),
    );
    return sorted.map((update) =>
      this.applyWorkflowUpdateInTransaction(
        update,
        conflictObjectIds.has(update.object_id),
        preexistingObjectIds.has(update.object_id),
      ),
    );
  }

  async applyWorkflowUpdate(update: WorkflowUpdate): Promise<WorkflowUpdateResult> {
    const [result] = await this.applyWorkflowUpdates([update]);
    return (
      result ?? {
        update_id: update.update_id ?? workflowUpdateId(update),
        object_type: update.object_type,
        object_id: update.object_id,
        admission: "reject",
        applied: false,
        changed_slots: [],
        ignored_slots: [{ slot: "update", reason: "duplicate" }],
        conflict_flags_added: [],
      }
    );
  }

  async applyWorkflowUpdates(updates: WorkflowUpdate[]): Promise<WorkflowUpdateResult[]> {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const results = this.applyWorkflowUpdatesInTransaction(updates);
      this.db.exec("COMMIT");
      return results;
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  async persistCanonicalBatch(
    records: EventRecord[],
    computed?: EntityStateRefreshComputation,
  ): Promise<{
    states: EntityState[];
    graphObjects: GraphObjectSet;
    workflowResults: WorkflowUpdateResult[];
  }> {
    const mergeComputation = computed ?? (await this.computeEntityStateRefresh(records));
    const graphObjects = deriveGraphObjects(records);
    const workflowUpdates = isWorkflowStateLayerEnabled()
      ? deriveWorkflowUpdates(records, graphObjects)
      : [];
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.upsertEventsInTransaction(records);
      this.upsertGraphObjectsInTransaction(graphObjects);
      const states = this.refreshEntityStatesInTransaction(mergeComputation.states);
      const workflowResults = this.applyWorkflowUpdatesInTransaction(workflowUpdates);
      this.setMeta("extractor_version", EXTRACTOR_VERSION);
      this.db.exec("COMMIT");
      return { states, graphObjects, workflowResults };
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
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
    const nowMs = Number.isFinite(params.nowMs) ? (params.nowMs as number) : Date.now();
    this.db
      .prepare(
        `INSERT INTO kg_backfill_state(
          scope, last_event_created_at, last_event_id, status, last_error, retry_marker_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scope) DO UPDATE SET
          status = excluded.status,
          last_error = excluded.last_error,
          retry_marker_json = excluded.retry_marker_json,
          updated_at = excluded.updated_at`,
      )
      .run(
        params.scope,
        params.lastEventCreatedAt ?? null,
        params.lastEventId ?? null,
        params.status,
        params.error ?? null,
        params.retryMarker ? JSON.stringify(params.retryMarker) : null,
        nowMs,
      );
  }

  private async computeEntityStateRefresh(
    records: EventRecord[],
  ): Promise<EntityStateRefreshComputation> {
    const entityIds = [...new Set(records.map((record) => record.entity_id))];
    const prevStates = new Map<string, EntityState>();
    for (const entityId of entityIds) {
      const state = await this.getEntityState(entityId);
      if (state) {
        prevStates.set(entityId, state);
      }
    }
    return {
      entityIds,
      previousStates: [...prevStates.values()],
      states: reduce(records, prevStates),
      events: records,
    };
  }

  async explainEntityStateRefresh(records: EventRecord[]): Promise<EntityStateRefreshComputation> {
    return this.computeEntityStateRefresh(records);
  }

  private refreshEntityStatesInTransaction(states: EntityState[]): EntityState[] {
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
    log.info(`canonical.store.refresh_states states=${states.length}`);
    return states;
  }

  async refreshEntityStates(
    records: EventRecord[],
    computed?: EntityStateRefreshComputation,
  ): Promise<EntityState[]> {
    const states = (computed ?? (await this.computeEntityStateRefresh(records))).states;
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.refreshEntityStatesInTransaction(states);
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    return states;
  }

  async getEntityState(entityId: string): Promise<EntityState | null> {
    const row = this.db.prepare("SELECT * FROM entity_states WHERE entity_id = ?").get(entityId) as
      | Record<string, unknown>
      | undefined;
    return row ? rowToState(row) : null;
  }

  getCanonicalEntity(entityId: string): CanonicalEntity | null {
    const row = this.db
      .prepare("SELECT * FROM canonical_entities WHERE entity_id = ?")
      .get(entityId) as Record<string, unknown> | undefined;
    return row ? rowToCanonicalEntity(row) : null;
  }

  getWorkflowState(objectType: WorkflowObjectType, objectId: string): WorkflowStateView | null {
    const row = this.db
      .prepare(
        `SELECT * FROM workflow_state_view
         WHERE object_type = ? AND object_id = ?`,
      )
      .get(objectType, objectId) as Record<string, unknown> | undefined;
    return row ? rowToWorkflowState(row) : null;
  }

  getWorkflowStateByObjectId(objectId: string): WorkflowStateView | null {
    const row = this.db
      .prepare("SELECT * FROM workflow_state_view WHERE object_id = ?")
      .get(objectId) as Record<string, unknown> | undefined;
    return row ? rowToWorkflowState(row) : null;
  }

  listWorkflowStates(): WorkflowStateView[] {
    const rows = this.db
      .prepare("SELECT * FROM workflow_state_view ORDER BY object_type ASC, object_id ASC")
      .all() as Array<Record<string, unknown>>;
    return rows.map(rowToWorkflowState);
  }

  resolveEntityIds(query: string, limit = 8): string[] {
    const tokens = query
      .split(/[^\p{L}\p{N}_@-]+/u)
      .map((token) => token.trim().toLowerCase())
      .filter((token) => token.length > 1)
      .slice(0, 8);
    const ids = new Set<string>();
    const aliasLookup = this.db.prepare(
      `SELECT entity_id FROM entity_aliases
       WHERE alias = ? OR alias LIKE ?
       ORDER BY confidence DESC, created_at DESC
       LIMIT ?`,
    );
    const entityLookup = this.db.prepare(
      `SELECT entity_id FROM canonical_entities
       WHERE lower(canonical_name) = ? OR lower(canonical_name) LIKE ?
       ORDER BY confidence DESC, updated_at DESC
       LIMIT ?`,
    );
    for (const token of tokens) {
      const pattern = `%${token}%`;
      for (const row of aliasLookup.all(token, pattern, limit) as Array<Record<string, unknown>>) {
        ids.add(String(row.entity_id));
      }
      for (const row of entityLookup.all(token, pattern, limit) as Array<Record<string, unknown>>) {
        ids.add(String(row.entity_id));
      }
      if (ids.size >= limit) {
        break;
      }
    }
    return [...ids].slice(0, limit);
  }

  resolveEntityCandidates(query: string, limit = 8): EntityResolutionCandidate[] {
    const tokens = extractResolutionTokens(query);
    if (tokens.length === 0) {
      return [];
    }
    const candidates = new Map<string, EntityResolutionCandidate>();
    const addCandidate = (
      row: Record<string, unknown>,
      matchKind: EntityResolutionCandidate["match_kind"],
      matchedText: string,
      confidenceBonus = 0,
    ) => {
      const entityId = String(row.entity_id);
      const confidence = Math.min(1, Number(row.confidence ?? 0.5) + confidenceBonus);
      const candidate: EntityResolutionCandidate = {
        entity_id: entityId,
        entity_type: normalizeEntityType(row.entity_type) ?? "other",
        canonical_name: typeof row.canonical_name === "string" ? row.canonical_name : entityId,
        match_kind: matchKind,
        matched_text: matchedText,
        confidence,
        last_seen_at: typeof row.last_seen_at === "string" ? row.last_seen_at : null,
        updated_at: Number(row.updated_at ?? row.created_at ?? 0),
      };
      const existing = candidates.get(entityId);
      if (
        !existing ||
        confidence > existing.confidence ||
        (confidence === existing.confidence && candidate.updated_at > existing.updated_at)
      ) {
        candidates.set(entityId, candidate);
      }
    };
    const aliasLookup = this.db.prepare(
      `SELECT
         a.alias,
         a.alias_type,
         a.confidence,
         e.entity_id,
         e.entity_type,
         e.canonical_name,
         e.last_seen_at,
         e.updated_at,
         e.created_at
       FROM entity_aliases a
       JOIN canonical_entities e ON e.entity_id = a.entity_id
       WHERE a.alias = ?
       ORDER BY a.confidence DESC, e.updated_at DESC
       LIMIT ?`,
    );
    const canonicalExactLookup = this.db.prepare(
      `SELECT * FROM canonical_entities
       WHERE lower(canonical_name) = ?
       ORDER BY confidence DESC, updated_at DESC
       LIMIT ?`,
    );
    const canonicalLikeLookup = this.db.prepare(
      `SELECT * FROM canonical_entities
       WHERE lower(canonical_name) LIKE ?
       ORDER BY confidence DESC, updated_at DESC
       LIMIT ?`,
    );
    for (const token of tokens) {
      for (const row of aliasLookup.all(token, limit) as Array<Record<string, unknown>>) {
        addCandidate(row, isStableEntityToken(token) ? "stable_id" : "exact_alias", token, 0.15);
      }
      for (const row of canonicalExactLookup.all(token, limit) as Array<Record<string, unknown>>) {
        addCandidate(
          row,
          isStableEntityToken(token) ? "stable_id" : "canonical_name",
          token,
          0.1 + canonicalNameTokenBonus(row, tokens),
        );
      }
    }
    const normalizedQuery = normalizeEntityAlias(query);
    if (normalizedQuery) {
      for (const row of aliasLookup.all(normalizedQuery, limit) as Array<Record<string, unknown>>) {
        addCandidate(row, "normalized_alias", normalizedQuery, 0.05);
      }
    }
    for (const token of tokens) {
      const pattern = `${token}%`;
      for (const row of canonicalLikeLookup.all(pattern, limit) as Array<Record<string, unknown>>) {
        addCandidate(row, "canonical_name", token, canonicalNameTokenBonus(row, tokens));
      }
    }
    return [...candidates.values()]
      .toSorted((left, right) => {
        if (left.confidence !== right.confidence) {
          return right.confidence - left.confidence;
        }
        if (left.updated_at !== right.updated_at) {
          return right.updated_at - left.updated_at;
        }
        return left.entity_id.localeCompare(right.entity_id);
      })
      .slice(0, limit);
  }

  searchGraphEdges(params: {
    entityIds?: string[];
    relations?: string[];
    includeWeak?: boolean;
    limit: number;
  }): EdgeRow[] {
    const clauses: string[] = [];
    const args: SQLInputValue[] = [];
    const entityIds = [...new Set(params.entityIds ?? [])].filter(Boolean);
    if (entityIds.length > 0) {
      const placeholders = entityIds.map(() => "?").join(", ");
      clauses.push(
        `(g.src_entity_id IN (${placeholders}) OR g.dst_entity_id IN (${placeholders}))`,
      );
      args.push(...entityIds, ...entityIds);
    }
    const relations = [...new Set(params.relations ?? [])].filter(Boolean);
    if (relations.length > 0) {
      clauses.push(`g.relation IN (${relations.map(() => "?").join(", ")})`);
      args.push(...relations);
    } else if (!params.includeWeak) {
      clauses.push("g.relation NOT IN ('about', 'mentions', 'related_to')");
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const rows = this.db
      .prepare(
        `SELECT
           g.*,
           src.canonical_name AS src_name,
           src.entity_type AS src_type,
           dst.canonical_name AS dst_name,
           dst.entity_type AS dst_type
         FROM graph_edges g
         LEFT JOIN canonical_entities src ON src.entity_id = g.src_entity_id
         LEFT JOIN canonical_entities dst ON dst.entity_id = g.dst_entity_id
         ${where}
         ORDER BY g.confidence DESC, g.occurred_at DESC, g.created_at DESC
         LIMIT ?`,
      )
      .all(...args, Math.max(1, params.limit)) as Array<Record<string, unknown>>;
    return rows.map(rowToGraphEdge);
  }

  getEventsByIds(eventIds: string[]): EventRecord[] {
    const ids = [...new Set(eventIds)].filter(Boolean);
    if (ids.length === 0) {
      return [];
    }
    const rows = this.db
      .prepare(
        `SELECT * FROM event_records
         WHERE event_id IN (${ids.map(() => "?").join(", ")})
         ORDER BY occurred_at DESC, created_at DESC`,
      )
      .all(...ids) as Array<Record<string, unknown>>;
    return rows.map(rowToEvent);
  }

  listProjectionStates(): ProjectionSourceState[] {
    const rows = this.db
      .prepare("SELECT * FROM source_projection_state ORDER BY source_id ASC")
      .all() as Array<Record<string, unknown>>;
    return rows.map(rowToProjectionState);
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

  listEventsForKgBackfill(params: { scope: string; limit?: number }): EventRecord[] {
    const state = this.db
      .prepare("SELECT * FROM kg_backfill_state WHERE scope = ?")
      .get(params.scope) as Record<string, unknown> | undefined;
    const lastCreatedAt =
      typeof state?.last_event_created_at === "number"
        ? state.last_event_created_at
        : state?.last_event_created_at == null
          ? null
          : Number(state.last_event_created_at);
    const lastEventId = typeof state?.last_event_id === "string" ? state.last_event_id : null;
    const limit = Math.max(1, params.limit ?? 200);
    const rows =
      lastCreatedAt == null || !lastEventId
        ? (this.db
            .prepare("SELECT * FROM event_records ORDER BY created_at ASC, event_id ASC LIMIT ?")
            .all(limit) as Array<Record<string, unknown>>)
        : (this.db
            .prepare(
              `SELECT * FROM event_records
               WHERE created_at > ? OR (created_at = ? AND event_id > ?)
               ORDER BY created_at ASC, event_id ASC
               LIMIT ?`,
            )
            .all(lastCreatedAt, lastCreatedAt, lastEventId, limit) as Array<
            Record<string, unknown>
          >);
    return rows.map(rowToEvent);
  }

  async backfillGraphObjectsFromEvents(
    params: {
      scope?: string;
      batchSize?: number;
      includeWorkflowState?: boolean;
    } = {},
  ): Promise<{
    processedEvents: number;
    entities: number;
    aliases: number;
    edges: number;
    workflowUpdates: number;
  }> {
    const scope = params.scope ?? "events";
    const batchSize = params.batchSize ?? 200;
    const backfillMode: WorkflowBackfillMode =
      params.includeWorkflowState && isWorkflowStateLayerEnabled()
        ? "graph_and_workflow"
        : "graph_only";
    const records = this.listEventsForKgBackfill({
      scope,
      limit: batchSize,
    });
    if (records.length === 0) {
      this.recordKgRetryMarker({ scope, status: "complete" });
      return { processedEvents: 0, entities: 0, aliases: 0, edges: 0, workflowUpdates: 0 };
    }
    const graphObjects = deriveGraphObjects(records);
    const workflowUpdates =
      backfillMode === "graph_and_workflow"
        ? deriveWorkflowUpdates(records, graphObjects, { sourceKind: "backfill" })
        : [];
    const last = records.at(-1);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.upsertGraphObjectsInTransaction(graphObjects);
      if (workflowUpdates.length > 0) {
        this.applyWorkflowUpdatesInTransaction(workflowUpdates);
      }
      this.db
        .prepare(
          `INSERT INTO kg_backfill_state(
            scope, last_event_created_at, last_event_id, status, last_error, retry_marker_json, updated_at
          ) VALUES (?, ?, ?, ?, NULL, NULL, ?)
          ON CONFLICT(scope) DO UPDATE SET
            last_event_created_at = excluded.last_event_created_at,
            last_event_id = excluded.last_event_id,
            status = excluded.status,
            last_error = NULL,
            retry_marker_json = NULL,
            updated_at = excluded.updated_at`,
        )
        .run(
          scope,
          last?.created_at ?? null,
          last?.event_id ?? null,
          records.length < batchSize ? "complete" : "running",
          Date.now(),
        );
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      this.recordKgRetryMarker({
        scope,
        status: "failed",
        error: String(err),
        retryMarker: { function: "backfillGraphObjectsFromEvents" },
      });
      throw err;
    }
    return {
      processedEvents: records.length,
      entities: graphObjects.entities.length,
      aliases: graphObjects.aliases.length,
      edges: graphObjects.edges.length,
      workflowUpdates: workflowUpdates.length,
    };
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
    const kgEntityRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM canonical_entities")
      .get() as {
      count?: number;
    };
    const edgeRow = this.db.prepare("SELECT COUNT(*) AS count FROM graph_edges").get() as {
      count?: number;
    };
    const workflowRow = this.db
      .prepare("SELECT COUNT(*) AS count FROM workflow_state_view")
      .get() as {
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
      canonicalEntitiesTotal: kgEntityRow.count ?? 0,
      graphEdgesTotal: edgeRow.count ?? 0,
      workflowStatesTotal: workflowRow.count ?? 0,
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
            .prepare("SELECT * FROM entity_aliases WHERE entity_id = ? ORDER BY alias ASC")
            .all(canonicalId.trim()) as Array<Record<string, unknown>>)
        : (this.db
            .prepare("SELECT * FROM entity_aliases ORDER BY entity_id ASC, alias ASC")
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
