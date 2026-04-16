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

export async function search_graph(
  store: CanonicalStore,
  query: string,
  k: number,
): Promise<GraphHit[]> {
  const limit = Math.max(1, k);
  const rows = await store.searchEvents(query, limit * 2);
  const seen = new Set<string>();
  const hits: GraphHit[] = [];
  for (const row of rows) {
    if (seen.has(row.entity_id)) {
      continue;
    }
    seen.add(row.entity_id);
    const score = scoreFromFts(row.fts_score);
    const state = await store.getEntityState(row.entity_id);
    if (state) {
      hits.push({
        type: "state",
        entity_id: row.entity_id,
        source_ref: row.source_ref,
        snippet_structured: state,
        score,
      });
    }
    hits.push({
      type: "event",
      entity_id: row.entity_id,
      source_ref: row.source_ref,
      snippet_structured: row,
      score,
    });
    if (hits.length >= limit) {
      break;
    }
  }
  const sliced = hits.slice(0, limit);
  log.info(`canonical.search query=${query} k=${limit} hits=${sliced.length}`);
  return sliced;
}
