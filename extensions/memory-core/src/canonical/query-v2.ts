import type { GraphHit } from "./schema.js";
import type { CanonicalStore } from "./store.js";

type QueryClass = "state" | "why" | "timeline" | "list_relation";

function asRecord(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function sourceRefFromEvidence(sourceLocatorJson: string): string {
  const locator = asRecord(sourceLocatorJson);
  return typeof locator.source_ref === "string"
    ? locator.source_ref
    : "transcripts/unknown.txt#L1-L1";
}

function eventLabel(eventType: string): string {
  switch (eventType) {
    case "owner_changed":
      return "owner changed";
    case "stage_changed":
      return "stage changed";
    case "approval_status_updated":
      return "approval updated";
    case "blocked":
      return "blocked";
    case "unblocked":
      return "unblocked";
    case "next_action_set":
      return "next action set";
    default:
      return eventType;
  }
}

export function classifyQueryV2(query: string): QueryClass {
  const normalized = query.toLowerCase();
  if (/(why|为什么|原因|卡在哪|blocked|blocker|dependency)/i.test(normalized)) {
    return "why";
  }
  if (/(timeline|历史|演进|什么时候|何时|changed)/i.test(normalized)) {
    return "timeline";
  }
  if (/(哪些|列出|all|关系|依赖|related)/i.test(normalized)) {
    return "list_relation";
  }
  return "state";
}

export function resolveEntityRefV2(
  store: CanonicalStore,
  query: string,
): { entity_ref: string; entity_type: string; confidence: number; matched_name: string } | null {
  const taskMatch = query.match(/\b([A-Z][A-Z0-9]+-\d+)\b/);
  if (taskMatch) {
    return {
      entity_ref: `task:${taskMatch[1]}`,
      entity_type: "task",
      confidence: 0.99,
      matched_name: taskMatch[1],
    };
  }
  const approvalMatch = query.match(/\b(AP-\d+)\b/i);
  if (approvalMatch) {
    return {
      entity_ref: `approval:${approvalMatch[1].toUpperCase()}`,
      entity_type: "approval",
      confidence: 0.99,
      matched_name: approvalMatch[1].toUpperCase(),
    };
  }
  const candidates = store.findEntityMatchesV2(query, 10);
  const rank = (entityType: string): number =>
    entityType === "task" ? 0 : entityType === "approval" ? 1 : entityType === "person" ? 2 : 3;
  const best = [...candidates].toSorted((left, right) => {
    const rankDelta = rank(left.entity_type) - rank(right.entity_type);
    if (rankDelta !== 0) {
      return rankDelta;
    }
    return right.last_seen_at.localeCompare(left.last_seen_at);
  })[0];
  return best
    ? {
        entity_ref: best.entity_ref,
        entity_type: best.entity_type,
        confidence: 0.7,
        matched_name: best.canonical_name,
      }
    : null;
}

function buildStateHit(store: CanonicalStore, taskRef: string): GraphHit[] {
  const state = store.getWorkflowStateV2(taskRef);
  if (!state) {
    return [];
  }
  const event = store.getEventByIdV2(state.last_event_id);
  const evidence = event ? store.getEvidenceByIdV2(event.evidence_id) : null;
  return [
    {
      type: "state",
      entity_id: taskRef,
      source_ref: evidence
        ? sourceRefFromEvidence(evidence.source_locator_json)
        : "transcripts/unknown.txt#L1-L1",
      score: 1,
      snippet_structured: {
        query_kind: "state",
        task_ref: state.task_ref,
        current_owner_ref: state.current_owner_ref,
        current_stage: state.current_stage,
        current_approval_ref: state.current_approval_ref,
        approval_status: state.approval_status,
        current_blocker_ref: state.current_blocker_ref,
        next_action_json: state.next_action_json,
        last_event_id: state.last_event_id,
        last_event_time: state.last_event_time,
        latest_status: state.current_stage,
        latest_owner: state.current_owner_ref,
        last_updated_at: state.updated_at,
      },
    },
  ];
}

function buildWhyHits(store: CanonicalStore, taskRef: string, limit: number): GraphHit[] {
  const state = store.getWorkflowStateV2(taskRef);
  if (!state) {
    return [];
  }
  const slotVersions = asRecord(state.slot_versions_json);
  const eventIds = new Set<string>();
  for (const slot of [
    "current_blocker_ref",
    "approval_status",
    "current_stage",
    "next_action_json",
  ]) {
    const version = slotVersions[slot];
    if (version && typeof version === "object" && !Array.isArray(version)) {
      const eventId = (version as Record<string, unknown>).event_id;
      if (typeof eventId === "string") {
        eventIds.add(eventId);
      }
    }
  }
  const hits: GraphHit[] = [];
  for (const event of store.getEventsByIdsV2([...eventIds]).slice(0, limit)) {
    const evidence = store.getEvidenceByIdV2(event.evidence_id);
    hits.push({
      type: "event",
      entity_id: taskRef,
      source_ref: evidence
        ? sourceRefFromEvidence(evidence.source_locator_json)
        : "transcripts/unknown.txt#L1-L1",
      score: 0.95,
      snippet_structured: {
        query_kind: "why",
        occurred_at: event.occurred_at,
        actor: event.actor_ref,
        action: eventLabel(event.event_type),
        object: event.object_ref,
        event_type: event.event_type,
        payload_json: event.payload_json,
        evidence_excerpt: evidence?.content_text ?? null,
      },
    });
  }
  return hits;
}

function buildTimelineHits(store: CanonicalStore, entityRef: string, limit: number): GraphHit[] {
  return store.listEventsForRefV2(entityRef, limit).map((event, index) => {
    const evidence = store.getEvidenceByIdV2(event.evidence_id);
    return {
      type: "event",
      entity_id: entityRef,
      source_ref: evidence
        ? sourceRefFromEvidence(evidence.source_locator_json)
        : "transcripts/unknown.txt#L1-L1",
      score: Math.max(0.4, 1 - index * 0.05),
      snippet_structured: {
        query_kind: "timeline",
        occurred_at: event.occurred_at,
        actor: event.actor_ref,
        action: eventLabel(event.event_type),
        object: event.object_ref,
        event_type: event.event_type,
        payload_json: event.payload_json,
      },
    };
  });
}

function buildListRelationHits(
  store: CanonicalStore,
  query: string,
  resolvedRef: string | null,
  limit: number,
): GraphHit[] {
  const lower = query.toLowerCase();
  if (lower.includes("blocked")) {
    return store
      .listWorkflowStatesV2({ stage: "blocked" })
      .slice(0, limit)
      .map((state, index) => ({
        type: "state",
        entity_id: state.task_ref,
        source_ref: "transcripts/unknown.txt#L1-L1",
        score: Math.max(0.4, 1 - index * 0.03),
        snippet_structured: {
          query_kind: "list_relation",
          latest_status: state.current_stage,
          latest_owner: state.current_owner_ref,
          last_updated_at: state.updated_at,
          current_blocker_ref: state.current_blocker_ref,
        },
      }));
  }
  if (resolvedRef) {
    return store
      .listActiveEdgesForRefV2(resolvedRef)
      .slice(0, limit)
      .map((edge, index) => ({
        type: "edge",
        entity_id: edge.src_ref,
        source_ref: "transcripts/unknown.txt#L1-L1",
        score: Math.max(0.4, 1 - index * 0.03),
        snippet_structured: {
          query_kind: "list_relation",
          relation: edge.edge_type,
          src_name: edge.src_ref,
          dst_name: edge.dst_ref,
          dst_entity_id: edge.dst_ref,
          occurred_at: edge.valid_from,
          graph_freshness: edge.active ? "active" : "inactive",
        },
      }));
  }
  return [];
}

export async function searchGraphV2(
  store: CanonicalStore,
  query: string,
  maxResults: number,
): Promise<{ hits: GraphHit[]; queryClass: QueryClass; resolvedRef: string | null }> {
  const queryClass = classifyQueryV2(query);
  const resolved = resolveEntityRefV2(store, query);
  const resolvedRef = resolved?.entity_ref ?? null;
  const limit = Math.max(1, maxResults);
  if (queryClass === "state" && resolvedRef?.startsWith("task:")) {
    return { hits: buildStateHit(store, resolvedRef).slice(0, limit), queryClass, resolvedRef };
  }
  if (queryClass === "why" && resolvedRef?.startsWith("task:")) {
    return { hits: buildWhyHits(store, resolvedRef, limit), queryClass, resolvedRef };
  }
  if (queryClass === "timeline" && resolvedRef) {
    return { hits: buildTimelineHits(store, resolvedRef, limit), queryClass, resolvedRef };
  }
  return {
    hits: buildListRelationHits(store, query, resolvedRef, limit),
    queryClass,
    resolvedRef,
  };
}
