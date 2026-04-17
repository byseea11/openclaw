import crypto from "node:crypto";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type {
  MemoryAfterTurnObserver,
  MemoryBeforeCompactionObserver,
  MemoryTranscriptSpanEntry,
  OpenClawConfig,
} from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { canonicalize } from "./canonicalizer.js";
import { extract } from "./extractor.js";
import {
  EXTRACTOR_VERSION,
  type ProjectionInboxEntry,
  resolveGraphIndexConfig,
} from "./schema.js";
import { getCanonicalStore } from "./store.js";

const log = createSubsystemLogger("memory");

const DIRTY_TURN_THRESHOLD = 3;
const DIRTY_ENTRY_THRESHOLD = 12;
const DIRTY_TOKEN_THRESHOLD = 2500;
const IDLE_DRAIN_MS = 10 * 60 * 1000;

type SignalDetection = {
  dirty: boolean;
  dirtyReason: string;
  signalStrength: number;
  needsLlmExtraction: boolean;
  strongEvent: boolean;
};

type DrainReason = "recall" | "dirty_threshold" | "idle" | "strong_event" | "pre_compaction";

const idleTimers = new Map<string, ReturnType<typeof setTimeout>>();
const drainingSources = new Set<string>();

const SIGNAL_RE =
  /\b(status|owner|decided|decision|blocked|done|due|assigned|remember|update|deadline|todo|task|project|ticket|issue)\b/i;
const STRUCTURED_RE =
  /\b(?:[A-Z]+-\d+|#[1-9]\d*|task[:\s-]+|project[:\s-]+|decision[:\s-]+|owner:\s*|status:\s*)/i;
const STRONG_EVENT_RE =
  /\b(owner changed|status changed|decided|decision made|deadline updated|assigned to|blocked|done|completed)\b/i;

function hashSourceId(value: string): string {
  return crypto.createHash("sha1").update(value).digest("hex").slice(0, 16);
}

function sourceIdFromParams(params: { sessionKey?: string; sessionId: string; sessionFile: string }): string {
  return params.sessionKey?.trim() || params.sessionId.trim() || hashSourceId(params.sessionFile);
}

function textForSignal(entry: MemoryTranscriptSpanEntry): string {
  return [entry.messageContent, entry.toolName, entry.toolResult].filter(Boolean).join("\n");
}

function detectTranscriptSignals(entries: MemoryTranscriptSpanEntry[]): SignalDetection {
  let signalStrength = 0;
  let strongEvent = false;
  const reasons = new Set<string>();
  for (const entry of entries) {
    const text = textForSignal(entry);
    if (!text.trim()) {
      continue;
    }
    if (SIGNAL_RE.test(text)) {
      signalStrength += 0.4;
      reasons.add("keyword");
    }
    if (STRUCTURED_RE.test(text)) {
      signalStrength += 0.35;
      reasons.add("structured");
    }
    if (entry.toolResult?.trim() && SIGNAL_RE.test(entry.toolResult)) {
      signalStrength += 0.3;
      reasons.add("tool_result");
    }
    if (STRONG_EVENT_RE.test(text)) {
      signalStrength += 0.6;
      strongEvent = true;
      reasons.add("strong_event");
    }
  }
  const normalizedStrength = Math.min(1, signalStrength);
  return {
    dirty: normalizedStrength > 0,
    dirtyReason: [...reasons].toSorted().join(",") || "none",
    signalStrength: normalizedStrength,
    needsLlmExtraction: normalizedStrength >= 0.7,
    strongEvent,
  };
}

function renderEntry(entry: MemoryTranscriptSpanEntry): string {
  const role = entry.messageRole?.trim() || entry.entryType;
  const content = entry.messageContent.trim();
  const tool = entry.toolName?.trim();
  const toolResult = entry.toolResult?.trim();
  return [
    `[${entry.entryId}] ${role}: ${content}`,
    tool ? `tool: ${tool}` : null,
    toolResult ? `tool_result: ${toolResult}` : null,
  ]
    .filter((line): line is string => Boolean(line?.trim()))
    .join(" ");
}

function renderProjectionBatch(sourceId: string, entries: MemoryTranscriptSpanEntry[]): {
  text: string;
  sourceRef: string;
} {
  const sourcePath = `transcripts/${hashSourceId(sourceId)}.txt`;
  const lines = entries.map(renderEntry).filter(Boolean);
  return {
    text: lines.join("\n"),
    sourceRef: `${sourcePath}#L1-L${Math.max(1, lines.length)}`,
  };
}

function parseInboxEntries(rows: ProjectionInboxEntry[]): MemoryTranscriptSpanEntry[] {
  const entriesById = new Map<string, MemoryTranscriptSpanEntry>();
  for (const row of rows) {
    try {
      const parsed = JSON.parse(row.entries_json) as unknown;
      if (!Array.isArray(parsed)) {
        continue;
      }
      for (const value of parsed) {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          continue;
        }
        const candidate = value as Partial<MemoryTranscriptSpanEntry>;
        if (typeof candidate.entryId !== "string" || !candidate.entryId.trim()) {
          continue;
        }
        entriesById.set(candidate.entryId, {
          entryId: candidate.entryId,
          parentId: typeof candidate.parentId === "string" ? candidate.parentId : null,
          entryType: candidate.entryType ?? "custom",
          messageRole: typeof candidate.messageRole === "string" ? candidate.messageRole : null,
          messageContent:
            typeof candidate.messageContent === "string" ? candidate.messageContent : "",
          toolName: typeof candidate.toolName === "string" ? candidate.toolName : null,
          toolResult: typeof candidate.toolResult === "string" ? candidate.toolResult : null,
          timestamp: typeof candidate.timestamp === "string" ? candidate.timestamp : null,
        });
      }
    } catch {
      log.warn(`canonical.projection.inbox_parse_failed id=${row.id}`);
    }
  }
  return [...entriesById.values()];
}

