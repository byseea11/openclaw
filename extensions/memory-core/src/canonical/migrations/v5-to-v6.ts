import type { DatabaseSync } from "node:sqlite";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { canonicalJson, generateUlid, normalizeName, normalizeWhitespace } from "../id-v2.js";
import {
  buildEdgeKey,
  buildEvidenceFingerprint,
  buildEventFingerprint,
  EVENT_TYPE_REGISTRY_SEED,
  normalizeBlockerRef,
  normalizeTypedPersonRef,
  type EventRecordV2,
} from "../schema-v2.js";

const log = createSubsystemLogger("memory");

type LegacyEventRow = {
  event_id: string;
  source_type: string;
  source_ref: string;
  occurred_at: string;
  entity_id: string;
  actor: string | null;
  action: string;
  object: string | null;
  object_type: string | null;
  status_before: string | null;
  status_after: string | null;
  session_id: string | null;
  covered_until_entry_id: string | null;
  confidence: number;
  extractor_version: string;
  created_at: number;
};

type LegacyEntityMeta = {
  canonical_name: string | null;
  entity_type: string | null;
  aliases: string[];
};

type WorkflowRow = {
  task_ref: string;
  current_owner_ref: string | null;
  current_stage: string | null;
  current_approval_ref: string | null;
  approval_status: string | null;
  current_blocker_ref: string | null;
  next_action_json: string;
  last_event_id: string;
  last_event_time: string;
  slot_versions_json: string;
  supporting_event_ids: string;
  updated_at: number;
};

type GraphEntityRow = {
  entity_ref: string;
  entity_type: string;
  canonical_name: string;
  alias_json: string;
  first_seen_at: string;
  last_seen_at: string;
  last_evidence_id: string | null;
  updated_at: number;
};

type GraphEdgeRow = {
  edge_id: string;
  edge_key: string;
  src_ref: string;
  edge_type: string;
  dst_ref: string;
  derived_from_event_id: string;
  active: number;
  valid_from: string;
  valid_to: string | null;
  updated_at: number;
};

function hasTable(db: DatabaseSync, name: string): boolean {
  const row = db
    .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?")
    .get(name) as { name?: string } | undefined;
  return row?.name === name;
}

function hasColumn(db: DatabaseSync, table: string, column: string): boolean {
  const rows = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name?: string }>;
  return rows.some((row) => row.name === column);
}

function ticketRef(text: string | null | undefined): string | null {
  const match = text?.match(/\b([A-Z][A-Z0-9]+-\d+)\b/);
  return match?.[1] ? `task:${match[1]}` : null;
}

function approvalRef(text: string | null | undefined): string | null {
  const match = text?.match(/\b(AP-\d+)\b/i);
  return match?.[1] ? `approval:${match[1].toUpperCase()}` : null;
}

function textRef(
  text: string | null | undefined,
  expectedType: "task" | "approval",
): string | null {
  if (!text) {
    return null;
  }
  const normalized = normalizeWhitespace(text);
  if (!normalized || /\s/.test(normalized)) {
    return null;
  }
  if (expectedType === "task") {
    return `task:${normalized}`;
  }
  return `approval:${normalized}`;
}

function legacySummary(row: LegacyEventRow): string {
  return [row.actor, row.action, row.object, row.status_after].filter(Boolean).join(" ").trim();
}

function inferSubjectRef(row: LegacyEventRow, meta: LegacyEntityMeta | undefined): string | null {
  return (
    ticketRef(row.object) ??
    ticketRef(meta?.canonical_name) ??
    meta?.aliases.map((alias) => ticketRef(alias)).find(Boolean) ??
    (meta?.entity_type === "task"
      ? (textRef(meta.canonical_name, "task") ??
        meta.aliases.map((alias) => textRef(alias, "task")).find(Boolean) ??
        textRef(row.object, "task"))
      : null)
  );
}

