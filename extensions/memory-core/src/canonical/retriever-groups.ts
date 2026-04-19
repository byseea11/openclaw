import {
  STRONG_GRAPH_RELATIONS,
  WEAK_GRAPH_RELATIONS,
  type EventRecord,
  type GraphHit,
  type ProjectionSourceState,
  type StrongGraphRelation,
} from "./schema.js";
import type { CanonicalStore, EntityResolutionCandidate } from "./store.js";

export type QueryClass = "state" | "list" | "timeline" | "blocker_why";
export type EvidenceFreshness = "fresh" | "mixed" | "unknown" | "stale";
export type EvidenceGroupType = "state" | "relation_list" | "timeline" | "blocker" | "conflict";
export type ResolutionStatus = "stable" | "ambiguous" | "unresolved";

type EdgeRow = ReturnType<CanonicalStore["searchGraphEdges"]>[number];

export type EvidenceGroup = {
  group_type: EvidenceGroupType;
  group_id: string;
  anchor_entity_id?: string;
  relation?: string;
  target_entity_ids?: string[];
  summary_label: string;
  evidence_event_ids: string[];
  evidence_edge_ids: string[];
  source_ref?: string;
  last_seen_at?: string;
  confidence: number;
  freshness: EvidenceFreshness;
  has_conflict?: boolean;
  is_main_evidence?: boolean;
  conflict_type?: string;
};

export type PlannerResult = {
  query_class: QueryClass;
  resolved_entity_ids: string[];
  resolution_status: ResolutionStatus;
  resolution_candidates: Array<Record<string, unknown>>;
  main_groups: EvidenceGroup[];
  conflict_groups: EvidenceGroup[];
  weak_edge_expansions: EvidenceGroup[];
  fallback_hits: GraphHit[];
  freshness_decisions: Array<Record<string, unknown>>;
  final_group_ids: string[];
  fallback_reason?: string[];
  group_budget: Record<string, number>;
};

type ResolutionResult = {
  status: ResolutionStatus;
  entityIds: string[];
  candidates: EntityResolutionCandidate[];
};

const FRESHNESS_RANK: Record<EvidenceFreshness, number> = {
  fresh: 4,
  mixed: 3,
  unknown: 2,
  stale: 1,
};

const RESOLVED_STATUS_RE = /\b(done|resolved|unblocked|closed|complete|completed)\b/i;
const BLOCKED_STATUS_RE = /\b(blocked|blocking|waiting|pending)\b/i;
const DECISION_EVIDENCE_RE =
  /\b(decid|decision|approval|approved|rejected|批准|通过|决定|审批|驳回|拒绝)\b/i;
const DECISION_QUERY_RE =
  /\b(decid|decision|approval|approved|rejected)\b|决定|审批|批准|驳回|拒绝/i;
const MEETING_QUERY_RE = /\b(meeting|scheduled|schedule|calendar)\b|会议|安排/i;
const APPROVED_RE = /\b(approved|accepted|approval|批准|通过)\b/i;
const REJECTED_RE = /\b(rejected|declined|denied|blocked|驳回|拒绝)\b/i;

export function isP1aGraphRecallEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  const value = env.OPENCLAW_GRAPH_RECALL_P1A?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

export function classifyGraphQuery(query: string): QueryClass {
  if (/(why|blocked|blocker|blocking|depends|dependency|卡|为什么|原因|依赖)/i.test(query)) {
    return "blocker_why";
  }
  if (/(when|timeline|history|change|changed|变化|历史|什么时候|何时)/i.test(query)) {
    return "timeline";
  }
  if (/(list|show all|which|有哪些|列出|所有)/i.test(query)) {
    return "list";
  }
  return "state";
}

function budgetForClass(queryClass: QueryClass, k: number): Record<string, number> {
  switch (queryClass) {
    case "state":
      return { total: Math.min(k, 4), main: 1, conflict: 1, weak: 2, fallback: 2 };
    case "list":
      return { total: Math.min(k, 6), main: 4, conflict: 0, weak: 2, fallback: 2 };
    case "timeline":
      return { total: Math.min(k, 7), main: 5, conflict: 1, weak: 2, fallback: 2 };
    case "blocker_why":
      return { total: Math.min(k, 6), main: 3, conflict: 1, weak: 2, fallback: 2 };
    default:
      return { total: Math.min(k, 4), main: 1, conflict: 1, weak: 2, fallback: 2 };
  }
}

