import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { bootstrapCanonicalIndex } from "./bootstrap.js";
import {
  drainPendingGraphUpdates,
  handleGraphAfterTurn,
  handleGraphBeforeCompaction,
} from "./projection.js";
import { graphHitToMemorySearchResult, type GraphMemorySearchResult } from "./prompt.js";
import { searchGraphV2 } from "./query-v2.js";
import {
  describeGraphIndexConfig,
  EXTRACTOR_VERSION,
  GRAPH_PROJECTION_VERSION,
  GRAPH_METRIC_KEYS,
  type GraphMetricsSnapshot,
  resolveGraphIndexConfig,
} from "./schema.js";
import { getCanonicalStore } from "./store.js";
import { buildGraphTraceId, recordGraphIndexTrace } from "./trace.js";
import {
  markGraphHitsUsedFromAssistantTexts,
  markGraphHitsUsedFromMemoryGet,
  recordReturnedGraphHits,
} from "./usage.js";

const log = createSubsystemLogger("memory");

function emptyGraphMetrics(): GraphMetricsSnapshot {
  const base = Object.fromEntries(GRAPH_METRIC_KEYS.map((key) => [key, 0])) as Record<
    (typeof GRAPH_METRIC_KEYS)[number],
    number
  >;
  return {
    ...base,
    hitsUsed: 0,
    extractLatencyMsAvg: 0,
  };
}

export { bootstrapCanonicalIndex } from "./bootstrap.js";
export { bootstrapCanonicalIndex as rebuildGraphIndex } from "./bootstrap.js";
export { canonicalizeV2 } from "./canonicalizer-v2.js";
export {
  extract,
  parseGraphJsonBlock,
  setDefaultExtractorClient,
  type LLMClient as CanonicalExtractorClient,
} from "./extractor.js";
export { createSubagentExtractorClient, isGraphExtractorSessionKey } from "./extractor.runtime.js";
export { graphHitToMemorySearchResult, renderGraphHit } from "./prompt.js";
export {
  drainPendingGraphUpdates,
  handleGraphAfterTurn,
  handleGraphBeforeCompaction,
} from "./projection.js";
export { classifyQueryV2, resolveEntityRefV2, searchGraphV2 } from "./query-v2.js";
export {
  __testing as canonicalUsageTesting,
  markGraphHitsUsedFromAssistantTexts,
  markGraphHitsUsedFromMemoryGet,
  recordReturnedGraphHits,
} from "./usage.js";
export {
  describeGraphIndexConfig,
  EXTRACTOR_VERSION,
  resolveGraphIndexConfig,
  type GraphHit,
  type GraphIndexConfig,
  type RawEvent,
} from "./schema.js";
export { CanonicalStore, closeAllCanonicalStores, getCanonicalStore } from "./store.js";

export async function maybeBootstrapCanonicalIndex(params: {
  cfg: OpenClawConfig;
  agentId: string;
  workspaceDir?: string;
  force?: boolean;
  progress?: (update: { completed: number; total: number; label?: string }) => void;
}) {
  try {
    const graphConfig = resolveGraphIndexConfig(params.cfg);
    if (!graphConfig.enabled || !graphConfig.bootstrapOnStart || !params.workspaceDir) {
      return null;
    }
    const store = getCanonicalStore(params.agentId);
    const status = store.getStatus();
    const shouldBootstrap =
      params.force ||
      status.schemaVersion !== describeGraphIndexConfig(params.cfg).schemaVersion ||
      status.extractorVersion !== EXTRACTOR_VERSION ||
      status.projectionVersion !== GRAPH_PROJECTION_VERSION;
    if (!shouldBootstrap) {
      return null;
    }
    return await bootstrapCanonicalIndex({
      cfg: params.cfg,
      agentId: params.agentId,
      workspaceDir: params.workspaceDir,
      force: params.force,
      progress: params.progress,
    });
  } catch (err) {
    log.warn(`[canonical] bootstrap.fallback error=${String(err)}`);
    return null;
  }
}