function inferEventType(
  row: LegacyEventRow,
  meta: LegacyEntityMeta | undefined,
): EventRecordV2["event_type"] | null {
  const action = normalizeName(row.action);
  const status = normalizeName(row.status_after ?? "");
  const combined = normalizeName(
    [row.action, row.object, row.status_after, meta?.canonical_name].join(" "),
  );
  if (/(assigned|owner|assignee|responsible|接手|负责人)/i.test(action)) {
    return "owner_changed";
  }
  if (/(next_action|next action|下一步)/i.test(combined)) {
    return "next_action_set";
  }
  if (/(approval|approved|rejected|needs_review|needs review|审批)/i.test(combined)) {
    return "approval_status_updated";
  }
  if (status === "blocked" || /(blocked|blocker|dependency|depends|卡)/i.test(combined)) {
    return "blocked";
  }
  if (
    status === "unblocked" ||
    status === "resolved" ||
    /(unblocked|resolved|解除阻塞)/i.test(combined)
  ) {
    return "unblocked";
  }
  if (row.status_after || row.status_before) {
    return "stage_changed";
  }
  return null;
}

function inferActorRef(row: LegacyEventRow, meta: LegacyEntityMeta | undefined): string | null {
  return normalizeTypedPersonRef({
    name: row.actor ?? (meta?.entity_type === "person" ? meta.canonical_name : null),
  });
}

function inferObjectRef(
  row: LegacyEventRow,
  eventType: EventRecordV2["event_type"],
): string | null {
  if (eventType === "owner_changed" || eventType === "next_action_set") {
    return normalizeTypedPersonRef({ name: row.actor ?? row.object });
  }
  if (eventType === "approval_status_updated") {
    return approvalRef(row.object);
  }
  if (eventType === "blocked" || eventType === "unblocked") {
    return approvalRef(row.object) ?? normalizeBlockerRef(row.object ?? row.action);
  }
  return null;
}

function payloadForLegacyEvent(
  row: LegacyEventRow,
  eventType: EventRecordV2["event_type"],
  actorRef: string | null,
  objectRef: string | null,
): Record<string, unknown> {
  switch (eventType) {
    case "owner_changed":
      return {
        new_owner_ref: objectRef ?? actorRef,
        old_owner_ref: null,
        reason: legacySummary(row) || null,
      };
    case "stage_changed":
      return {
        new_stage: row.status_after ?? row.action,
        old_stage: row.status_before,
        reason: legacySummary(row) || null,
      };
    case "approval_status_updated":
      return {
        approval_ref: objectRef,
        approval_status: row.status_after ?? "pending",
        reason: legacySummary(row) || null,
      };
    case "blocked":
      return {
        blocker_ref: objectRef,
        blocker_reason: row.object ?? legacySummary(row),
      };
    case "unblocked":
      return {
        blocker_ref: objectRef,
        blocker_reason: row.object ?? null,
        resumed_stage: "in_progress",
      };
    case "next_action_set":
      return {
        assignee_ref: objectRef ?? actorRef,
        action_text: row.object ?? legacySummary(row),
      };
    default:
      return {};
  }
}

function parseStringArray(value: unknown): string[] {
  if (typeof value !== "string" || !value.trim()) {
    return [];
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed)
      ? [...new Set(parsed.filter((entry): entry is string => typeof entry === "string"))]
      : [];
  } catch {
    return [];
  }
}

