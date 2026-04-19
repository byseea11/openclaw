import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import {
  buildPlannerResult,
  isP1aGraphRecallEnabled,
  plannerResultToHits,
  type PlannerResult,
} from "./retriever-groups.js";
import { STRONG_GRAPH_RELATIONS, type GraphHit } from "./schema.js";
import type { CanonicalStore } from "./store.js";

const log = createSubsystemLogger("memory");

function scoreFromFts(ftsScore: number | undefined): number {
  if (typeof ftsScore !== "number" || !Number.isFinite(ftsScore)) {
    return 0.5;
  }
  return Math.max(0.1, Math.min(1, 1 / (1 + Math.abs(ftsScore))));
}

function scoreRecency(occurredAt: string, createdAt: number): number {
  const timestamp = Date.parse(occurredAt);
  const effectiveMs = Number.isFinite(timestamp) ? timestamp : createdAt;
  if (!Number.isFinite(effectiveMs)) {
    return 0.4;
  }
  const ageDays = Math.max(0, (Date.now() - effectiveMs) / (24 * 60 * 60 * 1000));
  return Math.max(0.2, 1 / (1 + ageDays / 30));
}

type QueryClass = "state" | "list" | "timeline" | "blocker_why";

function classifyQuery(query: string): QueryClass {
  if (/(why|blocked|blocker|blocking|depends|dependency|卡|为什么|原因|依赖)/i.test(query)) {
    return "blocker_why";
  }
  if (/(when|timeline|history|change|changed|变化|历史|什么时候|何时)/i.test(query)) {
    return "timeline";
  }
  if (/(list|show all|which|有哪些|列出|所有)/i.test(query)) {
    return "list";
  }
  if (/(status|owner|assignee|responsible|who|现在|状态|负责人|谁)/i.test(query)) {
    return "state";
  }
  return "state";
}

function relationsForClass(queryClass: QueryClass): string[] {
  switch (queryClass) {
    case "blocker_why":
      return ["blocks", "depends_on", "owned_by", "decided_by"];
    case "timeline":
      return [...STRONG_GRAPH_RELATIONS];
    case "list":
      return [...STRONG_GRAPH_RELATIONS];
    case "state":
      return ["owned_by", "assigned_to", "blocks", "decided_by", "scheduled_for"];
    default:
      return ["owned_by", "assigned_to", "blocks", "decided_by", "scheduled_for"];
  }
}

function freshnessForStore(store: CanonicalStore) {
  const states = store.listProjectionStates();
  const staleSources = states
    .filter((state) => state.status === "dirty" || state.status === "failed")
    .map((state) => ({
      source_id: state.source_id,
      status: state.status,
      last_projected_at: state.last_projected_at,
    }));
  return {
    scope: "store",
    stale_sources: staleSources,
    graph_freshness: staleSources.length === 0 ? "fresh" : "partially_stale",
  };
}

async function searchGraphLegacy(
  store: CanonicalStore,
  query: string,
  k: number,
): Promise<GraphHit[]> {
  const limit = Math.max(1, k);
  const queryClass = classifyQuery(query);
  const freshness = freshnessForStore(store);
  const entityIds = store.resolveEntityIds(query, 8);
  const edgeRows =
    entityIds.length > 0
      ? store.searchGraphEdges({
          entityIds,
          relations: relationsForClass(queryClass),
          includeWeak: false,
          limit: limit * 3,
        })
      : [];
  const hits: GraphHit[] = [];
  const seen = new Set<string>();
  for (const edge of edgeRows) {
    if (seen.has(edge.edge_id)) {
      continue;
    }
    seen.add(edge.edge_id);
    hits.push({
      type: "edge",
      entity_id: edge.src_entity_id,
      source_ref: edge.source_ref,
      snippet_structured: {
        ...edge,
        query_class: queryClass,
        planner: `${queryClass}_planner`,
        scope: freshness.scope,
        stale_sources: freshness.stale_sources,
        graph_freshness: freshness.graph_freshness,
      },
      score: edge.confidence * 0.7 + scoreRecency(edge.occurred_at, edge.created_at) * 0.3,
    });
    if (hits.length >= limit) {
      break;
    }
  }
  const rows = await store.searchEvents(query, limit * 4);
  const rankedRows = rows
    .map((row) => ({
      row,
      score:
        scoreFromFts(row.fts_score) * 0.7 + scoreRecency(row.occurred_at, row.created_at) * 0.3,
    }))
    .toSorted((left, right) => {
      if (left.score !== right.score) {
        return right.score - left.score;
      }
      if (left.row.occurred_at !== right.row.occurred_at) {
        return right.row.occurred_at.localeCompare(left.row.occurred_at);
      }
      return right.row.created_at - left.row.created_at;
    });
  for (const { row, score } of rankedRows) {
    const state = await store.getEntityState(row.entity_id);
    const stateKey = `${row.entity_id}:state`;
    if (state && !seen.has(stateKey)) {
      seen.add(stateKey);
      hits.push({
        type: "state",
        entity_id: row.entity_id,
        source_ref: row.source_ref,
        snippet_structured: {
          ...state,
          query_class: queryClass,
          planner: `${queryClass}_planner`,
          scope: freshness.scope,
          stale_sources: freshness.stale_sources,
          graph_freshness: freshness.graph_freshness,
        },
        score,
      });
    }
    const eventKey = `${row.entity_id}:event`;
    if (!seen.has(eventKey)) {
      seen.add(eventKey);
      hits.push({
        type: "event",
        entity_id: row.entity_id,
        source_ref: row.source_ref,
        snippet_structured: {
          ...row,
          query_class: queryClass,
          planner: `${queryClass}_planner`,
          scope: freshness.scope,
          stale_sources: freshness.stale_sources,
          graph_freshness: freshness.graph_freshness,
        },
        score,
      });
    }
    if (hits.length >= limit) {
      break;
    }
  }
  const sliced = hits.slice(0, limit);
  log.info(`canonical.search query=${query} k=${limit} hits=${sliced.length}`);
  return sliced;
}

export async function search_graph_with_plan(
  store: CanonicalStore,
  query: string,
  k: number,
): Promise<{ hits: GraphHit[]; plannerResult: PlannerResult | null }> {
  if (!isP1aGraphRecallEnabled()) {
    return {
      hits: await searchGraphLegacy(store, query, k),
      plannerResult: null,
    };
  }
  const limit = Math.max(1, k);
  const plannerResult = await buildPlannerResult({ store, query, limit });
  const hits = plannerResultToHits(plannerResult, limit);
  log.info(
    `canonical.search.p1a query=${query} k=${limit} class=${plannerResult.query_class} groups=${plannerResult.final_group_ids.length} hits=${hits.length}`,
  );
  return { hits, plannerResult };
}

export async function search_graph(
  store: CanonicalStore,
  query: string,
  k: number,
): Promise<GraphHit[]> {
  return (await search_graph_with_plan(store, query, k)).hits;
}