function relationsForClass(queryClass: QueryClass): StrongGraphRelation[] {
  switch (queryClass) {
    case "blocker_why":
      return ["blocks", "depends_on", "owned_by", "decided_by"];
    case "timeline":
    case "list":
      return [...STRONG_GRAPH_RELATIONS];
    case "state":
      return ["owned_by", "assigned_to", "blocks", "decided_by", "scheduled_for"];
    default:
      return ["owned_by", "assigned_to", "blocks", "decided_by", "scheduled_for"];
  }
}

function recencyScore(value: string | null): number {
  if (!value) {
    return 0;
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return 0;
  }
  const ageDays = Math.max(0, (Date.now() - timestamp) / (24 * 60 * 60 * 1000));
  return Math.max(0, 1 / (1 + ageDays / 90));
}

function entityTypePrior(
  candidate: EntityResolutionCandidate,
  queryClass: QueryClass,
  query: string,
): number {
  if (candidate.entity_type === "decision" && DECISION_QUERY_RE.test(query)) {
    return 0.22;
  }
  if (candidate.entity_type === "meeting" && MEETING_QUERY_RE.test(query)) {
    return 0.22;
  }
  if (
    (candidate.entity_type === "task" || candidate.entity_type === "project") &&
    (queryClass === "state" || queryClass === "list" || queryClass === "blocker_why")
  ) {
    return 0.12;
  }
  if (candidate.entity_type === "meeting" && queryClass === "timeline") {
    return 0.12;
  }
  if (candidate.entity_type === "decision" && queryClass !== "list") {
    return 0.1;
  }
  if (candidate.entity_type === "person" && queryClass === "state") {
    return 0.05;
  }
  return 0;
}

function matchKindPrior(candidate: EntityResolutionCandidate): number {
  switch (candidate.match_kind) {
    case "stable_id":
      return 0.3;
    case "exact_alias":
      return 0.2;
    case "normalized_alias":
      return 0.1;
    case "canonical_name":
      return 0.05;
    default:
      return 0;
  }
}

function candidateScore(
  candidate: EntityResolutionCandidate,
  queryClass: QueryClass,
  query: string,
): number {
  return (
    candidate.confidence +
    matchKindPrior(candidate) +
    entityTypePrior(candidate, queryClass, query) +
    recencyScore(candidate.last_seen_at) * 0.05
  );
}

function resolveEntities(
  store: CanonicalStore,
  query: string,
  queryClass: QueryClass,
): ResolutionResult {
  const scored = store
    .resolveEntityCandidates(query, 8)
    .map((candidate) => ({
      candidate,
      score: candidateScore(candidate, queryClass, query),
    }))
    .toSorted((left, right) => {
      if (left.score !== right.score) {
        return right.score - left.score;
      }
      return left.candidate.entity_id.localeCompare(right.candidate.entity_id);
    });
  if (scored.length === 0) {
    return { status: "unresolved", entityIds: [], candidates: [] };
  }
  const top = scored[0];
  const second = scored[1];
  const exactTop =
    top?.candidate.match_kind === "stable_id" || top?.candidate.match_kind === "exact_alias";
  const tied = scored.filter((entry) => Math.abs(entry.score - (top?.score ?? 0)) < 0.001).length;
  const ambiguous =
    !exactTop && (tied > 3 || (second ? Math.abs(top.score - second.score) < 0.15 : false));
  return {
    status: ambiguous ? "ambiguous" : "stable",
    entityIds: ambiguous
      ? []
      : exactTop
        ? scored.slice(0, 4).map((entry) => entry.candidate.entity_id)
        : [top.candidate.entity_id],
    candidates: scored.slice(0, 6).map((entry) => entry.candidate),
  };
}

function freshnessForSession(
  sessionId: string | null,
  sourceRef: string,
  stateBySource: Map<string, ProjectionSourceState>,
): { freshness: EvidenceFreshness; reason: string; source_id: string | null } {
  if (!sessionId) {
    return {
      freshness: "unknown",
      reason: sourceRef.startsWith("transcripts/")
        ? "missing_source_state"
        : "non_transcript_source",
      source_id: null,
    };
  }
  const state = stateBySource.get(sessionId);
  if (!state) {
    return { freshness: "unknown", reason: "missing_source_state", source_id: sessionId };
  }
  if (state.status === "clean") {
    return { freshness: "fresh", reason: "source_clean", source_id: sessionId };
  }
  return { freshness: "stale", reason: `source_${state.status}`, source_id: sessionId };
}

function combineFreshness(values: EvidenceFreshness[]): EvidenceFreshness {
  const unique = new Set(values);
  if (unique.size === 0 || (unique.size === 1 && unique.has("unknown"))) {
    return "unknown";
  }
  if (unique.size === 1 && unique.has("fresh")) {
    return "fresh";
  }
  if (unique.size === 1 && unique.has("stale")) {
    return "stale";
  }
  if (unique.has("fresh")) {
    return "mixed";
  }
  return unique.has("unknown") ? "unknown" : "stale";
}