function upsertWorkflowState(
  states: Map<string, WorkflowRow>,
  event: EventRecordV2,
  workflowEventId: string,
): void {
  if (!event.subject_ref.startsWith("task:")) {
    return;
  }
  const taskRef = event.subject_ref;
  const payload = JSON.parse(event.payload_json) as Record<string, unknown>;
  const current = states.get(taskRef) ?? {
    task_ref: taskRef,
    current_owner_ref: null,
    current_stage: null,
    current_approval_ref: null,
    approval_status: null,
    current_blocker_ref: null,
    next_action_json: "{}",
    last_event_id: workflowEventId,
    last_event_time: event.occurred_at,
    slot_versions_json: "{}",
    supporting_event_ids: "[]",
    updated_at: event.created_at,
  };
  const slotVersions = JSON.parse(current.slot_versions_json) as Record<string, unknown>;
  const supporting = new Set(parseStringArray(current.supporting_event_ids));
  const applySlot = (slot: string, apply: () => void) => {
    const previous = slotVersions[slot] as Record<string, unknown> | undefined;
    const previousTime = typeof previous?.occurred_at === "string" ? previous.occurred_at : "";
    if (previousTime && previousTime > event.occurred_at) {
      return;
    }
    apply();
    slotVersions[slot] = {
      event_id: workflowEventId,
      event_fingerprint: event.event_fingerprint,
      occurred_at: event.occurred_at,
    };
  };

  switch (event.event_type) {
    case "owner_changed":
      applySlot("current_owner_ref", () => {
        current.current_owner_ref =
          (typeof payload.new_owner_ref === "string" ? payload.new_owner_ref : event.object_ref) ??
          null;
      });
      break;
    case "stage_changed":
      applySlot("current_stage", () => {
        current.current_stage = typeof payload.new_stage === "string" ? payload.new_stage : null;
      });
      break;
    case "approval_status_updated":
      applySlot("current_approval_ref", () => {
        current.current_approval_ref =
          (typeof payload.approval_ref === "string" ? payload.approval_ref : event.object_ref) ??
          null;
      });
      applySlot("approval_status", () => {
        current.approval_status =
          typeof payload.approval_status === "string" ? payload.approval_status : null;
      });
      break;
    case "blocked":
      applySlot("current_blocker_ref", () => {
        current.current_blocker_ref =
          (typeof payload.blocker_ref === "string" ? payload.blocker_ref : event.object_ref) ??
          null;
      });
      applySlot("current_stage", () => {
        current.current_stage = "blocked";
      });
      if (current.current_blocker_ref?.startsWith("approval:")) {
        applySlot("current_approval_ref", () => {
          current.current_approval_ref = current.current_blocker_ref;
        });
      }
      break;
    case "unblocked":
      applySlot("current_blocker_ref", () => {
        current.current_blocker_ref = null;
      });
      applySlot("current_stage", () => {
        current.current_stage =
          typeof payload.resumed_stage === "string" ? payload.resumed_stage : "in_progress";
      });
      break;
    case "next_action_set":
      applySlot("next_action_json", () => {
        current.next_action_json = canonicalJson({
          assignee_ref:
            typeof payload.assignee_ref === "string" ? payload.assignee_ref : event.object_ref,
          action_text: typeof payload.action_text === "string" ? payload.action_text : null,
        });
      });
      break;
  }

  supporting.add(workflowEventId);
  current.last_event_id = workflowEventId;
  current.last_event_time = event.occurred_at;
  current.updated_at = Math.max(current.updated_at, event.created_at);
  current.slot_versions_json = canonicalJson(slotVersions);
  current.supporting_event_ids = canonicalJson([...supporting]);
  states.set(taskRef, current);
}

function upsertEntities(
  entities: Map<string, GraphEntityRow>,
  event: EventRecordV2,
  evidenceId: string,
): void {
  const refs = new Set<string>();
  if (event.subject_ref) refs.add(event.subject_ref);
  if (event.actor_ref) refs.add(event.actor_ref);
  if (event.object_ref) refs.add(event.object_ref);
  for (const ref of parseStringArray(event.related_refs_json)) {
    refs.add(ref);
  }
  for (const ref of refs) {
    const entityType = ref.startsWith("task:")
      ? "task"
      : ref.startsWith("approval:")
        ? "approval"
        : ref.startsWith("person:")
          ? "person"
          : ref.startsWith("person_name:")
            ? "person"
            : "blocker";
    const canonicalName = ref.includes(":") ? ref.split(":").slice(1).join(":") : ref;
    const current = entities.get(ref);
    entities.set(ref, {
      entity_ref: ref,
      entity_type: entityType,
      canonical_name: current?.canonical_name ?? canonicalName,
      alias_json: current?.alias_json ?? "[]",
      first_seen_at: current?.first_seen_at ?? event.occurred_at,
      last_seen_at: event.occurred_at,
      last_evidence_id: evidenceId,
      updated_at: Math.max(current?.updated_at ?? 0, event.created_at),
    });
  }
}

