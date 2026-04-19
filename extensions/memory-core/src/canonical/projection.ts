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
import { isGraphExtractorSessionKey } from "./extractor.runtime.js";
import {
  EXTRACTOR_VERSION,
  type ProjectionInboxEntry,
  resolveGraphIndexConfig,
} from "./schema.js";
import { getCanonicalStore } from "./store.js";
import { buildGraphTraceId, recordGraphIndexTrace } from "./trace.js";

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
  /\b(status|owner|decided|decision|blocked|done|due|assigned|remember|update|deadline|todo|task|project|ticket|issue|prefer|preference|like|love|favorite|family|friend|partner|husband|wife|daughter|son|child|children|parent|school|class|college|university|work|job|internship|research|trip|travel|move|moved|live|lives|birthday|appointment|doctor|health|medicine|medication|plan|planning|tomorrow|yesterday)\b/i;
const STRUCTURED_RE =
  /\b(?:[A-Z]+-\d+|#[1-9]\d*|task[:\s-]+|project[:\s-]+|decision[:\s-]+|owner:\s*|status:\s*)/i;
const STRONG_EVENT_RE =
  /\b(owner changed|status changed|decided|decision made|deadline updated|assigned to|blocked|done|completed)\b/i;
const GRAPH_RECALL_MARKER_RE = /\[Graph (?:event|state)\]|\[toolCall:memory_search\]/i;

function projectionTraceId(params: {
  sourceId: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
}): string {
  return buildGraphTraceId([params.sourceId, params.firstEntryId, params.lastEntryId]);
}

function normalizeTraceText(value: string, limit = 600): string {
  return value.replace(/\s+/g, " ").trim().slice(0, limit);
}

function latestUserQuery(entries: MemoryTranscriptSpanEntry[]): string | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (entry?.messageRole !== "user") {
      continue;
    }
    const text = entry.messageContent.trim();
    if (!text) {
      continue;
    }
    return normalizeTraceText(text, 1000);
  }
  return null;
}

function buildTraceInput(entries: MemoryTranscriptSpanEntry[]): Record<string, unknown> {
  const userMessages = entries
    .filter((entry) => entry.messageRole === "user" && entry.messageContent.trim())
    .map((entry) => ({
      entry_id: entry.entryId,
      text: normalizeTraceText(entry.messageContent, 1000),
    }));
  const toolCalls = entries
    .filter((entry) => entry.toolName?.trim())
    .map((entry) => ({
      entry_id: entry.entryId,
      tool_name: entry.toolName,
    }));
  return {
    latest_user_query: latestUserQuery(entries),
    user_messages: userMessages,
    tool_calls: toolCalls,
    entry_count: entries.length,
  };
}

function traceRawEvent(event: {
  actor?: string;
  action: string;
  object?: string;
  status_before?: string;
  status_after?: string;
  occurred_at?: string;
  source_ref: string;
  confidence?: number;
}) {
  return {
    actor: event.actor ?? null,
    action: event.action,
    object: event.object ?? null,
    status_before: event.status_before ?? null,
    status_after: event.status_after ?? null,
    occurred_at: event.occurred_at ?? null,
    source_ref: event.source_ref,
    confidence: event.confidence ?? null,
  };
}

function traceEventRecord(record: {
  event_id: string;
  entity_id: string;
  actor: string | null;
  action: string;
  object: string | null;
  status_before: string | null;
  status_after: string | null;
  source_type: string;
  source_ref: string;
  session_id: string | null;
  covered_until_entry_id: string | null;
}) {
  return {
    event_id: record.event_id,
    entity_id: record.entity_id,
    actor: record.actor,
    action: record.action,
    object: record.object,
    status_before: record.status_before,
    status_after: record.status_after,
    source_type: record.source_type,
    source_ref: record.source_ref,
    session_id: record.session_id,
    covered_until_entry_id: record.covered_until_entry_id,
  };
}

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

function isMemorySearchEchoEntry(entry: MemoryTranscriptSpanEntry): boolean {
  return (
    entry.toolName === "memory_search" ||
    entry.messageRole === "toolResult" ||
    GRAPH_RECALL_MARKER_RE.test(entry.messageContent) ||
    (entry.toolResult ? GRAPH_RECALL_MARKER_RE.test(entry.toolResult) : false)
  );
}

