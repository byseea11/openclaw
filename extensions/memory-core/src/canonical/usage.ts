import {
  createSubsystemLogger,
  resolveAgentWorkspaceDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { appendMemoryHostEvent } from "openclaw/plugin-sdk/memory-host-events";
import type { GraphMemorySearchResult } from "./prompt.js";
import { parseSourceRef, type GraphHit } from "./schema.js";
import { getCanonicalStore } from "./store.js";
import { buildGraphTraceId, recordGraphIndexTrace } from "./trace.js";

const log = createSubsystemLogger("memory");

type UsageContext = {
  cfg: OpenClawConfig;
  agentId: string;
  sessionKey?: string;
};

function resolveWorkspaceDir(cfg: OpenClawConfig, agentId: string): string | undefined {
  return resolveAgentWorkspaceDir(cfg, agentId)?.trim() || undefined;
}

function normalizeSourceRefs(texts: string[]): string[] {
  return [
    ...new Set(
      texts
        .flatMap((text) =>
          [...text.matchAll(/\b(?:MEMORY\.md|memory\/[^\s#]+)#L\d+(?:-L?\d+)?\b/g)].map(
            (match) => match[0] ?? "",
          ),
        )
        .filter(Boolean),
    ),
  ];
}

function uniqueBySourceRef<T extends { source_ref: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  const unique: T[] = [];
  for (const item of items) {
    if (seen.has(item.source_ref)) {
      continue;
    }
    seen.add(item.source_ref);
    unique.push(item);
  }
  return unique;
}

function asRecordedResult(hit: GraphHit | GraphMemorySearchResult) {
  const parsed = "graphMeta" in hit ? null : parseSourceRef(hit.source_ref);
  return {
    type: "graphMeta" in hit ? hit.graphMeta.type : hit.type,
    entityId: "graphMeta" in hit ? hit.graphMeta.entity_id : hit.entity_id,
    sourceRef:
      "graphMeta" in hit ? `${hit.path}#L${hit.startLine}-L${hit.endLine}` : hit.source_ref,
    path:
      "graphMeta" in hit
        ? hit.path
        : (parsed?.path ?? hit.source_ref.split("#", 1)[0] ?? hit.source_ref),
    startLine: "graphMeta" in hit ? hit.startLine : (parsed?.startLine ?? 0),
    endLine: "graphMeta" in hit ? hit.endLine : (parsed?.endLine ?? 0),
    score: hit.score,
  };
}

export async function recordReturnedGraphHits(
  ctx: UsageContext & {
    query: string;
    hits: GraphHit[];
  },
): Promise<void> {
  if (!ctx.sessionKey || ctx.hits.length === 0) {
    return;
  }
  const store = getCanonicalStore(ctx.agentId);
  const recorded = store.recordRecentGraphHits({
    sessionKey: ctx.sessionKey,
    query: ctx.query,
    hits: ctx.hits,
  });
  if (recorded <= 0) {
    return;
  }
  store.bumpMetric("hitsReturned", recorded);
  log.info(`[canonical] usage.returned session=${ctx.sessionKey} hits=${recorded}`);
  recordGraphIndexTrace({
    cfg: ctx.cfg,
    message: "canonical.memory_search.graph_hits_recorded",
    summary: `session=${ctx.sessionKey} table=recent_graph_hits rows=${recorded}`,
    event: {
      trace_id: buildGraphTraceId([ctx.sessionKey, ctx.query, "recent_graph_hits"]),
      stage: "memory_search_graph_hits",
      source_kind: "transcript",
      source_id: ctx.sessionKey,
      search: {
        query: ctx.query,
        recorded_recent_hits: recorded,
      },
      tables: {
        recent_graph_hits: {
          table: "recent_graph_hits",
          rows: recorded,
          hits: ctx.hits.map(asRecordedResult),
        },
      },
      call: {
        function: "recordReturnedGraphHits",
        steps: ["recordRecentGraphHits", "appendMemoryHostEvent"],
      },
    },
  });
  const workspaceDir = resolveWorkspaceDir(ctx.cfg, ctx.agentId);
  if (!workspaceDir) {
    return;
  }
  try {
    await appendMemoryHostEvent(workspaceDir, {
      type: "memory.graph.recall.recorded",
      timestamp: new Date().toISOString(),
      sessionKey: ctx.sessionKey,
      query: ctx.query,
      resultCount: recorded,
      results: ctx.hits.map(asRecordedResult),
    });
  } catch (err) {
    log.warn(`[canonical] usage.host_event_failed via=returned error=${String(err)}`);
  }
}

export async function markGraphHitsUsedFromMemoryGet(
  ctx: UsageContext & {
    path: string;
    from?: number;
    lines?: number;
  },
): Promise<void> {
  if (!ctx.sessionKey) {
    return;
  }
  const store = getCanonicalStore(ctx.agentId);
  const used = store.markRecentGraphHitsUsedByRead({
    sessionKey: ctx.sessionKey,
    path: ctx.path,
    from: ctx.from,
    lines: ctx.lines,
  });
  if (used.length === 0) {
    return;
  }
  const uniqueUsed = uniqueBySourceRef(used);
  store.bumpMetric("hitsUsedRaw", used.length);
  store.bumpMetric("hitsUsedUniqueRefs", uniqueUsed.length);
  log.info(
    `[canonical] usage.used via=memory_get source_ref=${uniqueUsed.map((item) => item.source_ref).join(",")}`,
  );
  const workspaceDir = resolveWorkspaceDir(ctx.cfg, ctx.agentId);
  if (!workspaceDir) {
    return;
  }
  try {
    await appendMemoryHostEvent(workspaceDir, {
      type: "memory.graph.recall.used",
      timestamp: new Date().toISOString(),
      sessionKey: ctx.sessionKey,
      via: "memory_get",
      sourceRefs: uniqueUsed.map((item) => item.source_ref),
      results: uniqueUsed.map((item) => ({
        type: item.hit_type,
        entityId: item.entity_id,
        sourceRef: item.source_ref,
        path: item.path,
        startLine: item.start_line,
        endLine: item.end_line,
      })),
    });
  } catch (err) {
    log.warn(`[canonical] usage.host_event_failed via=memory_get error=${String(err)}`);
  }
}

export async function markGraphHitsUsedFromAssistantTexts(
  ctx: UsageContext & {
    assistantTexts: string[];
  },
): Promise<void> {
  if (!ctx.sessionKey || ctx.assistantTexts.length === 0) {
    return;
  }
  const sourceRefs = normalizeSourceRefs(ctx.assistantTexts);
  if (sourceRefs.length === 0) {
    return;
  }
  const store = getCanonicalStore(ctx.agentId);
  const used = store.markRecentGraphHitsUsedBySourceRefs({
    sessionKey: ctx.sessionKey,
    sourceRefs,
  });
  if (used.length === 0) {
    return;
  }
  const uniqueUsed = uniqueBySourceRef(used);
  store.bumpMetric("hitsUsedRaw", used.length);
  store.bumpMetric("hitsUsedUniqueRefs", uniqueUsed.length);
  log.info(
    `[canonical] usage.used via=llm_output source_ref=${uniqueUsed.map((item) => item.source_ref).join(",")}`,
  );
  const workspaceDir = resolveWorkspaceDir(ctx.cfg, ctx.agentId);
  if (!workspaceDir) {
    return;
  }
  try {
    await appendMemoryHostEvent(workspaceDir, {
      type: "memory.graph.recall.used",
      timestamp: new Date().toISOString(),
      sessionKey: ctx.sessionKey,
      via: "llm_output",
      sourceRefs: uniqueUsed.map((item) => item.source_ref),
      results: uniqueUsed.map((item) => ({
        type: item.hit_type,
        entityId: item.entity_id,
        sourceRef: item.source_ref,
        path: item.path,
        startLine: item.start_line,
        endLine: item.end_line,
      })),
    });
  } catch (err) {
    log.warn(`[canonical] usage.host_event_failed via=llm_output error=${String(err)}`);
  }
}

export const __testing = {
  normalizeSourceRefs,
  uniqueBySourceRef,
};