function upsertEdges(edges: Map<string, GraphEdgeRow>, event: EventRecordV2): void {
  if (!event.subject_ref.startsWith("task:")) {
    return;
  }
  const payload = JSON.parse(event.payload_json) as Record<string, unknown>;
  const close = (edgeType: string, validTo: string) => {
    for (const edge of edges.values()) {
      if (edge.src_ref === event.subject_ref && edge.edge_type === edgeType && edge.active === 1) {
        edge.active = 0;
        edge.valid_to = validTo;
        edge.updated_at = Math.max(edge.updated_at, event.created_at);
      }
    }
  };
  const open = (edgeType: GraphEdgeRow["edge_type"], dstRef: string | null) => {
    if (!dstRef) {
      return;
    }
    const edgeKey = buildEdgeKey({
      srcRef: event.subject_ref,
      edgeType: edgeType as
        | "assigned_to"
        | "has_approval"
        | "blocked_by"
        | "next_action_owner"
        | "related_to",
      dstRef,
    });
    const existing = edges.get(edgeKey);
    edges.set(edgeKey, {
      edge_id: existing?.edge_id ?? generateUlid(),
      edge_key: edgeKey,
      src_ref: event.subject_ref,
      edge_type: edgeType,
      dst_ref: dstRef,
      derived_from_event_id: event.event_id,
      active: 1,
      valid_from: event.occurred_at,
      valid_to: null,
      updated_at: Math.max(existing?.updated_at ?? 0, event.created_at),
    });
  };

  switch (event.event_type) {
    case "owner_changed":
      close("assigned_to", event.occurred_at);
      open("assigned_to", event.object_ref);
      break;
    case "approval_status_updated":
      open(
        "has_approval",
        typeof payload.approval_ref === "string" ? payload.approval_ref : event.object_ref,
      );
      break;
    case "blocked":
      close("blocked_by", event.occurred_at);
      open(
        "blocked_by",
        typeof payload.blocker_ref === "string" ? payload.blocker_ref : event.object_ref,
      );
      break;
    case "unblocked":
      close("blocked_by", event.occurred_at);
      break;
    case "next_action_set":
      close("next_action_owner", event.occurred_at);
      open(
        "next_action_owner",
        typeof payload.assignee_ref === "string" ? payload.assignee_ref : event.object_ref,
      );
      break;
  }
}

function loadLegacyEntityMeta(db: DatabaseSync): Map<string, LegacyEntityMeta> {
  const metas = new Map<string, LegacyEntityMeta>();
  if (hasTable(db, "canonical_entities")) {
    const rows = db
      .prepare("SELECT entity_id, canonical_name, entity_type FROM canonical_entities")
      .all() as Array<{
      entity_id: string;
      canonical_name: string | null;
      entity_type: string | null;
    }>;
    for (const row of rows) {
      metas.set(row.entity_id, {
        canonical_name: row.canonical_name,
        entity_type: row.entity_type,
        aliases: [],
      });
    }
  }
  if (hasTable(db, "entity_aliases")) {
    const rows = db
      .prepare("SELECT entity_id, alias FROM entity_aliases ORDER BY alias ASC")
      .all() as Array<{
      entity_id: string;
      alias: string;
    }>;
    for (const row of rows) {
      const current = metas.get(row.entity_id) ?? {
        canonical_name: null,
        entity_type: null,
        aliases: [],
      };
      current.aliases.push(row.alias);
      metas.set(row.entity_id, current);
    }
  }
  return metas;
}