export async function searchGraphForMemoryTool(params: {
  cfg: OpenClawConfig;
  agentId: string;
  query: string;
  maxResults?: number;
  sessionKey?: string;
}): Promise<{
  enabled: boolean;
  hits: number;
  renderedHits: number;
  results: GraphMemorySearchResult[];
}> {
  try {
    const graphConfig = resolveGraphIndexConfig(params.cfg);
    if (!graphConfig.enabled) {
      return { enabled: false, hits: 0, renderedHits: 0, results: [] };
    }
    const store = getCanonicalStore(params.agentId);
    if (store.hasPendingProjection(params.sessionKey)) {
      const summary = store.listPendingProjectionSummaries(params.sessionKey)[0];
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.memory_search.pending_drain",
        summary: `source=${params.sessionKey ?? ""} query=${JSON.stringify(params.query)}`,
        event: {
          trace_id: buildGraphTraceId([
            params.sessionKey,
            summary?.first_entry_id,
            summary?.last_entry_id,
            "memory_search_pending_drain",
          ]),
          stage: "memory_search_pending_drain",
          source_kind: "transcript",
          source_id: params.sessionKey,
          entry_range: {
            first: summary?.first_entry_id,
            last: summary?.last_entry_id,
          },
          search: {
            query: params.query,
            pending_spans: summary?.pending_spans ?? 0,
          },
          call: {
            function: "searchGraphForMemoryTool",
            steps: ["hasPendingProjection", "drainPendingGraphUpdates"],
          },
        },
      });
      await drainPendingGraphUpdates({
        cfg: params.cfg,
        agentId: params.agentId,
        sourceId: params.sessionKey,
        reason: "recall",
      });
    }
    const { hits, queryClass, resolvedRef } = await searchGraphV2(
      store,
      params.query,
      Math.max(1, params.maxResults ?? 5),
    );
    if (params.sessionKey) {
      await recordReturnedGraphHits({
        cfg: params.cfg,
        agentId: params.agentId,
        sessionKey: params.sessionKey,
        query: params.query,
        hits,
      });
    }
    const results: GraphMemorySearchResult[] = [];
    for (const hit of hits) {
      const rendered = graphHitToMemorySearchResult(hit);
      if (!rendered) {
        log.warn(`canonical.render.invalid_source_ref source_ref=${hit.source_ref}`);
        continue;
      }
      results.push(rendered);
    }
    recordGraphIndexTrace({
      cfg: params.cfg,
      message: "canonical.memory_search.graph_hits",
      summary: `query=${JSON.stringify(params.query)} hits=${hits.length} rendered=${results.length}`,
      event: {
        trace_id: buildGraphTraceId([params.sessionKey, params.query, "memory_search_graph_hits"]),
        stage: "memory_search_graph_hits",
        source_kind: params.sessionKey ? "transcript" : undefined,
        source_id: params.sessionKey,
        search: {
          query: params.query,
          hits: hits.length,
          rendered: results.length,
          query_class: queryClass,
          resolved_ref: resolvedRef,
          strong_edge_hits: hits.filter((hit) => hit.type === "edge").length,
          weak_edge_hits: hits.filter((hit) => {
            if (hit.type !== "edge" || typeof hit.snippet_structured.relation !== "string") {
              return false;
            }
            return ["about", "mentions", "related_to"].includes(hit.snippet_structured.relation);
          }).length,
          graph_results: results.map((result) => ({
            path: result.path,
            startLine: result.startLine,
            endLine: result.endLine,
            corpus: result.corpus,
            graphMeta: result.graphMeta,
            snippet: result.snippet,
          })),
        },
        call: {
          function: "searchGraphForMemoryTool",
          steps: ["searchGraphV2", "recordReturnedGraphHits", "graphHitToMemorySearchResult"],
        },
      },
    });
    return {
      enabled: true,
      hits: hits.length,
      renderedHits: results.length,
      results,
    };
  } catch (err) {
    log.warn(`[canonical] memory_search.fallback error=${String(err)}`);
    return { enabled: false, hits: 0, renderedHits: 0, results: [] };
  }
}

export function getCanonicalStatus(params: { cfg?: OpenClawConfig; agentId: string }) {
  try {
    const store = getCanonicalStore(params.agentId);
    return {
      ...describeGraphIndexConfig(params.cfg),
      ...store.getStatus(),
    };
  } catch (err) {
    log.warn(`[canonical] status.fallback error=${String(err)}`);
    return {
      ...describeGraphIndexConfig(params.cfg),
      dbPath: "",
      eventsTotal: 0,
      entitiesTotal: 0,
      metrics: emptyGraphMetrics(),
    };
  }
}

export async function noteGraphUsageFromMemoryGet(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sessionKey?: string;
  path: string;
  from?: number;
  lines?: number;
}): Promise<void> {
  try {
    await markGraphHitsUsedFromMemoryGet(params);
  } catch (err) {
    log.warn(`[canonical] usage.memory_get.fallback error=${String(err)}`);
  }
}

export async function noteGraphUsageFromAssistantOutput(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sessionKey?: string;
  assistantTexts: string[];
}): Promise<void> {
  try {
    await markGraphHitsUsedFromAssistantTexts(params);
  } catch (err) {
    log.warn(`[canonical] usage.llm_output.fallback error=${String(err)}`);
  }
}