function entriesForExtraction(entries: MemoryTranscriptSpanEntry[]): MemoryTranscriptSpanEntry[] {
  const firstRecallEchoIndex = entries.findIndex(isMemorySearchEchoEntry);
  const candidateEntries =
    firstRecallEchoIndex >= 0 ? entries.slice(0, firstRecallEchoIndex) : entries;
  return candidateEntries.filter((entry) => {
    if (entry.messageRole === "toolResult" || entry.toolName?.trim()) {
      return false;
    }
    return Boolean(entry.messageContent.trim());
  });
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

function scheduleIdleDrain(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sourceId: string;
  traceId?: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
}): void {
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
  recordGraphIndexTrace({
    cfg: params.cfg,
    message: "canonical.projection.drain_scheduled",
    summary: `reason=idle source=${params.sourceId}`,
    event: {
      trace_id:
        params.traceId ??
        projectionTraceId({
          sourceId: params.sourceId,
          firstEntryId: params.firstEntryId,
          lastEntryId: params.lastEntryId,
        }),
      stage: "drain_scheduled",
      source_kind: "transcript",
      source_id: params.sourceId,
      drain: {
        reason: "idle",
        delay_ms: IDLE_DRAIN_MS,
      },
    },
  });
}

function scheduleAsyncDrain(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sourceId: string;
  reason: DrainReason;
  traceId?: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
}): void {
  recordGraphIndexTrace({
    cfg: params.cfg,
    message: "canonical.projection.drain_scheduled",
    summary: `reason=${params.reason} source=${params.sourceId}`,
    event: {
      trace_id:
        params.traceId ??
        projectionTraceId({
          sourceId: params.sourceId,
          firstEntryId: params.firstEntryId,
          lastEntryId: params.lastEntryId,
        }),
      stage: "drain_scheduled",
      source_kind: "transcript",
      source_id: params.sourceId,
      drain: {
        reason: params.reason,
        delay_ms: 0,
      },
    },
  });
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
  if (isGraphExtractorSessionKey(params.sessionKey) || isGraphExtractorSessionKey(params.sessionId)) {
    return;
  }
  const detected = detectTranscriptSignals(params.entries);
  const sourceId = sourceIdFromParams(params);
  const firstEntry = params.entries[0]?.entryId;
  const lastEntry = params.entries.at(-1)?.entryId;
  const traceId = projectionTraceId({
    sourceId,
    firstEntryId: firstEntry,
    lastEntryId: lastEntry,
  });
  if (!detected.dirty) {
    recordGraphIndexTrace({
      cfg: params.cfg,
      message: "canonical.projection.after_turn",
      summary: `clean source=${sourceId} entries=${params.entries.length}`,
      event: {
        trace_id: traceId,
        stage: "after_turn_clean",
        source_kind: "transcript",
        source_id: sourceId,
        entry_range: {
          first: firstEntry,
          last: lastEntry,
        },
      },
      entries: params.entries,
    });
    return;
  }
  if (!firstEntry || !lastEntry) {
    return;
  }
  const store = getCanonicalStore(params.agentId);
  const beforeState = store.getProjectionState(sourceId);
  const beforeSummary = store.listPendingProjectionSummaries(sourceId)[0];
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
  const afterState = store.getProjectionState(sourceId);
  const afterSummary = store.listPendingProjectionSummaries(sourceId)[0];
  recordGraphIndexTrace({
    cfg: params.cfg,
    message: "canonical.projection.after_turn",
    summary: `dirty inserted=${inserted} source=${sourceId} reason=${detected.dirtyReason} strength=${detected.signalStrength.toFixed(2)} needs_llm=${detected.needsLlmExtraction} strong=${detected.strongEvent}`,
    event: {
      trace_id: traceId,
      stage: "after_turn_mark_dirty",
      source_kind: "transcript",
      source_id: sourceId,
      entry_range: {
        first: firstEntry,
        last: lastEntry,
      },
      dirty: {
        reason: detected.dirtyReason,
        signal_strength: detected.signalStrength,
        needs_llm_extraction: detected.needsLlmExtraction,
        strong_event: detected.strongEvent,
      },
      input: buildTraceInput(params.entries),
      call: {
        function: "handleGraphAfterTurn",
        steps: ["detectTranscriptSignals", "enqueueProjectionInbox", "scheduleIdleDrain"],
      },
      tables: {
        projection_inbox: {
          inserted,
          pending_before: beforeSummary?.pending_spans ?? 0,
          pending_after: afterSummary?.pending_spans ?? 0,
        },
        source_projection_state: {
          status_before: beforeState?.status ?? "missing",
          status_after: afterState?.status ?? "missing",
          dirty_since_entry_id: afterState?.dirty_since_entry_id ?? null,
        },
      },
    },
    entries: params.entries,
  });
  scheduleIdleDrain({
    cfg: params.cfg,
    agentId: params.agentId,
    sourceId,
    traceId,
    firstEntryId: firstEntry,
    lastEntryId: lastEntry,
  });
  const summary = store.listPendingProjectionSummaries(sourceId)[0];
  if (detected.strongEvent) {
    scheduleAsyncDrain({
      cfg: params.cfg,
      agentId: params.agentId,
      sourceId,
      reason: "strong_event",
      traceId,
      firstEntryId: firstEntry,
      lastEntryId: lastEntry,
    });
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
      traceId,
      firstEntryId: firstEntry,
      lastEntryId: lastEntry,
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
  if (isGraphExtractorSessionKey(params.sessionKey) || isGraphExtractorSessionKey(params.sessionId)) {
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
  recordGraphIndexTrace({
    cfg: params.cfg,
    message: "canonical.projection.before_compaction",
    summary: `source=${sourceId} entries=${params.entries.length}`,
    event: {
      trace_id: projectionTraceId({
        sourceId,
        firstEntryId: firstEntry,
        lastEntryId: lastEntry,
      }),
      stage: "before_compaction_catchup",
      source_kind: "transcript",
      source_id: sourceId,
      entry_range: {
        first: firstEntry,
        last: lastEntry,
      },
      drain: {
        reason: "pre_compaction",
        synchronous: true,
      },
    },
    entries: params.entries,
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
    const traceId = projectionTraceId({
      sourceId: summary.source_id,
      firstEntryId: summary.first_entry_id,
      lastEntryId: summary.last_entry_id,
    });
    const stateBeforeDrain = store.getProjectionState(summary.source_id);
    store.markProjectionSourceDraining(summary.source_id);
    try {
      const rows = store.listPendingProjectionInbox(summary.source_id);
      const entries = parseInboxEntries(rows);
      const coveredUntilEntryId = entries.at(-1)?.entryId ?? summary.last_entry_id;
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.projection.drain",
        summary: `started reason=${params.reason} source=${summary.source_id} spans=${rows.length} entries=${entries.length}`,
        event: {
          trace_id: traceId,
          stage: "drain_started",
          source_kind: "transcript",
          source_id: summary.source_id,
          entry_range: {
            first: summary.first_entry_id,
            last: coveredUntilEntryId,
          },
          drain: {
            reason: params.reason,
            pending_spans: rows.length,
            pending_entries: entries.length,
            state_before: stateBeforeDrain?.status ?? "missing",
          },
          input: buildTraceInput(entries),
          call: {
            function: "drainPendingGraphUpdates",
            steps: ["listPendingProjectionInbox", "parseInboxEntries", "renderProjectionBatch"],
          },
        },
        entries,
      });
      if (entries.length === 0 || !coveredUntilEntryId) {
        store.markProjectionDrained({
          sourceId: summary.source_id,
          coveredUntilEntryId: coveredUntilEntryId ?? summary.last_entry_id ?? "",
        });
        continue;
      }
      const extractEntries = entriesForExtraction(entries);
      const startedAt = Date.now();
      const rendered = renderProjectionBatch(summary.source_id, extractEntries);
      const rawEvents = await extract(rendered.text, rendered.sourceRef);
      const extractionMs = Date.now() - startedAt;
      store.recordExtractorLatency(extractionMs);
      store.bumpMetric("extractSuccesses", 1);
      parsedEvents += rawEvents.length;
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.projection.extractor",
        summary: `completed reason=${params.reason} source=${summary.source_id} entries=${entries.length} events=${rawEvents.length} latency_ms=${extractionMs}`,
        event: {
          trace_id: traceId,
          stage: "extractor_completed",
          source_kind: "transcript",
          source_id: summary.source_id,
          entry_range: {
            first: summary.first_entry_id,
            last: coveredUntilEntryId,
          },
          extract: {
            reason: params.reason,
            entries: extractEntries.length,
            skipped_entries: entries.length - extractEntries.length,
            events: rawEvents.length,
            latency_ms: extractionMs,
            rendered_source_ref: rendered.sourceRef,
            raw_events_json: rawEvents.map(traceRawEvent),
          },
          input: {
            ...buildTraceInput(entries),
            extractable_entry_count: extractEntries.length,
            skipped_echo_entry_count: entries.length - extractEntries.length,
            rendered_transcript_ref: rendered.sourceRef,
          },
          call: {
            function: "extract",
            steps: ["renderProjectionBatch", "extract"],
          },
        },
      });
      if (rawEvents.length > 0) {
        const records = canonicalize(rawEvents, EXTRACTOR_VERSION, {
          sourceType: "transcript",
          sessionId: summary.source_id,
          coveredUntilEntryId,
        });
        const mergeComputation = await store.explainEntityStateRefresh(records);
        store.setMeta("extractor_version", EXTRACTOR_VERSION);
        await store.upsertEvents(records);
        recordGraphIndexTrace({
          cfg: params.cfg,
          message: "canonical.projection.events_persisted",
          summary: `source=${summary.source_id} records=${records.length}`,
          event: {
            trace_id: traceId,
            stage: "events_persisted",
            source_kind: "transcript",
            source_id: summary.source_id,
            entry_range: {
              first: summary.first_entry_id,
              last: coveredUntilEntryId,
            },
            tables: {
              event_records: {
                table: "event_records",
                persisted: records.length,
                canonical_records_json: records.map(traceEventRecord),
              },
            },
            call: {
              function: "upsertEvents",
              steps: ["canonicalize", "event_records", "event_fts"],
            },
          },
        });
        const states = await store.refreshEntityStates(records, mergeComputation);
        recordGraphIndexTrace({
          cfg: params.cfg,
          message: "canonical.projection.entity_states_merged",
          summary: `source=${summary.source_id} states=${states.length}`,
          event: {
            trace_id: traceId,
            stage: "entity_states_merged",
            source_kind: "transcript",
            source_id: summary.source_id,
            entry_range: {
              first: summary.first_entry_id,
              last: coveredUntilEntryId,
            },
            tables: {
              entity_states: {
                table: "entity_states",
                merged: states.length,
                next_states: states,
              },
            },
            reducer: {
              function: "reduce",
              policy: {
                latest_event_selection:
                  "Newest event per entity wins by occurred_at, then created_at.",
                latest_status: "event.status_after ?? previous.latest_status",
                latest_owner: "event.actor ?? previous.latest_owner",
              },
              entity_ids: mergeComputation.entityIds,
              previous_states: mergeComputation.previousStates,
              input_events: mergeComputation.events.map(traceEventRecord),
              next_states: mergeComputation.states,
            },
            call: {
              function: "refreshEntityStates",
              steps: ["getEntityState", "reduce", "entity_states upsert"],
            },
          },
        });
        persistedEvents += records.length;
      } else {
        recordGraphIndexTrace({
          cfg: params.cfg,
          message: "canonical.projection.events_persisted",
          summary: `source=${summary.source_id} records=0`,
          event: {
            trace_id: traceId,
            stage: "events_persisted",
            source_kind: "transcript",
            source_id: summary.source_id,
            entry_range: {
              first: summary.first_entry_id,
              last: coveredUntilEntryId,
            },
            tables: {
              event_records: {
                persisted: 0,
              },
            },
          },
        });
      }
      store.markProjectionDrained({ sourceId: summary.source_id, coveredUntilEntryId });
      const stateAfterDrain = store.getProjectionState(summary.source_id);
      drainedSources += 1;
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.projection.drain",
        summary: `reason=${params.reason} source=${summary.source_id} entries=${entries.length} events=${rawEvents.length} persisted=${rawEvents.length > 0 ? rawEvents.length : 0} covered_until=${coveredUntilEntryId}`,
        event: {
          trace_id: traceId,
          stage: "cursor_advanced",
          source_kind: "transcript",
          source_id: summary.source_id,
          entry_range: {
            first: summary.first_entry_id,
            last: coveredUntilEntryId,
          },
          tables: {
            projection_inbox: {
              drained: rows.length,
            },
            source_projection_state: {
              status_before: stateBeforeDrain?.status ?? "missing",
              status_after: stateAfterDrain?.status ?? "missing",
              covered_until_entry_id: stateAfterDrain?.covered_until_entry_id ?? null,
              dirty_since_entry_id: stateAfterDrain?.dirty_since_entry_id ?? null,
            },
          },
        },
      });
    } catch (err) {
      store.bumpMetric("extractFailures", 1);
      store.markProjectionFailed(summary.source_id);
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.projection.drain_failed",
        summary: `reason=${params.reason} source=${summary.source_id} error=${String(err)}`,
        event: {
          trace_id: traceId,
          stage: "drain_failed",
          source_kind: "transcript",
          source_id: summary.source_id,
          entry_range: {
            first: summary.first_entry_id,
            last: summary.last_entry_id,
          },
          drain: {
            reason: params.reason,
          },
          error: String(err),
        },
      });
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
