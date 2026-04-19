import { createHash } from "node:crypto";
import {
  type CanonicalEntity,
  type CanonicalEntityType,
  type EntityAlias,
  type EventRecord,
  type GraphEdge,
  type GraphObjectSet,
  type GraphRelation,
  STRONG_GRAPH_RELATIONS,
  WEAK_GRAPH_RELATIONS,
} from "./schema.js";

const TICKET_KEY_RE = /\b[A-Z][A-Z0-9]+-\d+\b/;
const DOC_KEY_RE = /\b(?:doc|document|docs?)[:#\s-]+([A-Za-z0-9_.-]+)\b/i;
const MEETING_KEY_RE = /\b(?:meeting|会议)[:#\s-]+([A-Za-z0-9_.-]+)\b/i;
const PERSON_NAME_RE = /^@?[A-Z][A-Za-z0-9_.-]{1,40}(?:\s+[A-Z][A-Za-z0-9_.-]{1,40})?$/;
const WEAK_ACTION_RE =
  /(mention|refer|about|related|note|fact|preference|relationship|life|location|health|work_or_school)/i;
const OWNER_ACTION_RE = /(owner|assigned|assignee|responsible|跟进|负责人|接手)/i;
const BLOCKER_ACTION_RE = /(block|blocked|blocking|depends|dependency|卡|审批|waiting)/i;
const DECISION_ACTION_RE = /(decid|decision|approved|rejected|决定|审批通过|批准)/i;
const SCHEDULE_ACTION_RE = /(deadline|due|scheduled|meeting|calendar|安排|截止|预计)/i;
const PARTICIPATION_ACTION_RE = /(participat|attend|joined|meeting|参加)/i;
const TENTATIVE_RE = /\b(maybe|might|possibly|probably|tentative|could|可能|也许|预计)\b/i;
const NEGATED_RE = /\b(not|isn't|wasn't|不是|没有|并非)\b/i;

export type GraphRelationStrength = "strong" | "weak";

export function isStrongGraphRelation(relation: GraphRelation): boolean {
  return (STRONG_GRAPH_RELATIONS as readonly string[]).includes(relation);
}

export function isWeakGraphRelation(relation: GraphRelation): boolean {
  return (WEAK_GRAPH_RELATIONS as readonly string[]).includes(relation);
}

function hash(input: string, length = 16): string {
  return createHash("sha256").update(input).digest("hex").slice(0, length);
}

function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function normalizeEntityAlias(value: string): string {
  return normalizeWhitespace(value)
    .replace(/^@/, "")
    .replace(/[“”"']/g, "")
    .replace(/[，,。.;；:：()[\]{}]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function normalizeTicketKey(value: string): string | null {
  const match = value.match(TICKET_KEY_RE);
  return match?.[0]?.toUpperCase() ?? null;
}

function inferEntityType(
  name: string,
  objectType?: CanonicalEntityType | null,
): CanonicalEntityType {
  if (objectType && objectType !== "other") {
    return objectType;
  }
  if (normalizeTicketKey(name)) {
    return "task";
  }
  if (DOC_KEY_RE.test(name)) {
    return "document";
  }
  if (MEETING_KEY_RE.test(name) || /\bmeeting\b|会议/i.test(name)) {
    return "meeting";
  }
  if (PERSON_NAME_RE.test(name)) {
    return "person";
  }
  if (/\b(project|项目)\b/i.test(name)) {
    return "project";
  }
  if (/\b(customer|客户)\b/i.test(name)) {
    return "customer";
  }
  if (/\b(decision|决定|决策)\b/i.test(name)) {
    return "decision";
  }
  return "other";
}

function entityForName(params: {
  name: string;
  type?: CanonicalEntityType | null;
  fallbackId?: string;
  record: EventRecord;
  nowMs: number;
}): CanonicalEntity {
  const normalized = normalizeEntityAlias(params.name);
  const ticketKey = normalizeTicketKey(params.name);
  const type = inferEntityType(params.name, params.type ?? null);
  const entityId =
    params.fallbackId ??
    (ticketKey
      ? `ent_${hash(`${type}:key:${ticketKey}`)}`
      : normalized
        ? `ent_${hash(`${type}:name:${normalized}`)}`
        : `ent_${hash(`opaque:${params.record.session_id ?? ""}:${params.record.source_ref}`)}`);
  return {
    entity_id: entityId,
    entity_type: type,
    canonical_name: ticketKey ?? normalizeWhitespace(params.name),
    status: params.record.status_after,
    last_seen_at: params.record.occurred_at,
    confidence: params.record.confidence,
    created_at: params.nowMs,
    updated_at: params.nowMs,
    provenance_json: JSON.stringify([
      {
        event_id: params.record.event_id,
        source_ref: params.record.source_ref,
        session_id: params.record.session_id,
      },
    ]),
  };
}

function aliasRows(params: {
  entity: CanonicalEntity;
  aliases: string[];
  record: EventRecord;
  nowMs: number;
}): EntityAlias[] {
  const rows: EntityAlias[] = [];
  const seen = new Set<string>();
  for (const rawAlias of params.aliases) {
    const normalized = normalizeEntityAlias(rawAlias);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    rows.push({
      alias: normalized,
      entity_id: params.entity.entity_id,
      alias_type: normalized === rawAlias.trim().toLowerCase() ? "exact" : "normalized",
      confidence: params.record.confidence,
      source_ref: params.record.source_ref,
      session_id: params.record.session_id,
      created_at: params.nowMs,
    });
  }
  return rows;
}

function edgeId(edge: Omit<GraphEdge, "edge_id">): string {
  return `edge_${hash(
    `${edge.src_entity_id}\n${edge.relation}\n${edge.dst_entity_id}\n${edge.evidence_event_id}`,
    32,
  )}`;
}

function makeEdge(params: {
  src: CanonicalEntity;
  relation: GraphRelation;
  dst: CanonicalEntity;
  record: EventRecord;
  nowMs: number;
  confidence?: number;
}): GraphEdge {
  const edge = {
    src_entity_id: params.src.entity_id,
    relation: params.relation,
    dst_entity_id: params.dst.entity_id,
    occurred_at: params.record.occurred_at,
    source_ref: params.record.source_ref,
    session_id: params.record.session_id,
    evidence_event_id: params.record.event_id,
    confidence: Math.min(params.record.confidence, params.confidence ?? params.record.confidence),
    created_at: params.nowMs,
  };
  return { edge_id: edgeId(edge), ...edge };
}

function relationForEvent(record: EventRecord): GraphRelation {
  const text = `${record.action} ${record.object ?? ""} ${record.status_after ?? ""}`;
  if (NEGATED_RE.test(text)) {
    return "mentions";
  }
  if (OWNER_ACTION_RE.test(text)) {
    return "owned_by";
  }
  if (DECISION_ACTION_RE.test(text)) {
    return "decided_by";
  }
  if (SCHEDULE_ACTION_RE.test(text) && !TENTATIVE_RE.test(text)) {
    return "scheduled_for";
  }
  if (record.status_after === "blocked" || BLOCKER_ACTION_RE.test(text)) {
    return "blocks";
  }
  if (TENTATIVE_RE.test(text)) {
    return "about";
  }
  if (PARTICIPATION_ACTION_RE.test(text)) {
    return "participated_in";
  }
  if (WEAK_ACTION_RE.test(text)) {
    return "about";
  }
  return "related_to";
}

function inferActorEntity(record: EventRecord, nowMs: number): CanonicalEntity | null {
  const actor = record.actor?.trim();
  if (!actor || actor.toLowerCase() === "user" || actor.toLowerCase() === "assistant") {
    return null;
  }
  return entityForName({ name: actor, type: "person", record, nowMs });
}

function entityKey(entity: CanonicalEntity): string {
  return entity.entity_id;
}

function aliasKey(alias: EntityAlias): string {
  return `${alias.alias}\0${alias.entity_id}\0${alias.alias_type}`;
}

export function deriveGraphObjects(records: EventRecord[], nowMs = Date.now()): GraphObjectSet {
  const entities = new Map<string, CanonicalEntity>();
  const aliases = new Map<string, EntityAlias>();
  const edges = new Map<string, GraphEdge>();
  for (const record of records) {
    const objectName = record.object?.trim() || `${record.action}:${record.source_ref}`;
    const mainEntity = entityForName({
      name: objectName,
      type: record.object_type,
      fallbackId: record.entity_id,
      record,
      nowMs,
    });
    entities.set(entityKey(mainEntity), mainEntity);
    for (const alias of aliasRows({
      entity: mainEntity,
      aliases: [objectName, normalizeTicketKey(objectName) ?? ""],
      record,
      nowMs,
    })) {
      aliases.set(aliasKey(alias), alias);
    }
    const actorEntity = inferActorEntity(record, nowMs);
    if (actorEntity) {
      entities.set(entityKey(actorEntity), actorEntity);
      for (const alias of aliasRows({
        entity: actorEntity,
        aliases: [record.actor ?? ""],
        record,
        nowMs,
      })) {
        aliases.set(aliasKey(alias), alias);
      }
    }
    const relation = relationForEvent(record);
    if (actorEntity) {
      const src = ["owned_by", "assigned_to", "decided_by", "participated_in"].includes(relation)
        ? mainEntity
        : actorEntity;
      const dst = src === mainEntity ? actorEntity : mainEntity;
      const edge = makeEdge({
        src,
        relation,
        dst,
        record,
        nowMs,
        confidence: isStrongGraphRelation(relation) ? record.confidence : record.confidence * 0.7,
      });
      edges.set(edge.edge_id, edge);
    } else if (relation === "blocks" || relation === "scheduled_for" || relation === "about") {
      const edge = makeEdge({
        src: mainEntity,
        relation,
        dst: mainEntity,
        record,
        nowMs,
        confidence: isWeakGraphRelation(relation) ? record.confidence * 0.7 : record.confidence,
      });
      edges.set(edge.edge_id, edge);
    }
  }
  return {
    entities: [...entities.values()],
    aliases: [...aliases.values()],
    edges: [...edges.values()],
  };
}
