import type { DecisionStateViewV2, EventRecordV2 } from "./schema-v2.js";
import type { GraphHit } from "./schema.js";
import type { CanonicalStore } from "./store.js";

type QueryClass = "state" | "why" | "timeline" | "list_relation" | "decision_card";

const DECISION_CARD_RE =
  /(之前怎么定的|为什么这样定|反对意见|这个结论后来改过吗|为什么.*确认日期|现在到底按哪个口径|之前为什么选|历史决策|结论|口径|方案)/i;

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
    case "decision_claim_recorded":
      return "decision claim recorded";
    default:
      return eventType;
  }
}

export function classifyQueryV2(query: string): QueryClass {
  const normalized = query.toLowerCase();
  if (DECISION_CARD_RE.test(normalized)) {
    return "decision_card";
  }
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

function resolveDecisionAxisKey(query: string): string | null {
  if (/(确认日期|发布日期|目标日期|5月|5 月|deadline|release date)/i.test(query)) {
    return "release_date";
  }
  if (/(方案|选 A|选 B|solution)/i.test(query)) {
    return "solution_choice";
  }
  if (/(灰度|gray|灰度发布)/i.test(query)) {
    return "gray_release_plan";
  }
  if (/(依赖|迁移窗口|readiness|checklist|ready)/i.test(query)) {
    return "dependency_readiness";
  }
  if (/(对外|同步|口径|communication)/i.test(query)) {
    return "external_communication";
  }
  if (/(阶段|stage)/i.test(query)) {
    return "project_stage";
  }
  if (/(风险|risk)/i.test(query)) {
    return "risk_handling";
  }
  if (/(决策|结论|之前怎么定)/i.test(query)) {
    return "general_decision";
  }
  return null;
}

function arrayFromJson(value: string): string[] {
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string")
      : [];
  } catch {
    return [];
  }
}

function payloadForDecisionEvent(event: EventRecordV2): Record<string, unknown> {
  return asRecord(event.payload_json);
}

function claimTextFromEvent(event: EventRecordV2 | null): string | null {
  if (!event) {
    return null;
  }
  const payload = payloadForDecisionEvent(event);
  return typeof payload.claim_text === "string" ? payload.claim_text : null;
}

function collectDecisionEvidence(
  store: CanonicalStore,
  events: EventRecordV2[],
): Array<{ event_id: string; evidence_id: string; source_ref: string; quote: string | null }> {
  return events.flatMap((event) => {
    const evidence = store.getEvidenceByIdV2(event.evidence_id);
    if (!evidence) {
      return [];
    }
    const payload = payloadForDecisionEvent(event);
    return [
      {
        event_id: event.event_id,
        evidence_id: evidence.evidence_id,
        source_ref: sourceRefFromEvidence(evidence.source_locator_json),
        quote:
          typeof payload.evidence_quote === "string"
            ? payload.evidence_quote
            : evidence.content_text,
      },
    ];
  });
}

function buildDecisionCardHit(
  store: CanonicalStore,
  decisionState: DecisionStateViewV2,
  decisionEvents: EventRecordV2[],
): GraphHit {
  const conclusionEvent = decisionState.active_conclusion_event_id
    ? store.getEventByIdV2(decisionState.active_conclusion_event_id)
    : null;
  const rationaleEvents = store.getEventsByIdsV2(
    arrayFromJson(decisionState.active_rationale_event_ids_json),
  );
  const objectionEvents = store.getEventsByIdsV2(
    arrayFromJson(decisionState.active_objection_event_ids_json),
  );
  const activeStageEvent = decisionState.active_stage_event_id
    ? store.getEventByIdV2(decisionState.active_stage_event_id)
    : null;
  const timePointEvents = store.getEventsByIdsV2(
    arrayFromJson(decisionState.active_time_point_event_ids_json),
  );
  const evidenceRefs = collectDecisionEvidence(store, decisionEvents);
  const sourceRef = evidenceRefs[0]?.source_ref ?? "transcripts/unknown.txt#L1-L1";
  return {
    type: "state",
    entity_id: decisionState.topic_ref,
    source_ref: sourceRef,
    score: 1,
    snippet_structured: {
      query_kind: "decision_card",
      topic_ref: decisionState.topic_ref,
      decision_axis_key: decisionState.decision_axis_key,
      decision_axis_text: decisionState.decision_axis_text,
      current_conclusion: claimTextFromEvent(conclusionEvent),
      rationales: rationaleEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      objections: objectionEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      stage_claims: activeStageEvent ? [claimTextFromEvent(activeStageEvent)].filter(Boolean) : [],
      time_point_claims: timePointEvents
        .map((event) => claimTextFromEvent(event))
        .filter((value): value is string => Boolean(value)),
      evidence_refs: evidenceRefs,
      historical_claims: decisionEvents.map((event) => ({
        event_id: event.event_id,
        occurred_at: event.occurred_at,
        ...payloadForDecisionEvent(event),
      })),
      last_event_id: decisionState.last_event_id,
    },
  };
}

function buildDecisionCardHits(
  store: CanonicalStore,
  query: string,
  limit: number,
  resolvedRef: string | null,
): GraphHit[] {
  const taskMatch = query.match(/\b([A-Z][A-Z0-9]+-\d+)\b/);
  const axisKey = resolveDecisionAxisKey(query);
  const taskId = taskMatch?.[1] ?? (resolvedRef?.startsWith("task:") ? resolvedRef.slice(5) : null);
  if (!taskId) {
    return [];
  }
  const states = store.findDecisionStatesByAnchor({
    anchorType: "task",
    anchorRef: taskId,
    decisionAxisKey: axisKey,
    limit,
  });
  return states.slice(0, limit).map((state) => {
    const events = store.listDecisionEventsForTopic({
      topicRef: state.topic_ref,
      decisionAxisKey: state.decision_axis_key,
      decisionAxisInstanceId: state.decision_axis_instance_id,
      limit: 50,
    });
    return buildDecisionCardHit(store, state, events);
  });
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
  if (queryClass === "decision_card") {
    return {
      hits: buildDecisionCardHits(store, query, limit, resolvedRef).slice(0, limit),
      queryClass,
      resolvedRef,
    };
  }
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
