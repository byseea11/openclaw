import { buildEdgeKey } from "./schema-v2.js";
import type { EventRecordV2, GraphEdgeV2 } from "./schema-v2.js";

export type EdgeUpsertV2 = {
  edge_key: string;
  src_ref: string;
  edge_type: GraphEdgeV2["edge_type"];
  dst_ref: string;
  derived_from_event_id: string;
  active: 1;
  valid_from: string;
};

export type EdgeCloseV2 = {
  src_ref: string;
  edge_type: GraphEdgeV2["edge_type"];
  closed_at: string;
};

export type EdgeMutationBatchV2 = {
  closes: EdgeCloseV2[];
  upserts: EdgeUpsertV2[];
};

function asPayload(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function taskRef(event: EventRecordV2): string | null {
  if (event.subject_ref.startsWith("task:")) {
    return event.subject_ref;
  }
  if (typeof event.object_ref === "string" && event.object_ref.startsWith("task:")) {
    return event.object_ref;
  }
  return null;
}

function upsert(
  event: EventRecordV2,
  src_ref: string,
  edge_type: GraphEdgeV2["edge_type"],
  dst_ref: string,
): EdgeUpsertV2 {
  return {
    edge_key: buildEdgeKey({ srcRef: src_ref, edgeType: edge_type, dstRef: dst_ref }),
    src_ref,
    edge_type,
    dst_ref,
    derived_from_event_id: event.event_id,
    active: 1,
    valid_from: event.occurred_at,
  };
}

export function deriveGraphEdgeMutationsV2(events: EventRecordV2[]): EdgeMutationBatchV2 {
  const closes: EdgeCloseV2[] = [];
  const upserts: EdgeUpsertV2[] = [];

  for (const event of events) {
    const src = taskRef(event);
    const payload = asPayload(event.payload_json);
    if (!src) {
      continue;
    }
    switch (event.event_type) {
      case "owner_changed":
        closes.push({ src_ref: src, edge_type: "assigned_to", closed_at: event.occurred_at });
        if (typeof event.object_ref === "string") {
          upserts.push(upsert(event, src, "assigned_to", event.object_ref));
        }
        break;
      case "approval_status_updated": {
        const approvalRef =
          typeof payload.approval_ref === "string"
            ? payload.approval_ref
            : typeof event.object_ref === "string" && event.object_ref.startsWith("approval:")
              ? event.object_ref
              : null;
        if (approvalRef) {
          upserts.push(upsert(event, src, "has_approval", approvalRef));
        }
        break;
      }
      case "blocked": {
        const blockerRef =
          typeof payload.blocker_ref === "string" ? payload.blocker_ref : event.object_ref;
        closes.push({ src_ref: src, edge_type: "blocked_by", closed_at: event.occurred_at });
        if (blockerRef) {
          upserts.push(upsert(event, src, "blocked_by", blockerRef));
        }
        break;
      }
      case "unblocked":
        closes.push({ src_ref: src, edge_type: "blocked_by", closed_at: event.occurred_at });
        break;
      case "next_action_set": {
        closes.push({ src_ref: src, edge_type: "next_action_owner", closed_at: event.occurred_at });
        const assigneeRef =
          typeof payload.assignee_ref === "string"
            ? payload.assignee_ref
            : typeof event.object_ref === "string"
              ? event.object_ref
              : null;
        if (assigneeRef) {
          upserts.push(upsert(event, src, "next_action_owner", assigneeRef));
        }
        break;
      }
      default:
        break;
    }
  }

  return { closes, upserts };
}

export function reopenOrCreateEdgeV2(params: {
  existing: GraphEdgeV2 | null;
  upsert: EdgeUpsertV2;
}): GraphEdgeV2 {
  return {
    edge_id: params.existing?.edge_id ?? "",
    edge_key: params.upsert.edge_key,
    src_ref: params.upsert.src_ref,
    edge_type: params.upsert.edge_type,
    dst_ref: params.upsert.dst_ref,
    derived_from_event_id: params.upsert.derived_from_event_id,
    active: 1,
    valid_from: params.upsert.valid_from,
    valid_to: null,
    updated_at: Date.now(),
  };
}
