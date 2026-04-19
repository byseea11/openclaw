import fs from "node:fs/promises";
import path from "node:path";
import {
  createSubsystemLogger,
  resolveAgentWorkspaceDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { bootstrapCanonicalIndex } from "./bootstrap.js";
import { canonicalize } from "./canonicalizer.js";
import { parseGraphJsonBlockWithStatus } from "./extractor.js";
import {
  drainPendingGraphUpdates,
  handleGraphAfterTurn,
  handleGraphBeforeCompaction,
} from "./projection.js";
import { graphHitToMemorySearchResult, type GraphMemorySearchResult } from "./prompt.js";
import { plannerResultToTraceSearch } from "./retriever-groups.js";
import { search_graph_with_plan } from "./retriever.js";
import {
  describeGraphIndexConfig,
  EXTRACTOR_VERSION,
  GRAPH_PROJECTION_VERSION,
  GRAPH_METRIC_KEYS,
  type GraphMetricsSnapshot,
  parseSourceRef,
  resolveGraphIndexConfig,
  type RawEvent,
  type SourceRefValidationResult,
} from "./schema.js";
import { getCanonicalStore } from "./store.js";
import { buildGraphTraceId, recordGraphIndexTrace } from "./trace.js";
import {
  markGraphHitsUsedFromAssistantTexts,
  markGraphHitsUsedFromMemoryGet,
  recordReturnedGraphHits,
} from "./usage.js";

const log = createSubsystemLogger("memory");

function isAllowedFlushMemoryPath(sourcePath: string): boolean {
  return sourcePath === "MEMORY.md" || /^memory\/\d{4}-\d{2}-\d{2}\.md$/.test(sourcePath);
}

async function validateSourceRefForWorkspace(
  sourceRef: string,
  workspaceDir: string | undefined,
): Promise<SourceRefValidationResult> {
  const parsed = parseSourceRef(sourceRef);
  if (!parsed) {
    return { ok: false, reason: "invalid_syntax", sourceRef };
  }
  if (!isAllowedFlushMemoryPath(parsed.path)) {
    return { ok: false, reason: "not_memory_source", sourceRef };
  }
  if (!workspaceDir?.trim()) {
    return { ok: false, reason: "file_missing", sourceRef };
  }
  const workspaceRoot = path.resolve(workspaceDir);
  const fullPath = path.resolve(workspaceRoot, parsed.path);
  if (!fullPath.startsWith(`${workspaceRoot}${path.sep}`) && fullPath !== workspaceRoot) {
    return { ok: false, reason: "unsafe_path", sourceRef };
  }
  let text: string;
  try {
    text = await fs.readFile(fullPath, "utf8");
  } catch {
    return { ok: false, reason: "file_missing", sourceRef };
  }
  const totalLines = text.split(/\r?\n/).length;
  if (parsed.startLine > totalLines || parsed.endLine > totalLines) {
    return { ok: false, reason: "line_range", sourceRef, totalLines };
  }
  return { ok: true, ...parsed, totalLines };
}

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
export { canonicalize, canonicalizeEntityId, createEventId } from "./canonicalizer.js";
export { deriveGraphObjects, normalizeEntityAlias } from "./kg.js";
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
export { reduce } from "./reducer.js";
export { search_graph, search_graph_with_plan } from "./retriever.js";
export { plannerResultToTraceSearch } from "./retriever-groups.js";
export {
  __testing as canonicalUsageTesting,
  markGraphHitsUsedFromAssistantTexts,
  markGraphHitsUsedFromMemoryGet,
  recordReturnedGraphHits,
} from "./usage.js";
export {
  describeGraphIndexConfig,
  EXTRACTOR_VERSION,
  parseSourceRef,
  resolveGraphIndexConfig,
  type EntityState,
  type EventRecord,
  type GraphHit,
  type GraphIndexConfig,
  type RawEvent,
} from "./schema.js";
export { CanonicalStore, closeAllCanonicalStores, getCanonicalStore } from "./store.js";

export async function handleGraphFlushResult(params: {
  cfg: OpenClawConfig;
  agentId: string;
  outputText: string;
}): Promise<{ parsedEvents: number; persistedEvents: number }> {
  try {
    const graphConfig = resolveGraphIndexConfig(params.cfg);
    if (!graphConfig.enabled || !graphConfig.extractDuringFlush) {
      log.info("canonical.flush.skip_disabled");
      return { parsedEvents: 0, persistedEvents: 0 };
    }
    const parseStartedAt = Date.now();
    const parsed = parseGraphJsonBlockWithStatus(params.outputText);
    const parseDurationMs = Date.now() - parseStartedAt;
    const store = getCanonicalStore(params.agentId);
    store.recordExtractorLatency(parseDurationMs);
    store.bumpMetric(parsed.ok ? "extractSuccesses" : "extractFailures", 1);
    const workspaceDir = resolveAgentWorkspaceDir(params.cfg, params.agentId);
    const rawEvents: RawEvent[] = [];
    for (const event of parsed.events) {
      const validation = await validateSourceRefForWorkspace(event.source_ref, workspaceDir);
      if (validation.ok) {
        store.bumpMetric("sourceRefValidated", 1);
        rawEvents.push(event);
        continue;
      }
      store.bumpMetric("sourceRefRejected", 1);
      log.warn(
        `[canonical] source_ref.rejected reason=${validation.reason} source_ref=${event.source_ref}`,
      );
    }
    log.info(`canonical.flush.parsed events=${rawEvents.length}`);
    if (rawEvents.length === 0) {
      return { parsedEvents: 0, persistedEvents: 0 };
    }
    const records = canonicalize(rawEvents, EXTRACTOR_VERSION);
    const persisted = await store.persistCanonicalBatch(records);
    log.info(`canonical.flush.persisted records=${records.length}`);
    recordGraphIndexTrace({
      cfg: params.cfg,
      message: "canonical.flush.kg_persisted",
      summary: `records=${records.length} entities=${persisted.graphObjects.entities.length} edges=${persisted.graphObjects.edges.length}`,
      event: {
        trace_id: buildGraphTraceId(["flush", records[0]?.event_id, "kg_persisted"]),
        stage: "kg_objects_derived",
        source_kind: "flush",
        tables: {
          canonical_entities: {
            table: "canonical_entities",
            persisted: persisted.graphObjects.entities.length,
          },
          entity_aliases: {
            table: "entity_aliases",
            persisted: persisted.graphObjects.aliases.length,
          },
          graph_edges: {
            table: "graph_edges",
            persisted: persisted.graphObjects.edges.length,
          },
        },
      },
    });
    return { parsedEvents: rawEvents.length, persistedEvents: records.length };
  } catch (err) {
    log.warn(`[canonical] flush.fallback error=${String(err)}`);
    return { parsedEvents: 0, persistedEvents: 0 };
  }
}

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

export async function backfillGraphObjectsFromEvents(params: {
  agentId: string;
  scope?: string;
  batchSize?: number;
}) {
  const store = getCanonicalStore(params.agentId);
  return await store.backfillGraphObjectsFromEvents({
    scope: params.scope,
    batchSize: params.batchSize,
  });
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
    const { hits, plannerResult } = await search_graph_with_plan(
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
          ...(plannerResult ? plannerResultToTraceSearch(plannerResult) : {}),
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
          steps: ["search_graph", "recordReturnedGraphHits", "graphHitToMemorySearchResult"],
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
