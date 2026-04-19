import { createHash } from "node:crypto";
import { isStrongGraphRelation, isWeakGraphRelation } from "./kg.js";
import {
  type CanonicalEntityType,
  type EventRecord,
  type GraphObjectSet,
  type GraphRelation,
  type WorkflowAdmission,
  type WorkflowObjectType,
  type WorkflowSourceKind,
  type WorkflowStateView,
  type WorkflowUpdate,
} from "./schema.js";

const BLOCKER_RE = /(block|blocked|blocking|depends|dependency|waiting|stuck|卡|阻塞|等待)/i;
const RESOLVED_RE = /(done|resolved|unblocked|closed|complete|completed|解除|解决|完成)/i;
const APPROVED_RE = /(approved|accepted|approval|批准|通过)/i;
const REJECTED_RE = /(rejected|declined|denied|驳回|拒绝)/i;
const PENDING_RE = /(pending|waiting|needs_review|review|审批|待定|等待)/i;
const NEXT_ACTION_RE = /(next_action|action_item|follow_up|todo|下一步|待办)/i;

export type WorkflowBackfillMode = "graph_only" | "graph_and_workflow";

export function isWorkflowStateLayerEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  const value = env.OPENCLAW_WORKFLOW_STATE_LAYER?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

export function isWorkflowStateReadEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  const value = env.OPENCLAW_WORKFLOW_STATE_READ?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

export function workflowSourcePriority(sourceKind: WorkflowSourceKind): number {
  switch (sourceKind) {
    case "tool_result":
      return 50;
    case "transcript":
      return 40;
    case "doc_parse":
      return 30;
    case "flush":
      return 20;
    case "backfill":
      return 10;
    default:
      return 0;
  }
}

export function workflowAdmissionPriority(admission: WorkflowAdmission): number {
  switch (admission) {
    case "current_state_patch":
      return 30;
    case "evidence_only":
      return 20;
    case "reject":
      return 10;
    default:
      return 0;
  }
}