export function runV5ToV6Migration(db: DatabaseSync): void {
  log.info("[canonical] migration.start from=v5 to=v6");
  db.exec("BEGIN IMMEDIATE");
  try {
    const insertEventType = db.prepare(
      `INSERT OR IGNORE INTO event_type_registry(
        event_type, subject_type, object_type, payload_schema_json, description, enabled, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)`,
    );
    for (const record of EVENT_TYPE_REGISTRY_SEED) {
      insertEventType.run(
        record.event_type,
        record.subject_type,
        record.object_type,
        record.payload_schema_json,
        record.description,
        record.enabled,
        record.created_at,
      );
    }

    const legacyMeta = loadLegacyEntityMeta(db);
    const hasLegacyEvents = hasTable(db, "event_records");
    const legacyEvents = hasLegacyEvents
      ? (db
          .prepare("SELECT * FROM event_records ORDER BY created_at ASC, event_id ASC")
          .all() as LegacyEventRow[])
      : [];

    const insertEvidence = db.prepare(
      `INSERT OR IGNORE INTO evidence_records(
        evidence_id, evidence_fingerprint, source_platform, source_kind, session_key, message_id,
        chat_id, chat_type, thread_id, root_id, parent_id, first_entry_id, last_entry_id,
        content_text, content_json, source_locator_json, occurred_at, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const selectEvidence = db.prepare(
      "SELECT evidence_id FROM evidence_records WHERE evidence_fingerprint = ?",
    );
    const insertEvent = db.prepare(
      `INSERT OR IGNORE INTO event_records_v2(
        event_id, event_fingerprint, evidence_id, event_type, subject_ref, actor_ref, object_ref,
        related_refs_json, occurred_at, payload_json, confidence, extraction_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const workflowStates = new Map<string, WorkflowRow>();
    const graphEntities = new Map<string, GraphEntityRow>();
    const graphEdges = new Map<string, GraphEdgeRow>();
    const migratedEvents: EventRecordV2[] = [];
    const skippedLegacyEvents: Array<{ event_id: string; reason: "unsupported" }> = [];

    for (const row of legacyEvents) {
      const meta = legacyMeta.get(row.entity_id);
      const eventType = inferEventType(row, meta);
      const subjectRef = inferSubjectRef(row, meta);
      if (!eventType || !subjectRef) {
        skippedLegacyEvents.push({ event_id: row.event_id, reason: "unsupported" });
        continue;
      }
      const actorRef = inferActorRef(row, meta);
      const objectRef = inferObjectRef(row, eventType);
      const payloadJson = payloadForLegacyEvent(row, eventType, actorRef, objectRef);
      const evidenceFingerprint = buildEvidenceFingerprint({
        sourcePlatform: "legacy",
        sourceKind: "legacy_event_record",
        sessionKey: row.session_id,
        occurredAt: row.occurred_at,
        contentText: legacySummary(row),
        contentJson: row,
      });
      let evidenceId =
        (selectEvidence.get(evidenceFingerprint) as { evidence_id?: string } | undefined)
          ?.evidence_id ?? null;
      if (!evidenceId) {
        evidenceId = generateUlid();
        insertEvidence.run(
          evidenceId,
          evidenceFingerprint,
          "legacy",
          "legacy_event_record",
          row.session_id,
          null,
          null,
          null,
          null,
          null,
          null,
          null,
          row.covered_until_entry_id,
          legacySummary(row),
          canonicalJson(row),
          canonicalJson({
            source_ref: row.source_ref,
            legacy_event_id: row.event_id,
            legacy_entity_id: row.entity_id,
          }),
          row.occurred_at,
          row.created_at,
        );
      }
      const eventFingerprint = buildEventFingerprint({
        evidenceId,
        eventType,
        subjectRef,
        objectRef,
        occurredAt: row.occurred_at,
        payloadJson,
      });
      const eventId = generateUlid();
      insertEvent.run(
        eventId,
        eventFingerprint,
        evidenceId,
        eventType,
        subjectRef,
        actorRef,
        objectRef,
        canonicalJson(
          [actorRef, objectRef].filter((value): value is string =>
            Boolean(value && value !== subjectRef),
          ),
        ),
        row.occurred_at,
        canonicalJson(payloadJson),
        row.confidence,
        row.extractor_version,
        row.created_at,
      );
      const existing = db
        .prepare("SELECT event_id FROM event_records_v2 WHERE event_fingerprint = ?")
        .get(eventFingerprint) as { event_id?: string } | undefined;
      const workflowEventId = existing?.event_id ?? eventId;
      const migratedEvent: EventRecordV2 = {
        event_id: workflowEventId,
        event_fingerprint: eventFingerprint,
        evidence_id: evidenceId,
        event_type: eventType,
        subject_ref: subjectRef,
        actor_ref: actorRef,
        object_ref: objectRef,
        related_refs_json: canonicalJson(
          [actorRef, objectRef].filter((value): value is string =>
            Boolean(value && value !== subjectRef),
          ),
        ),
        occurred_at: row.occurred_at,
        payload_json: canonicalJson(payloadJson),
        confidence: row.confidence,
        extraction_version: row.extractor_version,
        created_at: row.created_at,
      };
      migratedEvents.push(migratedEvent);
      upsertWorkflowState(workflowStates, migratedEvent, workflowEventId);
      upsertEntities(graphEntities, migratedEvent, evidenceId);
      upsertEdges(graphEdges, migratedEvent);
    }
    if (skippedLegacyEvents.length > 0) {
      log.warn(
        `[canonical] migration.skipped_legacy_events from=v5 to=v6 count=${skippedLegacyEvents.length} events=${canonicalJson(skippedLegacyEvents)}`,
      );
    }

    const insertWorkflow = db.prepare(
      `INSERT OR REPLACE INTO workflow_state_view_v2(
        task_ref, current_owner_ref, current_stage, current_approval_ref, approval_status,
        current_blocker_ref, next_action_json, last_event_id, last_event_time, slot_versions_json,
        supporting_event_ids, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    for (const row of workflowStates.values()) {
      insertWorkflow.run(
        row.task_ref,
        row.current_owner_ref,
        row.current_stage,
        row.current_approval_ref,
        row.approval_status,
        row.current_blocker_ref,
        row.next_action_json,
        row.last_event_id,
        row.last_event_time,
        row.slot_versions_json,
        row.supporting_event_ids,
        row.updated_at,
      );
    }

    const insertEntity = db.prepare(
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
    for (const row of graphEntities.values()) {
      insertEntity.run(
        row.entity_ref,
        row.entity_type,
        row.canonical_name,
        row.alias_json,
        row.first_seen_at,
        row.last_seen_at,
        row.last_evidence_id,
        row.updated_at,
      );
    }

    const insertEdge = db.prepare(
      `INSERT INTO graph_edges_v2(
        edge_id, edge_key, src_ref, edge_type, dst_ref, derived_from_event_id, active, valid_from,
        valid_to, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(edge_key) DO UPDATE SET
        src_ref = excluded.src_ref,
        edge_type = excluded.edge_type,
        dst_ref = excluded.dst_ref,
        derived_from_event_id = excluded.derived_from_event_id,
        active = excluded.active,
        valid_from = excluded.valid_from,
        valid_to = excluded.valid_to,
        updated_at = excluded.updated_at`,
    );
    for (const row of graphEdges.values()) {
      insertEdge.run(
        row.edge_id,
        row.edge_key,
        row.src_ref,
        row.edge_type,
        row.dst_ref,
        row.derived_from_event_id,
        row.active,
        row.valid_from,
        row.valid_to,
        row.updated_at,
      );
    }

    if (hasTable(db, "kg_backfill_state")) {
      db.exec("DROP TABLE IF EXISTS kg_backfill_state");
    }
    db.exec("DROP TABLE IF EXISTS workflow_state_view");
    db.exec("DROP TABLE IF EXISTS graph_edges");
    db.exec("DROP TABLE IF EXISTS canonical_entities");
    db.exec("DROP TABLE IF EXISTS entity_aliases");
    db.exec("DROP TABLE IF EXISTS event_fts");
    db.exec("DROP TABLE IF EXISTS entity_states");
    db.exec("DROP TABLE IF EXISTS event_records");
    db.exec("COMMIT");
    log.info(
      `[canonical] migration.done from=v5 to=v6 migrated_events=${migratedEvents.length} workflow=${workflowStates.size} entities=${graphEntities.size} edges=${graphEdges.size}`,
    );
  } catch (err) {
    db.exec("ROLLBACK");
    log.warn(`[canonical] migration.fallback from=v5 to=v6 error=${String(err)}`);
    throw err;
  }
}
