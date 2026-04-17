import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { bootstrapCanonicalIndex } from "./bootstrap.js";
import { canonicalize } from "./canonicalizer.js";
import { parseGraphJsonBlock, parseGraphJsonBlockWithStatus } from "./extractor.js";
import { graphHitToMemorySearchResult, type GraphMemorySearchResult } from "./prompt.js";
import { search_graph } from "./retriever.js";
import {
  describeGraphIndexConfig,
  EXTRACTOR_VERSION,
  parseSourceRef,
  resolveGraphIndexConfig,
} from "./schema.js";
import { getCanonicalStore } from "./store.js";
import {
  markGraphHitsUsedFromAssistantTexts,
  markGraphHitsUsedFromMemoryGet,
  recordReturnedGraphHits,
} from "./usage.js";

const log = createSubsystemLogger("memory");

export { bootstrapCanonicalIndex } from "./bootstrap.js";
export { canonicalize, canonicalizeEntityId, createEventId } from "./canonicalizer.js";
export { extract, parseGraphJsonBlock } from "./extractor.js";
export { graphHitToMemorySearchResult, renderGraphHit } from "./prompt.js";
export { reduce } from "./reducer.js";
export { search_graph } from "./retriever.js";
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
  const rawEvents = parsed.events.filter((event) => {
    const parsedSourceRef = parseSourceRef(event.source_ref);
    if (parsedSourceRef) {
      return true;
    }
    log.warn(`canonical.flush.invalid_source_ref source_ref=${event.source_ref}`);
    return false;
  });
  log.info(`canonical.flush.parsed events=${rawEvents.length}`);
  if (rawEvents.length === 0) {
    return { parsedEvents: 0, persistedEvents: 0 };
  }
  const records = canonicalize(rawEvents, EXTRACTOR_VERSION);
  store.setMeta("extractor_version", EXTRACTOR_VERSION);
  await store.upsertEvents(records);
  await store.refreshEntityStates(records);
  log.info(`canonical.flush.persisted records=${records.length}`);
  return { parsedEvents: rawEvents.length, persistedEvents: records.length };
}

export async function maybeBootstrapCanonicalIndex(params: {
  cfg: OpenClawConfig;
  agentId: string;
  workspaceDir?: string;
  force?: boolean;
  progress?: (update: { completed: number; total: number; label?: string }) => void;
}) {
  const graphConfig = resolveGraphIndexConfig(params.cfg);
  if (!graphConfig.enabled || !graphConfig.bootstrapOnStart || !params.workspaceDir) {
    return null;
  }
  const store = getCanonicalStore(params.agentId);
  const status = store.getStatus();
  const shouldBootstrap =
    params.force || status.eventsTotal === 0 || status.extractorVersion !== EXTRACTOR_VERSION;
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
  const graphConfig = resolveGraphIndexConfig(params.cfg);
  if (!graphConfig.enabled) {
    return { enabled: false, hits: 0, renderedHits: 0, results: [] };
  }
  const store = getCanonicalStore(params.agentId);
  const hits = await search_graph(store, params.query, Math.max(1, params.maxResults ?? 5));
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
  log.info(`canonical.memory_search.graph_hits hits=${hits.length} rendered=${results.length}`);
  return {
    enabled: true,
    hits: hits.length,
    renderedHits: results.length,
    results,
  };
}

export function getCanonicalStatus(params: { cfg?: OpenClawConfig; agentId: string }) {
  const store = getCanonicalStore(params.agentId);
  return {
    ...describeGraphIndexConfig(params.cfg),
    ...store.getStatus(),
  };
}

export async function noteGraphUsageFromMemoryGet(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sessionKey?: string;
  path: string;
  from?: number;
  lines?: number;
}): Promise<void> {
  await markGraphHitsUsedFromMemoryGet(params);
}

export async function noteGraphUsageFromAssistantOutput(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sessionKey?: string;
  assistantTexts: string[];
}): Promise<void> {
  await markGraphHitsUsedFromAssistantTexts(params);
}