function hash(input: string, length = 24): string {
  return createHash("sha256").update(input).digest("hex").slice(0, length);
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .toSorted(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function workflowUpdateId(update: WorkflowUpdate): string {
  return `wf_${hash(
    stableStringify({
      object_type: update.object_type,
      object_id: update.object_id,
      occurred_at: update.occurred_at,
      source: update.source,
      patch: update.patch,
      event_id: update.evidence.event_id,
    }),
  )}`;
}

function textForEvent(record: EventRecord): string {
  return `${record.action} ${record.object ?? ""} ${record.status_before ?? ""} ${record.status_after ?? ""}`;
}

function sourceKindForEvent(
  record: EventRecord,
  override?: WorkflowSourceKind,
): WorkflowSourceKind {
  if (override) {
    return override;
  }
  switch (record.source_type) {
    case "transcript":
    case "tool_result":
    case "flush":
      return record.source_type;
    case "memory_file":
    case "promotion":
      return "doc_parse";
    default:
      return "doc_parse";
  }
}

function workflowTypeForEntity(
  canonicalEntityType: CanonicalEntityType | null,
  record: EventRecord,
): Pick<WorkflowUpdate["derived"], "workflow_type_source"> & {
  objectType: WorkflowObjectType | null;
} {
  const text = textForEvent(record);
  switch (canonicalEntityType) {
    case "task":
    case "project":
    case "meeting":
    case "document":
      return { objectType: canonicalEntityType, workflow_type_source: "canonical_type" };
    case "decision":
      if (APPROVED_RE.test(text) || REJECTED_RE.test(text) || PENDING_RE.test(text)) {
        return { objectType: "approval", workflow_type_source: "explicit_semantics" };
      }
      return { objectType: null, workflow_type_source: "canonical_type" };
    case "other":
      if (/\b(artifact|build|release|report|file)\b|产物|制品/i.test(text)) {
        return { objectType: "artifact", workflow_type_source: "explicit_semantics" };
      }
      return { objectType: null, workflow_type_source: "canonical_type" };
    case "person":
    case "team":
    case "customer":
      return { objectType: null, workflow_type_source: "canonical_type" };
    default:
      return { objectType: null, workflow_type_source: "canonical_type" };
  }
}

function relationStrengthForEdges(
  relations: GraphRelation[],
): WorkflowUpdate["evidence"]["relation_strength"] {
  if (relations.some((relation) => isStrongGraphRelation(relation))) {
    return "strong";
  }
  if (relations.some((relation) => isWeakGraphRelation(relation))) {
    return "weak";
  }
  return "none";
}

function approvalStatusFor(record: EventRecord): WorkflowStateView["approval_status"] | null {
  const text = textForEvent(record);
  if (APPROVED_RE.test(text)) {
    return "approved";
  }
  if (REJECTED_RE.test(text)) {
    return "rejected";
  }
  if (PENDING_RE.test(text)) {
    return text.includes("review") || text.includes("needs_review") ? "needs_review" : "pending";
  }
  return null;
}

function ownerEntityIdFor(record: EventRecord, graphObjects: GraphObjectSet): string | null {
  const ownerEdge = graphObjects.edges.find(
    (edge) =>
      edge.evidence_event_id === record.event_id &&
      (edge.relation === "owned_by" || edge.relation === "assigned_to") &&
      edge.src_entity_id === record.entity_id,
  );
  return ownerEdge?.dst_entity_id ?? null;
}

function patchForRecord(
  record: EventRecord,
  graphObjects: GraphObjectSet,
): WorkflowUpdate["patch"] | null {
  const set: NonNullable<WorkflowUpdate["patch"]["set"]> = {};
  const append: NonNullable<WorkflowUpdate["patch"]["append"]> = {
    supporting_event_ids: [record.event_id],
  };
  const text = textForEvent(record);
  const ownerEntityId = ownerEntityIdFor(record, graphObjects);
  if (ownerEntityId) {
    set.owner_entity_id = ownerEntityId;
  }
  if (record.status_after) {
    set.stage = record.status_after;
  }
  if (BLOCKER_RE.test(text) || record.status_after === "blocked") {
    set.blocker_status = "blocked";
    set.blocker_reason = record.object ?? record.action;
  }
  if (RESOLVED_RE.test(text)) {
    set.blocker_status = "resolved";
  }
  const approvalStatus = approvalStatusFor(record);
  if (approvalStatus) {
    set.approval_status = approvalStatus;
  }
  if (NEXT_ACTION_RE.test(text)) {
    set.next_action = record.object ?? record.action;
  }
  if (Object.keys(set).length === 0) {
    return { append };
  }
  return { set, append };
}

export function deriveWorkflowUpdates(
  records: EventRecord[],
  graphObjects: GraphObjectSet,
  options: { sourceKind?: WorkflowSourceKind } = {},
): WorkflowUpdate[] {
  const entitiesById = new Map(graphObjects.entities.map((entity) => [entity.entity_id, entity]));
  return records.flatMap((record) => {
    const canonicalEntityType =
      record.object_type ?? entitiesById.get(record.entity_id)?.entity_type ?? null;
    const workflowType = workflowTypeForEntity(canonicalEntityType, record);
    if (!workflowType.objectType) {
      return [];
    }
    const patch = patchForRecord(record, graphObjects);
    if (!patch) {
      return [];
    }
    const eventEdges = graphObjects.edges.filter(
      (edge) => edge.evidence_event_id === record.event_id,
    );
    const update: WorkflowUpdate = {
      object_type: workflowType.objectType,
      object_id: record.entity_id,
      occurred_at: record.occurred_at,
      source: {
        source_kind: sourceKindForEvent(record, options.sourceKind),
        source_ref: record.source_ref,
        session_id: record.session_id,
      },
      patch,
      evidence: {
        event_id: record.event_id,
        supporting_event_ids: [record.event_id],
        edge_ids: eventEdges.map((edge) => edge.edge_id),
        confidence: record.confidence,
        relation_strength: relationStrengthForEdges(eventEdges.map((edge) => edge.relation)),
        resolution_status: "stable",
      },
      derived: {
        canonical_entity_id: record.entity_id,
        canonical_entity_type: canonicalEntityType ?? "other",
        workflow_type_source: workflowType.workflow_type_source,
      },
    };
    return [{ ...update, update_id: workflowUpdateId(update) }];
  });
}

export function preliminaryWorkflowAdmission(update: WorkflowUpdate): WorkflowAdmission {
  if (update.evidence.resolution_status !== "stable") {
    return "reject";
  }
  if (update.evidence.relation_strength === "weak") {
    return "evidence_only";
  }
  if (update.source.source_kind === "backfill") {
    return "evidence_only";
  }
  if (update.source.source_kind === "flush" || update.source.source_kind === "doc_parse") {
    return update.evidence.confidence >= 0.8 ? "current_state_patch" : "evidence_only";
  }
  return update.evidence.confidence >= 0.7 ? "current_state_patch" : "evidence_only";
}

export function sortWorkflowUpdatesDeterministically(updates: WorkflowUpdate[]): WorkflowUpdate[] {
  return updates.toSorted((left, right) => {
    const admissionDelta =
      workflowAdmissionPriority(preliminaryWorkflowAdmission(right)) -
      workflowAdmissionPriority(preliminaryWorkflowAdmission(left));
    return (
      left.object_type.localeCompare(right.object_type) ||
      left.object_id.localeCompare(right.object_id) ||
      left.occurred_at.localeCompare(right.occurred_at) ||
      workflowSourcePriority(right.source.source_kind) -
        workflowSourcePriority(left.source.source_kind) ||
      admissionDelta ||
      left.evidence.event_id.localeCompare(right.evidence.event_id) ||
      (left.update_id ?? workflowUpdateId(left)).localeCompare(
        right.update_id ?? workflowUpdateId(right),
      )
    );
  });
}

export function workflowBatchTypeConflictObjectIds(updates: WorkflowUpdate[]): Set<string> {
  const typesByObjectId = new Map<string, Set<WorkflowObjectType>>();
  for (const update of updates) {
    const existing = typesByObjectId.get(update.object_id) ?? new Set<WorkflowObjectType>();
    existing.add(update.object_type);
    typesByObjectId.set(update.object_id, existing);
  }
  return new Set(
    [...typesByObjectId.entries()]
      .filter(([, types]) => types.size > 1)
      .map(([objectId]) => objectId),
  );
}
