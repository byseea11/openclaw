import { canonicalJson, normalizeName, sha1, sha256 } from "./id-v2.js";

export const V2_EVENT_TYPES = [
  "conclusion_event",
  "rationale_event",
  "objection_event",
  "constraint_event",
  "commitment_event",
  "status_event",
  "time_event",
  "scope_event",
] as const;

export type V2EventType = (typeof V2_EVENT_TYPES)[number];

export type EvidenceRecordV2 = {
  evidence_id: string;
  evidence_fingerprint: string;
  source_platform: "transcript" | "feishu" | "legacy";
  source_kind:
    | "transcript_span"
    | "p2p_text"
    | "group_text"
    | "group_thread"
    | "interactive"
    | "legacy_event_record";
  session_key: string | null;
  message_id: string | null;
  chat_id: string | null;
  chat_type: string | null;
  thread_id: string | null;
  root_id: string | null;
  parent_id: string | null;
  first_entry_id: string | null;
  last_entry_id: string | null;
  content_text: string | null;
  content_json: string;
  source_locator_json: string;
  occurred_at: string | null;
  created_at: number;
  linked_event_ids_json?: string | null;
};

export type EventTypeRegistryRecord = {
  event_type: V2EventType;
  subject_type: string;
  object_type: string | null;
  payload_schema_json: string;
  description: string;
  enabled: number;
  created_at: number;
};

export type EventRecordV2 = {
  event_id: string;
  event_fingerprint: string;
  evidence_id: string;
  event_type: V2EventType;
  subject_ref: string;
  actor_ref: string | null;
  object_ref: string | null;
  related_refs_json: string;
  occurred_at: string;
  payload_json: string;
  confidence: number;
  extraction_version: string;
  created_at: number;
};

export type TaskCurrentStateViewV2 = {
  task_ref: string;
  primary_topic_ref: string | null;
  active_conclusion_event_id: string | null;
  active_rationale_event_ids_json: string;
  active_objection_event_ids_json: string;
  active_constraint_event_ids_json: string;
  active_commitment_event_ids_json: string;
  active_status_event_ids_json: string;
  active_scope_event_ids_json: string;
  active_stage_event_id: string | null;
  active_time_point_event_ids_json: string;
  slot_versions_json: string;
  last_event_id: string;
  updated_at: number;
};

export type GraphEntityV2 = {
  entity_ref: string;
  entity_type:
    | "task"
    | "person"
    | "topic"
    | "thread"
    | "doc"
    | "project"
    | "memory_block"
    | "session_event"
    | "session_wiki"
    | "evidence"
    | "date";
  canonical_name: string;
  alias_json: string;
  first_seen_at: string;
  last_seen_at: string;
  last_evidence_id: string | null;
  updated_at: number;
};

export type GraphEdgeV2 = {
  edge_id: string;
  edge_key: string;
  src_ref: string;
  edge_type:
    | "anchored_by_task"
    | "anchored_by_thread"
    | "anchored_by_doc"
    | "anchored_by_project"
    | "has_active_conclusion"
    | "has_active_rationale"
    | "has_active_objection"
    | "has_active_constraint"
    | "has_active_commitment"
    | "has_active_status"
    | "has_active_scope"
    | "has_active_stage"
    | "has_active_time_point"
    | "supported_by"
    | "related_time"
    | "supersedes";
  dst_ref: string;
  derived_from_event_id: string;
  active: number;
  valid_from: string;
  valid_to: string | null;
  updated_at: number;
};

export type QueryClassV2 = "task_state" | "task_why" | "task_timeline" | "list_relation" | "task_memory_card";

