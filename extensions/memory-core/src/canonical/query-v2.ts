import type { EventRecordV2, QueryClassV2, TaskCurrentStateViewV2 } from "./schema-v2.js";
import type { GraphHit } from "./schema.js";
import type { FeishuTaskWikiStore } from "./store.js";

const TASK_MEMORY_CARD_RE =
  /(之前怎么定的|为什么这样定|反对意见|这个结论后来改过吗|为什么.*确认日期|现在到底按哪个口径|之前为什么选|历史决策|结论|口径|方案|task memory)/i;

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

function stringArrayFromJson(value: string): string[] {
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string")
      : [];
  } catch {
    return [];
  }
}

function sourceRefFromEvidence(sourceLocatorJson: string): string {
  const locator = asRecord(sourceLocatorJson);
  return typeof locator.source_ref === "string"
    ? locator.source_ref
    : "transcripts/unknown.txt#L1-L1";
}

function payloadForEvent(event: EventRecordV2): Record<string, unknown> {
  return asRecord(event.payload_json);
}

function taskRefFromEvent(event: EventRecordV2): string {
  return event.subject_ref.startsWith("task:") ? event.subject_ref : event.subject_ref;
}

function eventLabel(eventType: EventRecordV2["event_type"]): string {
  switch (eventType) {
    case "conclusion_event":
      return "task conclusion";
    case "rationale_event":
      return "task rationale";
    case "objection_event":
      return "task objection";
    case "constraint_event":
      return "task constraint";
    case "commitment_event":
      return "task commitment";
    case "status_event":
      return "task status";
    case "time_event":
      return "task time point";
    case "scope_event":
      return "task scope";
    default:
      return eventType;
  }
}

function claimTextFromEvent(event: EventRecordV2 | null): string | null {
  if (!event) {
    return null;
  }
  const payload = payloadForEvent(event);
  if (typeof payload.claim === "string" && payload.claim.trim()) {
    return payload.claim.trim();
  }
  if (typeof payload.claim_text === "string" && payload.claim_text.trim()) {
    return payload.claim_text.trim();
  }
  return null;
}

function evidenceRefsForEvents(
  store: FeishuTaskWikiStore,
  events: EventRecordV2[],
): Array<{ event_id: string; evidence_id: string; source_ref: string; quote: string | null }> {
  return events.flatMap((event) => {
    const evidence = store.getEvidenceByIdV2(event.evidence_id);
    if (!evidence) {
      return [];
    }
    const payload = payloadForEvent(event);
    return [
      {
        event_id: event.event_id,
        evidence_id: evidence.evidence_id,
        source_ref: sourceRefFromEvidence(evidence.source_locator_json),
        quote:
          typeof payload.evidence_quote === "string" ? payload.evidence_quote : evidence.content_text,
      },
    ];
  });
}

function latestEventForIds(store: FeishuTaskWikiStore, idsJson: string): EventRecordV2[] {
  const ids = stringArrayFromJson(idsJson);
  return store
    .getEventsByIdsV2(ids)
    .toSorted(
      (left, right) =>
        right.occurred_at.localeCompare(left.occurred_at) ||
        right.created_at - left.created_at ||
        right.event_id.localeCompare(left.event_id),
    );
}

export function classifyQueryV2(query: string): QueryClassV2 {
  const normalized = query.toLowerCase();
  if (TASK_MEMORY_CARD_RE.test(normalized)) {
    return "task_memory_card";
  }
  if (/(why|为什么|原因|卡在哪|blocked|blocker|dependency|constraint|risk)/i.test(normalized)) {
    return "task_why";
  }
  if (/(timeline|历史|演进|什么时候|何时|changed|commitment|时间线)/i.test(normalized)) {
    return "task_timeline";
  }
  if (/(哪些|列出|all|关系|依赖|related)/i.test(normalized)) {
    return "list_relation";
  }
  return "task_state";
}