function latestDate(values: Array<string | undefined>): string | undefined {
  return values
    .filter((value): value is string => Boolean(value))
    .toSorted()
    .at(-1);
}

function averageConfidence(edges: EdgeRow[], events: EventRecord[] = []): number {
  const values = [
    ...edges.map((edge) => edge.confidence),
    ...events.map((event) => event.confidence),
  ].filter((value) => Number.isFinite(value));
  if (values.length === 0) {
    return 0.5;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function groupId(parts: Array<string | null | undefined>): string {
  return parts
    .map((part) => part ?? "")
    .join(":")
    .replace(/[^A-Za-z0-9_.:-]+/g, "_");
}

function groupFromEdges(params: {
  groupType: EvidenceGroupType;
  queryClass: QueryClass;
  edges: EdgeRow[];
  events?: EventRecord[];
  anchorEntityId?: string;
  relation?: string;
  targetEntityIds?: string[];
  label: string;
  freshness: EvidenceFreshness;
  conflictType?: string;
  main?: boolean;
}): EvidenceGroup {
  const events = params.events ?? [];
  const evidenceEventIds = [
    ...new Set([
      ...params.edges.map((edge) => edge.evidence_event_id),
      ...events.map((event) => event.event_id),
    ]),
  ];
  const evidenceEdgeIds = [...new Set(params.edges.map((edge) => edge.edge_id))];
  return {
    group_type: params.groupType,
    group_id: groupId([
      params.queryClass,
      params.groupType,
      params.anchorEntityId,
      params.relation,
      params.targetEntityIds?.join("_"),
      evidenceEdgeIds[0],
      evidenceEventIds[0],
    ]),
    anchor_entity_id: params.anchorEntityId,
    relation: params.relation,
    target_entity_ids: params.targetEntityIds,
    summary_label: params.label,
    evidence_event_ids: evidenceEventIds,
    evidence_edge_ids: evidenceEdgeIds,
    source_ref: params.edges[0]?.source_ref ?? events[0]?.source_ref,
    last_seen_at: latestDate([
      ...params.edges.map((edge) => edge.occurred_at),
      ...events.map((event) => event.occurred_at),
    ]),
    confidence: averageConfidence(params.edges, events),
    freshness: params.freshness,
    conflict_type: params.conflictType,
    is_main_evidence: params.main,
  };
}

function buildFreshnessContext(store: CanonicalStore, edges: EdgeRow[], events: EventRecord[]) {
  const stateBySource = new Map(
    store.listProjectionStates().map((state) => [state.source_id, state]),
  );
  const freshnessDecisions: Array<Record<string, unknown>> = [];
  const edgeFreshness = new Map<string, EvidenceFreshness>();
  const eventFreshness = new Map<string, EvidenceFreshness>();
  for (const edge of edges) {
    const decision = freshnessForSession(edge.session_id, edge.source_ref, stateBySource);
    edgeFreshness.set(edge.edge_id, decision.freshness);
    freshnessDecisions.push({
      evidence_type: "edge",
      evidence_id: edge.edge_id,
      source_ref: edge.source_ref,
      source_id: decision.source_id,
      freshness: decision.freshness,
      reason: decision.reason,
    });
  }
  for (const event of events) {
    const decision = freshnessForSession(event.session_id, event.source_ref, stateBySource);
    eventFreshness.set(event.event_id, decision.freshness);
    freshnessDecisions.push({
      evidence_type: "event",
      evidence_id: event.event_id,
      source_ref: event.source_ref,
      source_id: decision.source_id,
      freshness: decision.freshness,
      reason: decision.reason,
    });
  }
  return {
    freshnessDecisions,
    groupFreshness(groupEdges: EdgeRow[], groupEvents: EventRecord[] = []) {
      return combineFreshness([
        ...groupEdges.map((edge) => edgeFreshness.get(edge.edge_id) ?? "unknown"),
        ...groupEvents.map((event) => eventFreshness.get(event.event_id) ?? "unknown"),
      ]);
    },
  };
}

function groupRank(group: EvidenceGroup): number {
  return (
    FRESHNESS_RANK[group.freshness] * 10 +
    group.confidence * 5 +
    (group.evidence_edge_ids.length + group.evidence_event_ids.length) * 0.1 +
    recencyScore(group.last_seen_at ?? null)
  );
}

function sortGroups(groups: EvidenceGroup[]): EvidenceGroup[] {
  return groups.toSorted((left, right) => {
    if (FRESHNESS_RANK[left.freshness] !== FRESHNESS_RANK[right.freshness]) {
      return FRESHNESS_RANK[right.freshness] - FRESHNESS_RANK[left.freshness];
    }
    const leftRank = groupRank(left);
    const rightRank = groupRank(right);
    if (leftRank !== rightRank) {
      return rightRank - leftRank;
    }
    return left.group_id.localeCompare(right.group_id);
  });
}

function statusText(event: EventRecord): string {
  return `${event.action} ${event.object ?? ""} ${event.status_before ?? ""} ${event.status_after ?? ""}`;
}

function detectConflictGroups(params: {
  queryClass: QueryClass;
  edges: EdgeRow[];
  events: EventRecord[];
  freshness: ReturnType<typeof buildFreshnessContext>;
}): EvidenceGroup[] {
  const conflicts: EvidenceGroup[] = [];
  const edgesByRelationAnchor = new Map<string, EdgeRow[]>();
  for (const edge of params.edges) {
    if (
      !["owned_by", "assigned_to", "decided_by", "scheduled_for", "blocks", "depends_on"].includes(
        edge.relation,
      )
    ) {
      continue;
    }
    const key = `${edge.relation}:${edge.src_entity_id}`;
    edgesByRelationAnchor.set(key, [...(edgesByRelationAnchor.get(key) ?? []), edge]);
  }
  for (const [key, edges] of edgesByRelationAnchor) {
    const [relation, anchor] = key.split(":");
    const targets = new Set(edges.map((edge) => edge.dst_entity_id));
    const dates = new Set(edges.map((edge) => edge.occurred_at.slice(0, 10)));
    const conflictType =
      relation === "scheduled_for" && dates.size > 1
        ? "scheduled_for_conflict"
        : (relation === "owned_by" || relation === "assigned_to") && targets.size > 1
          ? "owner_conflict"
          : relation === "decided_by" && targets.size > 1
            ? "decision_approval_conflict"
            : null;
    if (!conflictType) {
      continue;
    }
    conflicts.push(
      groupFromEdges({
        queryClass: params.queryClass,
        groupType: "conflict",
        edges,
        anchorEntityId: anchor,
        relation,
        targetEntityIds: [...targets],
        label: `${conflictType}: ${relation} has conflicting evidence`,
        freshness: params.freshness.groupFreshness(edges),
        conflictType,
      }),
    );
  }
  const statusEvents = params.events.filter((event) => event.status_after);
  const statuses = new Set(
    statusEvents
      .map((event) => event.status_after?.toLowerCase())
      .filter((status): status is string => Boolean(status)),
  );
  if (
    statuses.size > 1 &&
    ([...statuses].some((status) => BLOCKED_STATUS_RE.test(status)) ||
      [...statuses].some((status) => RESOLVED_STATUS_RE.test(status)))
  ) {
    conflicts.push(
      groupFromEdges({
        queryClass: params.queryClass,
        groupType: "conflict",
        edges: [],
        events: statusEvents,
        anchorEntityId: statusEvents[0]?.entity_id,
        relation: "status",
        label: "status_conflict: status has conflicting evidence",
        freshness: params.freshness.groupFreshness([], statusEvents),
        conflictType: "status_conflict",
      }),
    );
  }
  const approvalEvents = params.events.filter((event) => {
    const text = statusText(event);
    return DECISION_EVIDENCE_RE.test(text) && (APPROVED_RE.test(text) || REJECTED_RE.test(text));
  });
  if (
    approvalEvents.some((event) => APPROVED_RE.test(statusText(event))) &&
    approvalEvents.some((event) => REJECTED_RE.test(statusText(event)))
  ) {
    conflicts.push(
      groupFromEdges({
        queryClass: params.queryClass,
        groupType: "conflict",
        edges: [],
        events: approvalEvents,
        anchorEntityId: approvalEvents[0]?.entity_id,
        relation: "decided_by",
        label: "decision_approval_conflict: approval evidence conflicts",
        freshness: params.freshness.groupFreshness([], approvalEvents),
        conflictType: "decision_approval_conflict",
      }),
    );
  }
  const blockerEvents = params.events.filter((event) => {
    const text = statusText(event);
    return BLOCKED_STATUS_RE.test(text) || RESOLVED_STATUS_RE.test(text);
  });
  if (
    blockerEvents.some((event) => BLOCKED_STATUS_RE.test(statusText(event))) &&
    blockerEvents.some((event) => RESOLVED_STATUS_RE.test(statusText(event)))
  ) {
    conflicts.push(
      groupFromEdges({
        queryClass: params.queryClass,
        groupType: "conflict",
        edges: params.edges.filter(
          (edge) => edge.relation === "blocks" || edge.relation === "depends_on",
        ),
        events: blockerEvents,
        anchorEntityId: blockerEvents[0]?.entity_id,
        relation: "blocks",
        label: "blocker_conflict: blocker status changed or conflicts",
        freshness: params.freshness.groupFreshness(
          params.edges.filter(
            (edge) => edge.relation === "blocks" || edge.relation === "depends_on",
          ),
          blockerEvents,
        ),
        conflictType: "blocker_conflict",
      }),
    );
  }
  return sortGroups(conflicts);
}

function markConflicts(
  mainGroups: EvidenceGroup[],
  conflictGroups: EvidenceGroup[],
): EvidenceGroup[] {
  if (conflictGroups.length === 0) {
    return mainGroups;
  }
  const conflictAnchors = new Set(
    conflictGroups.map((group) => group.anchor_entity_id).filter(Boolean),
  );
  const conflictRelations = new Set(conflictGroups.map((group) => group.relation).filter(Boolean));
  return mainGroups.map((group) => ({
    ...group,
    has_conflict:
      group.has_conflict ||
      (group.anchor_entity_id ? conflictAnchors.has(group.anchor_entity_id) : false) ||
      (group.relation ? conflictRelations.has(group.relation) : false),
  }));
}

function buildStateGroups(params: {
  store: CanonicalStore;
  queryClass: QueryClass;
  entityIds: string[];
  edges: EdgeRow[];
  events: EventRecord[];
  freshness: ReturnType<typeof buildFreshnessContext>;
}): EvidenceGroup[] {
  const groups: EvidenceGroup[] = [];
  for (const entityId of params.entityIds) {
    const relevantEdges = params.edges.filter(
      (edge) => edge.src_entity_id === entityId || edge.dst_entity_id === entityId,
    );
    const relevantEvents = params.events.filter((event) => event.entity_id === entityId);
    if (relevantEdges.length === 0 && relevantEvents.length === 0) {
      continue;
    }
    groups.push(
      groupFromEdges({
        queryClass: params.queryClass,
        groupType: "state",
        edges: relevantEdges,
        events: relevantEvents,
        anchorEntityId: entityId,
        relation: "state",
        targetEntityIds: [...new Set(relevantEdges.map((edge) => edge.dst_entity_id))],
        label: `State evidence for ${entityId}`,
        freshness: params.freshness.groupFreshness(relevantEdges, relevantEvents),
        main: true,
      }),
    );
  }
  return sortGroups(groups);
}

function buildListGroups(params: {
  queryClass: QueryClass;
  edges: EdgeRow[];
  eventsById: Map<string, EventRecord>;
  freshness: ReturnType<typeof buildFreshnessContext>;
}): EvidenceGroup[] {
  const byRelationTarget = new Map<string, EdgeRow[]>();
  for (const edge of params.edges) {
    const key = `${edge.relation}:${edge.dst_entity_id}`;
    byRelationTarget.set(key, [...(byRelationTarget.get(key) ?? []), edge]);
  }
  const groups = [...byRelationTarget.entries()].map(([key, edges]) => {
    const [relation, target] = key.split(":");
    const events = edges
      .map((edge) => params.eventsById.get(edge.evidence_event_id))
      .filter((event): event is EventRecord => Boolean(event));
    return groupFromEdges({
      queryClass: params.queryClass,
      groupType: "relation_list",
      edges,
      events,
      anchorEntityId: edges[0]?.src_entity_id,
      relation,
      targetEntityIds: target ? [target] : [],
      label: `${relation} -> ${edges[0]?.dst_name ?? target}`,
      freshness: params.freshness.groupFreshness(edges, events),
      main: true,
    });
  });
  return sortGroups(groups);
}

function buildTimelineGroups(params: {
  queryClass: QueryClass;
  edges: EdgeRow[];
  eventsById: Map<string, EventRecord>;
  freshness: ReturnType<typeof buildFreshnessContext>;
}): EvidenceGroup[] {
  const groups = params.edges.map((edge) => {
    const event = params.eventsById.get(edge.evidence_event_id);
    return groupFromEdges({
      queryClass: params.queryClass,
      groupType: "timeline",
      edges: [edge],
      events: event ? [event] : [],
      anchorEntityId: edge.src_entity_id,
      relation: edge.relation,
      targetEntityIds: [edge.dst_entity_id],
      label: `${edge.occurred_at.slice(0, 10)} ${edge.src_name ?? edge.src_entity_id} ${edge.relation} ${edge.dst_name ?? edge.dst_entity_id}`,
      freshness: params.freshness.groupFreshness([edge], event ? [event] : []),
      main: true,
    });
  });
  return groups.toSorted((left, right) => {
    const leftDate = left.last_seen_at ?? "";
    const rightDate = right.last_seen_at ?? "";
    if (leftDate !== rightDate) {
      return leftDate.localeCompare(rightDate);
    }
    return groupRank(right) - groupRank(left);
  });
}

function buildBlockerGroups(params: {
  queryClass: QueryClass;
  edges: EdgeRow[];
  eventsById: Map<string, EventRecord>;
  freshness: ReturnType<typeof buildFreshnessContext>;
}): EvidenceGroup[] {
  const blockerEdges = params.edges.filter(
    (edge) => edge.relation === "blocks" || edge.relation === "depends_on",
  );
  const contextEdges = params.edges.filter(
    (edge) => edge.relation === "owned_by" || edge.relation === "decided_by",
  );
  const byTarget = new Map<string, EdgeRow[]>();
  for (const edge of blockerEdges) {
    const key = edge.dst_entity_id || edge.src_entity_id;
    byTarget.set(key, [...(byTarget.get(key) ?? []), edge]);
  }
  const groups = [...byTarget.entries()].map(([target, edges]) => {
    const relatedContext = contextEdges.filter((edge) =>
      edges.some((blocker) => blocker.src_entity_id === edge.src_entity_id),
    );
    const allEdges = [...edges, ...relatedContext];
    const events = allEdges
      .map((edge) => params.eventsById.get(edge.evidence_event_id))
      .filter((event): event is EventRecord => Boolean(event));
    const hasResolved = events.some((event) => RESOLVED_STATUS_RE.test(statusText(event)));
    const hasBlocked =
      events.some((event) => BLOCKED_STATUS_RE.test(statusText(event))) || edges.length > 0;
    const labelPrefix =
      hasResolved && hasBlocked
        ? "Historical/resolved blocker"
        : hasBlocked
          ? "Current blocker"
          : "Blocker context";
    return groupFromEdges({
      queryClass: params.queryClass,
      groupType: "blocker",
      edges: allEdges,
      events,
      anchorEntityId: edges[0]?.src_entity_id,
      relation: "blocks",
      targetEntityIds: [target],
      label: `${labelPrefix}: ${edges[0]?.dst_name ?? target}`,
      freshness: params.freshness.groupFreshness(allEdges, events),
      main: true,
    });
  });
  return sortGroups(groups);
}

function buildWeakGroups(params: {
  queryClass: QueryClass;
  edges: EdgeRow[];
  eventsById: Map<string, EventRecord>;
  freshness: ReturnType<typeof buildFreshnessContext>;
  limit: number;
}): EvidenceGroup[] {
  return buildListGroups({
    queryClass: params.queryClass,
    edges: params.edges,
    eventsById: params.eventsById,
    freshness: params.freshness,
  })
    .map((group) => ({ ...group, is_main_evidence: false }))
    .slice(0, params.limit);
}

function fallbackScore(ftsScore: number | undefined): number {
  if (typeof ftsScore !== "number" || !Number.isFinite(ftsScore)) {
    return 0.45;
  }
  return Math.max(0.1, Math.min(1, 1 / (1 + Math.abs(ftsScore))));
}

async function buildFallbackHits(
  store: CanonicalStore,
  query: string,
  limit: number,
): Promise<GraphHit[]> {
  const rows = await store.searchEvents(query, Math.max(1, limit * 4));
  const hits: GraphHit[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const state = await store.getEntityState(row.entity_id);
    if (state) {
      const key = `${row.entity_id}:state`;
      if (!seen.has(key)) {
        seen.add(key);
        hits.push({
          type: "state",
          entity_id: row.entity_id,
          source_ref: row.source_ref,
          snippet_structured: {
            ...state,
            planner: "fts_fallback",
            group_type: "state",
          },
          score: fallbackScore(row.fts_score),
        });
      }
    }
    const key = `${row.event_id}:event`;
    if (!seen.has(key)) {
      seen.add(key);
      hits.push({
        type: "event",
        entity_id: row.entity_id,
        source_ref: row.source_ref,
        snippet_structured: {
          ...row,
          planner: "fts_fallback",
        },
        score: fallbackScore(row.fts_score),
      });
    }
    if (hits.length >= limit) {
      break;
    }
  }
  return hits.slice(0, limit);
}

function shouldFallback(params: {
  groups: EvidenceGroup[];
  resolutionStatus: ResolutionStatus;
  budget: Record<string, number>;
}): string[] {
  const reasons: string[] = [];
  if (params.groups.length < Math.min(1, params.budget.main)) {
    reasons.push("groups_insufficient");
  }
  if (
    params.groups.length > 0 &&
    params.groups.every((group) => group.freshness === "stale" || group.freshness === "unknown")
  ) {
    reasons.push("top_groups_stale_or_unknown");
  }
  if (params.groups.some((group) => group.evidence_event_ids.length === 0)) {
    reasons.push("supporting_events_missing");
  }
  if (params.resolutionStatus !== "stable") {
    reasons.push(`resolution_${params.resolutionStatus}`);
  }
  return reasons;
}

function selectMainGroups(
  groups: EvidenceGroup[],
  budget: Record<string, number>,
): EvidenceGroup[] {
  const strongFreshMixed = groups.filter(
    (group) =>
      group.is_main_evidence &&
      group.freshness !== "unknown" &&
      group.freshness !== "stale" &&
      group.relation !== "about" &&
      group.relation !== "mentions" &&
      group.relation !== "related_to",
  );
  const strongUnknown = groups.filter(
    (group) => group.is_main_evidence && group.freshness === "unknown",
  );
  const strongStale = groups.filter(
    (group) => group.is_main_evidence && group.freshness === "stale",
  );
  return [
    ...sortGroups(strongFreshMixed),
    ...sortGroups(strongUnknown),
    ...sortGroups(strongStale),
  ].slice(0, budget.main);
}

function groupToHit(group: EvidenceGroup, queryClass: QueryClass): GraphHit | null {
  if (!group.source_ref) {
    return null;
  }
  return {
    type: group.group_type === "state" ? "state" : "edge",
    entity_id: group.anchor_entity_id ?? group.target_entity_ids?.[0] ?? "graph_group",
    source_ref: group.source_ref,
    snippet_structured: {
      group_type: group.group_type,
      evidence_group: group,
      query_class: queryClass,
      planner: `${queryClass}_planner`,
      graph_freshness: group.freshness,
      relation: group.relation,
      occurred_at: group.last_seen_at,
    },
    score: groupRank(group),
  };
}

function mergeFinalHits(params: {
  queryClass: QueryClass;
  mainGroups: EvidenceGroup[];
  conflictGroups: EvidenceGroup[];
  weakGroups: EvidenceGroup[];
  fallbackHits: GraphHit[];
  budget: Record<string, number>;
  limit: number;
}): { hits: GraphHit[]; finalGroupIds: string[] } {
  const hits: GraphHit[] = [];
  const finalGroupIds: string[] = [];
  const addGroup = (group: EvidenceGroup) => {
    const hit = groupToHit(group, params.queryClass);
    if (!hit) {
      return;
    }
    hits.push(hit);
    finalGroupIds.push(group.group_id);
  };
  for (const group of params.mainGroups) {
    addGroup(group);
    const attachedConflict = params.conflictGroups.find(
      (conflict) =>
        conflict.anchor_entity_id === group.anchor_entity_id ||
        (conflict.relation && conflict.relation === group.relation),
    );
    if (
      attachedConflict &&
      finalGroupIds.filter((id) => id.includes(":conflict:")).length < params.budget.conflict
    ) {
      addGroup(attachedConflict);
    }
  }
  for (const hit of params.fallbackHits.slice(0, params.budget.fallback)) {
    hits.push(hit);
  }
  for (const group of params.weakGroups.slice(0, params.budget.weak)) {
    addGroup(group);
  }
  return {
    hits: hits.slice(0, Math.min(params.limit, params.budget.total)),
    finalGroupIds: finalGroupIds.slice(0, Math.min(params.limit, params.budget.total)),
  };
}

export async function buildPlannerResult(params: {
  store: CanonicalStore;
  query: string;
  limit: number;
}): Promise<PlannerResult> {
  const queryClass = classifyGraphQuery(params.query);
  const budget = budgetForClass(queryClass, Math.max(1, params.limit));
  const resolution = resolveEntities(params.store, params.query, queryClass);
  const relations = relationsForClass(queryClass);
  const strongEdges =
    resolution.status === "stable" && resolution.entityIds.length > 0
      ? params.store.searchGraphEdges({
          entityIds: resolution.entityIds,
          relations,
          includeWeak: false,
          limit: 64,
        })
      : [];
  const weakEdges =
    resolution.status === "stable" && resolution.entityIds.length > 0
      ? params.store.searchGraphEdges({
          entityIds: resolution.entityIds,
          relations: [...WEAK_GRAPH_RELATIONS],
          includeWeak: true,
          limit: budget.weak * 4,
        })
      : [];
  const allEdgeEventIds = [
    ...new Set([...strongEdges, ...weakEdges].map((edge) => edge.evidence_event_id)),
  ];
  const events = params.store.getEventsByIds(allEdgeEventIds);
  const eventsById = new Map(events.map((event) => [event.event_id, event]));
  const freshness = buildFreshnessContext(params.store, [...strongEdges, ...weakEdges], events);
  const conflictGroups = detectConflictGroups({
    queryClass,
    edges: strongEdges,
    events,
    freshness,
  }).slice(0, budget.conflict);
  const mainCandidates =
    queryClass === "state"
      ? buildStateGroups({
          store: params.store,
          queryClass,
          entityIds: resolution.entityIds,
          edges: strongEdges,
          events,
          freshness,
        })
      : queryClass === "list"
        ? buildListGroups({ queryClass, edges: strongEdges, eventsById, freshness })
        : queryClass === "timeline"
          ? buildTimelineGroups({ queryClass, edges: strongEdges, eventsById, freshness })
          : buildBlockerGroups({ queryClass, edges: strongEdges, eventsById, freshness });
  const selectedMain = markConflicts(selectMainGroups(mainCandidates, budget), conflictGroups);
  const weakGroups =
    selectedMain.length < budget.main
      ? buildWeakGroups({ queryClass, edges: weakEdges, eventsById, freshness, limit: budget.weak })
      : [];
  const fallbackReason = shouldFallback({
    groups: selectedMain,
    resolutionStatus: resolution.status,
    budget,
  });
  const fallbackHits =
    fallbackReason.length > 0
      ? await buildFallbackHits(params.store, params.query, budget.fallback)
      : [];
  const merged = mergeFinalHits({
    queryClass,
    mainGroups: selectedMain,
    conflictGroups,
    weakGroups,
    fallbackHits,
    budget,
    limit: params.limit,
  });
  return {
    query_class: queryClass,
    resolved_entity_ids: resolution.entityIds,
    resolution_status: resolution.status,
    resolution_candidates: resolution.candidates.map((candidate) => ({
      entity_id: candidate.entity_id,
      entity_type: candidate.entity_type,
      canonical_name: candidate.canonical_name,
      match_kind: candidate.match_kind,
      confidence: candidate.confidence,
    })),
    main_groups: selectedMain,
    conflict_groups: conflictGroups,
    weak_edge_expansions: weakGroups,
    fallback_hits: fallbackHits,
    freshness_decisions: freshness.freshnessDecisions,
    final_group_ids: merged.finalGroupIds,
    fallback_reason: fallbackReason.length > 0 ? fallbackReason : undefined,
    group_budget: budget,
  };
}

export function plannerResultToHits(result: PlannerResult, limit: number): GraphHit[] {
  const budget = result.group_budget;
  const merged = mergeFinalHits({
    queryClass: result.query_class,
    mainGroups: result.main_groups,
    conflictGroups: result.conflict_groups,
    weakGroups: result.weak_edge_expansions,
    fallbackHits: result.fallback_hits,
    budget,
    limit,
  });
  result.final_group_ids = merged.finalGroupIds;
  return merged.hits;
}

export function plannerResultToTraceSearch(result: PlannerResult): Record<string, unknown> {
  return {
    query_class: result.query_class,
    resolved_entity_ids: result.resolved_entity_ids,
    resolution_status: result.resolution_status,
    resolution_candidates: result.resolution_candidates,
    strong_edge_groups: result.main_groups.map((group) => ({
      group_id: group.group_id,
      group_type: group.group_type,
      relation: group.relation,
      anchor_entity_id: group.anchor_entity_id,
      target_entity_ids: group.target_entity_ids,
      evidence_edge_ids: group.evidence_edge_ids,
      evidence_event_ids: group.evidence_event_ids,
      freshness: group.freshness,
      confidence: group.confidence,
      has_conflict: group.has_conflict,
    })),
    weak_edge_expansions: result.weak_edge_expansions.map((group) => ({
      group_id: group.group_id,
      relation: group.relation,
      freshness: group.freshness,
      confidence: group.confidence,
    })),
    freshness_decisions: result.freshness_decisions,
    conflict_groups: result.conflict_groups.map((group) => ({
      group_id: group.group_id,
      conflict_type: group.conflict_type,
      relation: group.relation,
      evidence_edge_ids: group.evidence_edge_ids,
      evidence_event_ids: group.evidence_event_ids,
      freshness: group.freshness,
    })),
    final_group_ids: result.final_group_ids,
    fallback_reason: result.fallback_reason,
    fallback_count: result.fallback_hits.length,
    group_budget: result.group_budget,
  };
}
