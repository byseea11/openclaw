import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  createSubsystemLogger,
  resolveStateDir,
  resolveUserPath,
  truncateUtf16Safe,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type {
  MemoryTranscriptSpanEntry,
  OpenClawConfig,
} from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { resolveFeishuTaskWikiConfig } from "./schema.js";

const log = createSubsystemLogger("memory");
export const GRAPH_INDEX_IMPL_TAG = "GRAPH_INDEX_IMPL";
export const OPENCLAW_RUNTIME_TAG = "OPENCLAW_RUNTIME";

export type GraphIndexTraceStage =
  | "after_turn_clean"
  | "after_turn_mark_dirty"
  | "drain_scheduled"
  | "drain_started"
  | "extractor_completed"
  | "events_persisted"
  | "kg_objects_derived"
  | "canonical_entities_upserted"
  | "graph_edges_upserted"
  | "entity_states_merged"
  | "cursor_advanced"
  | "memory_search_pending_drain"
  | "memory_search_graph_hits"
  | "before_compaction_catchup"
  | "kg_persist_failed"
  | "drain_failed";

export type GraphIndexTraceEvent = {
  ts: string;
  tag: typeof GRAPH_INDEX_IMPL_TAG;
  trace_id: string;
  stage: GraphIndexTraceStage;
  observed_tags?: string[];
  source_kind?: "transcript" | "flush" | "backfill";
  source_id?: string;
  entry_range?: {
    first?: string | null;
    last?: string | null;
  };
  dirty?: Record<string, unknown>;
  drain?: Record<string, unknown>;
  input?: Record<string, unknown>;
  extract?: Record<string, unknown>;
  tables?: Record<string, unknown>;
  search?: Record<string, unknown>;
  reducer?: Record<string, unknown>;
  call?: Record<string, unknown>;
  error?: string;
  entry_preview?: Array<{
    entryId: string;
    role: string;
    text: string;
  }>;
};

type TraceInput = Omit<GraphIndexTraceEvent, "ts" | "tag" | "trace_id"> & {
  trace_id?: string;
};

export function buildGraphTraceId(parts: Array<number | string | null | undefined>): string {
  const material = parts.map((part) => String(part ?? "")).join("|");
  return `graph_${crypto.createHash("sha1").update(material).digest("hex").slice(0, 16)}`;
}

function resolveTraceFilePath(cfg: OpenClawConfig | undefined): string {
  const graphConfig = resolveFeishuTaskWikiConfig(cfg);
  const configuredPath = graphConfig.trace.filePath;
  if (configuredPath) {
    return resolveUserPath(configuredPath);
  }
  return path.join(resolveStateDir(process.env, os.homedir), "logs", "graph-index-trace.jsonl");
}

function entryPreview(
  entries: MemoryTranscriptSpanEntry[] | undefined,
  maxPreviewChars: number,
): GraphIndexTraceEvent["entry_preview"] {
  if (!entries?.length) {
    return undefined;
  }
  return entries.map((entry) => {
    const role = entry.messageRole?.trim() || entry.entryType;
    const text = [entry.messageContent, entry.toolName, entry.toolResult]
      .filter((value): value is string => Boolean(value?.trim()))
      .join("\n");
    return {
      entryId: entry.entryId,
      role,
      text: truncateUtf16Safe(text, maxPreviewChars),
    };
  });
}

function observedTags(entries: MemoryTranscriptSpanEntry[] | undefined): string[] | undefined {
  if (!entries?.length) {
    return undefined;
  }
  const tags = new Set<string>();
  for (const entry of entries) {
    if (entry.messageRole === "user" || entry.toolName?.trim() || entry.toolResult?.trim()) {
      tags.add(OPENCLAW_RUNTIME_TAG);
    }
  }
  return tags.size > 0 ? [...tags] : undefined;
}

function writeTraceFile(filePath: string, event: GraphIndexTraceEvent): void {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.appendFileSync(filePath, `${JSON.stringify(event)}\n`, "utf8");
  } catch (err) {
    log.warn(`${GRAPH_INDEX_IMPL_TAG} canonical.trace.write_failed error=${String(err)}`, {
      tag: GRAPH_INDEX_IMPL_TAG,
      graph_stage: "trace_write_failed",
      trace_id: event.trace_id,
    });
  }
}

export function recordGraphIndexTrace(params: {
  cfg?: OpenClawConfig;
  message: string;
  summary?: string;
  event: TraceInput;
  entries?: MemoryTranscriptSpanEntry[];
}): void {
  const graphConfig = resolveFeishuTaskWikiConfig(params.cfg);
  const traceId =
    params.event.trace_id ??
    buildGraphTraceId([
      params.event.stage,
      params.event.source_id,
      params.event.entry_range?.first,
      params.event.entry_range?.last,
    ]);
  const event: GraphIndexTraceEvent = {
    ...params.event,
    ts: new Date().toISOString(),
    tag: GRAPH_INDEX_IMPL_TAG,
    trace_id: traceId,
  };
  event.observed_tags = observedTags(params.entries);
  if (graphConfig.trace.enabled && graphConfig.trace.includeEntryPreview) {
    event.entry_preview = entryPreview(params.entries, graphConfig.trace.maxPreviewChars);
  }

  const runtimeMessage = [
    GRAPH_INDEX_IMPL_TAG,
    params.message,
    params.summary,
    event.observed_tags?.length ? `observed=${event.observed_tags.join(",")}` : null,
  ]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(" ");
  log.info(runtimeMessage, {
    tag: GRAPH_INDEX_IMPL_TAG,
    observed_tags: event.observed_tags,
    graph_stage: event.stage,
    trace_id: event.trace_id,
    source_id: event.source_id,
  });

  if (!graphConfig.trace.enabled) {
    return;
  }
  writeTraceFile(resolveTraceFilePath(params.cfg), event);
}
