import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { GraphHit } from "./schema.js";
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

export async function search_graph(
  store: CanonicalStore,
  query: string,
  k: number,
): Promise<GraphHit[]> {
  const limit = Math.max(1, k);
  const rows = await store.searchEvents(query, limit * 4);
  const rankedRows = rows
    .map((row) => ({
      row,
      score: scoreFromFts(row.fts_score) * 0.7 + scoreRecency(row.occurred_at, row.created_at) * 0.3,
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
  const entityTypeSeen = new Set<string>();
  const hits: GraphHit[] = [];
  for (const { row, score } of rankedRows) {
    const state = await store.getEntityState(row.entity_id);
    const stateKey = `${row.entity_id}:state`;
    if (state && !entityTypeSeen.has(stateKey)) {
      entityTypeSeen.add(stateKey);
      hits.push({
        type: "state",
        entity_id: row.entity_id,
        source_ref: row.source_ref,
        snippet_structured: state,
        score,
      });
    }
    const eventKey = `${row.entity_id}:event`;
    if (!entityTypeSeen.has(eventKey)) {
      entityTypeSeen.add(eventKey);
      hits.push({
        type: "event",
        entity_id: row.entity_id,
        source_ref: row.source_ref,
        snippet_structured: row,
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