function scheduleIdleDrain(params: { cfg: OpenClawConfig; agentId: string; sourceId: string }): void {
  const existing = idleTimers.get(params.sourceId);
  if (existing) {
    clearTimeout(existing);
  }
  const timer = setTimeout(() => {
    idleTimers.delete(params.sourceId);
    void drainPendingGraphUpdates({
      cfg: params.cfg,
      agentId: params.agentId,
      sourceId: params.sourceId,
      reason: "idle",
    }).catch((err) => {
      log.warn(`[canonical] projection.idle_drain_failed error=${String(err)}`);
    });
  }, IDLE_DRAIN_MS);
  timer.unref?.();
  idleTimers.set(params.sourceId, timer);
}

function scheduleAsyncDrain(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sourceId: string;
  reason: DrainReason;
}): void {
  setTimeout(() => {
    void drainPendingGraphUpdates(params).catch((err) => {
      log.warn(`[canonical] projection.async_drain_failed reason=${params.reason} error=${String(err)}`);
    });
  }, 0).unref?.();
}

function shouldDrainForAccumulation(params: {
  pendingSpans: number;
  pendingEntries: number;
  estimatedTokens: number;
}): boolean {
  return (
    params.pendingSpans >= DIRTY_TURN_THRESHOLD ||
    params.pendingEntries >= DIRTY_ENTRY_THRESHOLD ||
    params.estimatedTokens >= DIRTY_TOKEN_THRESHOLD
  );
}

export const handleGraphAfterTurn: MemoryAfterTurnObserver = async (params) => {
  const graphConfig = resolveGraphIndexConfig(params.cfg);
  if (!graphConfig.enabled || params.entries.length === 0) {
    return;
  }
  const detected = detectTranscriptSignals(params.entries);
  if (!detected.dirty) {
    log.info("canonical.projection.after_turn.clean");
    return;
  }
  const sourceId = sourceIdFromParams(params);
  const firstEntry = params.entries[0]?.entryId;
  const lastEntry = params.entries.at(-1)?.entryId;
  if (!firstEntry || !lastEntry) {
    return;
  }
  const store = getCanonicalStore(params.agentId);
  const inserted = store.enqueueProjectionInbox({
    source_kind: "transcript",
    source_id: sourceId,
    first_entry_id: firstEntry,
    last_entry_id: lastEntry,
    entries_json: JSON.stringify(params.entries),
    dirty_reason: detected.dirtyReason,
    signal_strength: detected.signalStrength,
    strong_event: detected.strongEvent,
    created_at: Date.now(),
  });
  log.info(
    `canonical.projection.after_turn dirty inserted=${inserted} source=${sourceId} reason=${detected.dirtyReason} strength=${detected.signalStrength.toFixed(2)} needs_llm=${detected.needsLlmExtraction}`,
  );
  scheduleIdleDrain({ cfg: params.cfg, agentId: params.agentId, sourceId });
  const summary = store.listPendingProjectionSummaries(sourceId)[0];
  if (detected.strongEvent) {
    scheduleAsyncDrain({ cfg: params.cfg, agentId: params.agentId, sourceId, reason: "strong_event" });
  } else if (
    summary &&
    shouldDrainForAccumulation({
      pendingSpans: summary.pending_spans,
      pendingEntries: summary.pending_entries,
      estimatedTokens: summary.estimated_tokens,
    })
  ) {
    scheduleAsyncDrain({
      cfg: params.cfg,
      agentId: params.agentId,
      sourceId,
      reason: "dirty_threshold",
    });
  }
};