export function resolveEntityRefV2(
  store: FeishuTaskWikiStore,
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
  const candidates = store.findEntityMatchesV2(query, 10);
  const rank = (entityType: string): number =>
    entityType === "task" ? 0 : entityType === "topic" ? 1 : entityType === "person" ? 2 : 3;
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

function buildTaskStateHit(store: FeishuTaskWikiStore, taskRef: string): GraphHit[] {
  const state = store.getTaskCurrentStateV2(taskRef);
  if (!state) {
    return [];
  }
  const lastEvent = store.getEventByIdV2(state.last_event_id);
  const evidence = lastEvent ? store.getEvidenceByIdV2(lastEvent.evidence_id) : null;
  const latestStatusEvent = latestEventForIds(store, state.active_status_event_ids_json)[0] ?? null;
  const latestCommitmentEvent =
    latestEventForIds(store, state.active_commitment_event_ids_json)[0] ?? null;
  return [
    {
      type: "state",
      entity_id: taskRef,
      source_ref: evidence
        ? sourceRefFromEvidence(evidence.source_locator_json)
        : "transcripts/unknown.txt#L1-L1",
      score: 1,
      snippet_structured: {
        query_kind: "task_state",
        task_ref: state.task_ref,
        primary_topic_ref: state.primary_topic_ref,
        current_conclusion: claimTextFromEvent(
          state.active_conclusion_event_id
            ? store.getEventByIdV2(state.active_conclusion_event_id)
            : null,
        ),
        latest_status: claimTextFromEvent(latestStatusEvent),
        latest_commitment: claimTextFromEvent(latestCommitmentEvent),
        last_event_id: state.last_event_id,
        last_updated_at: state.updated_at,
      },
    },
  ];
}

function buildWhyHits(store: FeishuTaskWikiStore, taskRef: string, limit: number): GraphHit[] {
  const state = store.getTaskCurrentStateV2(taskRef);
  if (!state) {
    return [];
  }
  const eventIds = [
    ...stringArrayFromJson(state.active_rationale_event_ids_json),
    ...stringArrayFromJson(state.active_objection_event_ids_json),
    ...stringArrayFromJson(state.active_constraint_event_ids_json),
  ];
  return store
    .getEventsByIdsV2([...new Set(eventIds)])
    .toSorted(
      (left, right) =>
        right.occurred_at.localeCompare(left.occurred_at) ||
        right.created_at - left.created_at,
    )
    .slice(0, limit)
    .map<GraphHit>((event) => {
      const evidence = store.getEvidenceByIdV2(event.evidence_id);
      return {
        type: "event",
        entity_id: taskRef,
        source_ref: evidence
          ? sourceRefFromEvidence(evidence.source_locator_json)
          : "transcripts/unknown.txt#L1-L1",
        score: 0.95,
        snippet_structured: {
          query_kind: "task_why",
          occurred_at: event.occurred_at,
          actor: event.actor_ref,
          action: eventLabel(event.event_type),
          object: event.object_ref,
          event_type: event.event_type,
          payload_json: event.payload_json,
          evidence_excerpt: evidence?.content_text ?? null,
        },
      };
    });
}

function buildTimelineHits(store: FeishuTaskWikiStore, entityRef: string, limit: number): GraphHit[] {
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
        query_kind: "task_timeline",
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
  store: FeishuTaskWikiStore,
  query: string,
  resolvedRef: string | null,
  limit: number,
): GraphHit[] {
  const lower = query.toLowerCase();
  if (lower.includes("blocked") || lower.includes("constraint")) {
    return store
      .listTaskStatesV2()
      .filter((state) => stringArrayFromJson(state.active_constraint_event_ids_json).length > 0)
      .slice(0, limit)
      .map((state, index) => ({
        type: "state",
        entity_id: state.task_ref,
        source_ref: "transcripts/unknown.txt#L1-L1",
        score: Math.max(0.4, 1 - index * 0.03),
        snippet_structured: {
          query_kind: "list_relation",
          latest_status: claimTextFromEvent(
            latestEventForIds(store, state.active_status_event_ids_json)[0] ?? null,
          ),
          latest_owner: null,
          last_updated_at: state.updated_at,
          current_blocker_ref: null,
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

function buildTaskMemoryCardHit(
  store: FeishuTaskWikiStore,
  state: TaskCurrentStateViewV2,
): GraphHit {
  const conclusionEvent = state.active_conclusion_event_id
    ? store.getEventByIdV2(state.active_conclusion_event_id)
    : null;
  const rationaleEvents = latestEventForIds(store, state.active_rationale_event_ids_json);
  const objectionEvents = latestEventForIds(store, state.active_objection_event_ids_json);
  const constraintEvents = latestEventForIds(store, state.active_constraint_event_ids_json);
  const statusEvents = latestEventForIds(store, state.active_status_event_ids_json);
  const scopeEvents = latestEventForIds(store, state.active_scope_event_ids_json);
  const timeEvents = latestEventForIds(store, state.active_time_point_event_ids_json);
  const commitmentEvents = latestEventForIds(store, state.active_commitment_event_ids_json);
  const allEvents = [
    ...(conclusionEvent ? [conclusionEvent] : []),
    ...rationaleEvents,
    ...objectionEvents,
    ...constraintEvents,
    ...statusEvents,
    ...scopeEvents,
    ...timeEvents,
    ...commitmentEvents,
  ];
  const evidenceRefs = evidenceRefsForEvents(store, allEvents);
  return {
    type: "state",
    entity_id: state.task_ref,
    source_ref: evidenceRefs[0]?.source_ref ?? "transcripts/unknown.txt#L1-L1",
    score: 1,
    snippet_structured: {
      query_kind: "task_memory_card",
      task_ref: state.task_ref,
      primary_topic_ref: state.primary_topic_ref,
      current_conclusion: claimTextFromEvent(conclusionEvent),
      rationales: rationaleEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      objections: objectionEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      constraints: constraintEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      statuses: statusEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      scope_claims: scopeEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      time_point_claims: timeEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      commitments: commitmentEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      evidence_refs: evidenceRefs,
      historical_claims: store.listEventsForRefV2(state.task_ref, 50).map((event) => ({
        event_id: event.event_id,
        occurred_at: event.occurred_at,
        ...payloadForEvent(event),
      })),
      last_event_id: state.last_event_id,
    },
  };
}

function buildTaskMemoryCardHits(
  store: FeishuTaskWikiStore,
  query: string,
  limit: number,
  resolvedRef: string | null,
): GraphHit[] {
  const taskMatch = query.match(/\b([A-Z][A-Z0-9]+-\d+)\b/);
  const taskId = taskMatch?.[1] ?? (resolvedRef?.startsWith("task:") ? resolvedRef.slice(5) : null);
  if (!taskId) {
    return [];
  }
  const state = store.getTaskCurrentStateV2(`task:${taskId}`);
  return state ? [buildTaskMemoryCardHit(store, state)].slice(0, limit) : [];
}

export async function searchGraphV2(
  store: FeishuTaskWikiStore,
  query: string,
  maxResults: number,
): Promise<{ hits: GraphHit[]; queryClass: QueryClassV2; resolvedRef: string | null }> {
  const queryClass = classifyQueryV2(query);
  const resolved = resolveEntityRefV2(store, query);
  const resolvedRef = resolved?.entity_ref ?? null;
  const limit = Math.max(1, maxResults);
  if (queryClass === "task_memory_card") {
    return {
      hits: buildTaskMemoryCardHits(store, query, limit, resolvedRef).slice(0, limit),
      queryClass,
      resolvedRef,
    };
  }
  if (queryClass === "task_state" && resolvedRef?.startsWith("task:")) {
    return { hits: buildTaskStateHit(store, resolvedRef).slice(0, limit), queryClass, resolvedRef };
  }
  if (queryClass === "task_why" && resolvedRef?.startsWith("task:")) {
    return { hits: buildWhyHits(store, resolvedRef, limit), queryClass, resolvedRef };
  }
  if (queryClass === "task_timeline" && resolvedRef) {
    return { hits: buildTimelineHits(store, resolvedRef, limit), queryClass, resolvedRef };
  }
  return {
    hits: buildListRelationHits(store, query, resolvedRef, limit),
    queryClass,
    resolvedRef,
  };
}