export const EVENT_TYPE_REGISTRY_SEED: EventTypeRegistryRecord[] = [
  {
    event_type: "conclusion_event",
    subject_type: "task",
    object_type: "topic",
    payload_schema_json: canonicalJson({
      claim: "string",
      target: "string?",
      conclusion: "string?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded task conclusion or current communication caliber.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "rationale_event",
    subject_type: "task",
    object_type: null,
    payload_schema_json: canonicalJson({
      claim: "string",
      reason: "string",
      reason_for: "string?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded rationale or basis for a task decision.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "objection_event",
    subject_type: "task",
    object_type: "topic",
    payload_schema_json: canonicalJson({
      claim: "string",
      objection: "string",
      objector: "string?",
      target: "string?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded objection, concern, or counter-position.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "constraint_event",
    subject_type: "task",
    object_type: "topic",
    payload_schema_json: canonicalJson({
      claim: "string",
      constraint: "string",
      target: "string?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded constraint, boundary, or do-not-commit rule.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "commitment_event",
    subject_type: "task",
    object_type: "person",
    payload_schema_json: canonicalJson({
      claim: "string",
      owner: "string",
      action: "string",
      deadline: "string?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded action commitment.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "status_event",
    subject_type: "task",
    object_type: null,
    payload_schema_json: canonicalJson({
      claim: "string",
      target: "string",
      status: "string",
      evidence_quote: "string",
    }),
    description: "A quote-grounded task or dependency status fact.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "time_event",
    subject_type: "task",
    object_type: null,
    payload_schema_json: canonicalJson({
      claim: "string",
      time_target: "string",
      time_value: "string",
      certainty: "string?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded date, deadline, or milestone fact.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "scope_event",
    subject_type: "task",
    object_type: null,
    payload_schema_json: canonicalJson({
      claim: "string",
      scope_target: "string",
      included: "array?",
      excluded: "array?",
      evidence_quote: "string",
    }),
    description: "A quote-grounded scope, rollout range, or stage boundary.",
    enabled: 1,
    created_at: 0,
  },
];

export function buildEvidenceFingerprint(params: {
  sourcePlatform: EvidenceRecordV2["source_platform"];
  sourceKind: EvidenceRecordV2["source_kind"];
  sessionKey?: string | null;
  messageId?: string | null;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
  parentId?: string | null;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
  occurredAt?: string | null;
  contentText?: string | null;
  contentJson?: unknown;
}): string {
  return sha256(
    [
      params.sourcePlatform,
      params.sourceKind,
      params.sessionKey ?? "",
      params.messageId ?? "",
      params.chatId ?? "",
      params.threadId ?? "",
      params.rootId ?? "",
      params.parentId ?? "",
      params.firstEntryId ?? "",
      params.lastEntryId ?? "",
      params.occurredAt ?? "",
      sha1((params.contentText ?? "").trim().toLowerCase()),
      sha1(canonicalJson(params.contentJson ?? {})),
    ].join("|"),
  );
}

export function buildEventFingerprint(params: {
  evidenceId: string;
  eventType: V2EventType;
  subjectRef: string;
  objectRef?: string | null;
  occurredAt: string;
  payloadJson: unknown;
}): string {
  return sha256(
    [
      params.evidenceId,
      params.eventType,
      params.subjectRef,
      params.objectRef ?? "",
      params.occurredAt,
      canonicalJson(params.payloadJson),
    ].join("|"),
  );
}

export function buildTaskSessionEventFingerprint(params: {
  taskRef: string;
  eventType: V2EventType;
  claimText: string;
  evidenceId: string;
}): string {
  return sha256(
    [
      params.taskRef,
      params.eventType,
      params.claimText,
      params.evidenceId,
    ].join("|"),
  );
}

export function buildEdgeKey(params: {
  srcRef: string;
  edgeType: GraphEdgeV2["edge_type"];
  dstRef: string;
}): string {
  return sha256([params.srcRef, params.edgeType, params.dstRef].join("|"));
}

export function normalizeTypedPersonRef(input: {
  openId?: string | null;
  name?: string | null;
}): string | null {
  const openId = input.openId?.trim();
  if (openId) {
    return `person:${openId}`;
  }
  const name = normalizeName(input.name ?? "");
  if (!name) {
    return null;
  }
  return `person_name:${sha1(name)}`;
}

export function normalizeBlockerRef(reason: string): string {
  return `blocker:${sha1(normalizeName(reason))}`;
}
