import { canonicalJson, normalizeName, sha1, sha256 } from "./id-v2.js";

export const V2_EVENT_TYPES = [
  "owner_changed",
  "stage_changed",
  "approval_status_updated",
  "blocked",
  "unblocked",
  "next_action_set",
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
};

export type EventTypeRegistryRecord = {
  event_type: V2EventType;
  subject_type: "task" | "approval";
  object_type: "person" | "approval" | "blocker" | "task" | null;
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

export type WorkflowStateViewV2 = {
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

export type GraphEntityV2 = {
  entity_ref: string;
  entity_type: "task" | "approval" | "person" | "blocker";
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
  edge_type: "assigned_to" | "has_approval" | "blocked_by" | "next_action_owner" | "related_to";
  dst_ref: string;
  derived_from_event_id: string;
  active: number;
  valid_from: string;
  valid_to: string | null;
  updated_at: number;
};

export type QueryClassV2 = "state" | "why" | "timeline" | "list_relation";

export const EVENT_TYPE_REGISTRY_SEED: EventTypeRegistryRecord[] = [
  {
    event_type: "owner_changed",
    subject_type: "task",
    object_type: "person",
    payload_schema_json: canonicalJson({
      old_owner_ref: "string?",
      new_owner_ref: "string",
      reason: "string?",
    }),
    description: "Task ownership changed.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "stage_changed",
    subject_type: "task",
    object_type: null,
    payload_schema_json: canonicalJson({
      old_stage: "string?",
      new_stage: "string",
      reason: "string?",
    }),
    description: "Task stage changed.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "approval_status_updated",
    subject_type: "task",
    object_type: "approval",
    payload_schema_json: canonicalJson({
      approval_ref: "string",
      approval_status: "string",
      reason: "string?",
    }),
    description: "Approval status updated for a task.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "blocked",
    subject_type: "task",
    object_type: "blocker",
    payload_schema_json: canonicalJson({
      blocker_ref: "string",
      blocker_reason: "string?",
    }),
    description: "Task became blocked.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "unblocked",
    subject_type: "task",
    object_type: "blocker",
    payload_schema_json: canonicalJson({
      blocker_ref: "string?",
      blocker_reason: "string?",
      resumed_stage: "string?",
    }),
    description: "Task is no longer blocked.",
    enabled: 1,
    created_at: 0,
  },
  {
    event_type: "next_action_set",
    subject_type: "task",
    object_type: "person",
    payload_schema_json: canonicalJson({
      assignee_ref: "string?",
      action_text: "string",
      due_at: "string?",
    }),
    description: "Next action was assigned or updated.",
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