export const handleGraphBeforeCompaction: MemoryBeforeCompactionObserver = async (params) => {
  if (!params.cfg) {
    return;
  }
  const graphConfig = resolveGraphIndexConfig(params.cfg);
  if (!graphConfig.enabled || params.entries.length === 0) {
    return;
  }
  const sourceId = sourceIdFromParams(params);
  const firstEntry = params.entries[0]?.entryId;
  const lastEntry = params.entries.at(-1)?.entryId;
  if (!firstEntry || !lastEntry) {
    return;
  }
  const store = getCanonicalStore(params.agentId);
  store.enqueueProjectionInbox({
    source_kind: "transcript",
    source_id: sourceId,
    first_entry_id: firstEntry,
    last_entry_id: lastEntry,
    entries_json: JSON.stringify(params.entries),
    dirty_reason: "pre_compaction",
    signal_strength: 1,
    strong_event: true,
    created_at: Date.now(),
  });
  await drainPendingGraphUpdates({
    cfg: params.cfg,
    agentId: params.agentId,
    sourceId,
    reason: "pre_compaction",
  });
};

export async function drainPendingGraphUpdates(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sourceId?: string;
  reason: DrainReason;
}): Promise<{ drainedSources: number; parsedEvents: number; persistedEvents: number }> {
  const graphConfig = resolveGraphIndexConfig(params.cfg);
  if (!graphConfig.enabled) {
    return { drainedSources: 0, parsedEvents: 0, persistedEvents: 0 };
  }
  const store = getCanonicalStore(params.agentId);
  const summaries = store.listPendingProjectionSummaries(params.sourceId);
  let drainedSources = 0;
  let parsedEvents = 0;
  let persistedEvents = 0;
  for (const summary of summaries) {
    if (drainingSources.has(summary.source_id)) {
      continue;
    }
    drainingSources.add(summary.source_id);
    store.markProjectionSourceDraining(summary.source_id);
    try {
      const rows = store.listPendingProjectionInbox(summary.source_id);
      const entries = parseInboxEntries(rows);
      const coveredUntilEntryId = entries.at(-1)?.entryId ?? summary.last_entry_id;
      if (entries.length === 0 || !coveredUntilEntryId) {
        store.markProjectionDrained({
          sourceId: summary.source_id,
          coveredUntilEntryId: coveredUntilEntryId ?? summary.last_entry_id ?? "",
        });
        continue;
      }
      const startedAt = Date.now();
      const rendered = renderProjectionBatch(summary.source_id, entries);
      const rawEvents = await extract(rendered.text, rendered.sourceRef);
      store.recordExtractorLatency(Date.now() - startedAt);
      store.bumpMetric("extractSuccesses", 1);
      parsedEvents += rawEvents.length;
      if (rawEvents.length > 0) {
        const records = canonicalize(rawEvents, EXTRACTOR_VERSION, {
          sourceType: "transcript",
          sessionId: summary.source_id,
          coveredUntilEntryId,
        });
        store.setMeta("extractor_version", EXTRACTOR_VERSION);
        await store.upsertEvents(records);
        await store.refreshEntityStates(records);
        persistedEvents += records.length;
      }
      store.markProjectionDrained({ sourceId: summary.source_id, coveredUntilEntryId });
      drainedSources += 1;
      log.info(
        `canonical.projection.drain reason=${params.reason} source=${summary.source_id} entries=${entries.length} events=${rawEvents.length}`,
      );
    } catch (err) {
      store.bumpMetric("extractFailures", 1);
      store.markProjectionFailed(summary.source_id);
      log.warn(
        `[canonical] projection.drain_failed reason=${params.reason} source=${summary.source_id} error=${String(err)}`,
      );
    } finally {
      drainingSources.delete(summary.source_id);
    }
  }
  return { drainedSources, parsedEvents, persistedEvents };
}

export const __testing = {
  detectTranscriptSignals,
  renderProjectionBatch,
};
