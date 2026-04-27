import crypto from "node:crypto";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type {
  MemoryAfterTurnObserver,
  MemoryBeforeCompactionObserver,
  MemoryTranscriptSpanEntry,
  OpenClawConfig,
} from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { canonicalizeV2 } from "./canonicalizer-v2.js";
import {
  extract,
  getGraphExtractorErrorCode,
  type DecisionCurrentStateContext,
  type DecisionExtractionEnvelope,
  type DecisionPromptEntry,
} from "./extractor.js";
import { isGraphExtractorSessionKey } from "./extractor.runtime.js";
import { type ProjectionInboxEntry, resolveGraphIndexConfig } from "./schema.js";
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
  usedSemanticGate: boolean;
  strongEvent: boolean;
  possibleFields: string[];
  gateReason: string | null;
  gateConfidence: number | null;
};

type DrainReason = "recall" | "dirty_threshold" | "idle" | "strong_event" | "pre_compaction";

const idleTimers = new Map<string, ReturnType<typeof setTimeout>>();
const drainingSources = new Set<string>();

const TASK_ANCHOR_RE = /\b[A-Z][A-Z0-9]+-\d+\b/;
const DOC_SYNC_RE = /(doc|docx|wiki|base|sheet|文档|知识库|多维表格|电子表格)/i;
const PROJECT_RE = /(project|项目|发布|release)/i;
const DECISION_RE =
  /(先按|按这个来|按刚才的来|当前结论|确认|暂定|顺延|不是已确认|不要(?:对外)?说死|先别说死|改成|最终|口径|方案|决定|结论|这个日期|confirm|final)/i;
const RATIONALE_RE =
  /(因为|原因|风险|blocker|卡住|未确认|还没完成|checklist|依赖|迁移窗口|because|risk)/i;
const TIME_RE =
  /(deadline|发布日期|截止日期|目标日期|确认日期|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2})/i;
const STRONG_EVENT_RE =
  /(当前结论|确认|暂定|顺延|改成|不要(?:对外)?说死|先别说死|不是已确认|最终|口径|这个日期|final decision)/i;
const BORING_RE = /(收到|好的|辛苦了|我看下|哈哈|ok|okay|thanks)/i;
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

function traceDecisionClaim(claim: Record<string, unknown>) {
  return {
    claim_field: claim.claim_field ?? null,
    claim_text: claim.claim_text ?? null,
    evidence_quote: claim.evidence_quote ?? null,
    confidence: claim.confidence ?? null,
  };
}

function hashSourceId(value: string): string {
  return crypto.createHash("sha1").update(value).digest("hex").slice(0, 16);
}

function sourceIdFromParams(params: {
  sessionKey?: string;
  sessionId: string;
  sessionFile: string;
}): string {
  return params.sessionKey?.trim() || params.sessionId.trim() || hashSourceId(params.sessionFile);
}

function textForSignal(entry: MemoryTranscriptSpanEntry): string {
  return [entry.messageContent, entry.toolName, entry.toolResult].filter(Boolean).join("\n");
}

function possibleDecisionFields(text: string): string[] {
  const fields = new Set<string>();
  if (TIME_RE.test(text)) {
    fields.add("time_point");
  }
  if (RATIONALE_RE.test(text)) {
    fields.add("rationale");
  }
  if (/(不要(?:对外)?说死|先别说死|不同意|反对|风险提醒|objection)/i.test(text)) {
    fields.add("objection");
  }
  if (/(当前结论|确认|暂定|改成|最终|口径|conclusion)/i.test(text)) {
    fields.add("conclusion");
  }
  if (/(阶段|stage|灰度|发布准备)/i.test(text)) {
    fields.add("stage");
  }
  return [...fields];
}

function runSemanticGate(text: string): {
  should_enqueue: boolean;
  possible_fields: string[];
  reason: string;
  confidence: number;
} {
  const possibleFields = possibleDecisionFields(text);
  const hasDecisionSignal = DECISION_RE.test(text);
  const hasRationaleSignal = RATIONALE_RE.test(text);
  const hasTimeSignal = TIME_RE.test(text);
  const shouldEnqueue =
    possibleFields.length > 0 && (hasDecisionSignal || hasRationaleSignal || hasTimeSignal);
  return {
    should_enqueue: shouldEnqueue,
    possible_fields: possibleFields,
    reason: shouldEnqueue ? "semantic_gate_candidate" : "semantic_gate_reject",
    confidence: shouldEnqueue ? 0.66 : 0.34,
  };
}

function detectTranscriptSignals(entries: MemoryTranscriptSpanEntry[]): SignalDetection {
  let signalStrength = 0;
  let strongEvent = false;
  let hasAnchor = false;
  let hasDecisionLikeSignal = false;
  let allBoring = true;
  const possibleFields = new Set<string>();
  let gateReason: string | null = null;
  let gateConfidence: number | null = null;
  let usedSemanticGate = false;

  for (const entry of entries) {
    const text = textForSignal(entry);
    if (!text.trim()) {
      continue;
    }
    if (!BORING_RE.test(text)) {
      allBoring = false;
    }
    const anchorMatched = TASK_ANCHOR_RE.test(text) || DOC_SYNC_RE.test(text) || PROJECT_RE.test(text);
    const decisionMatched = DECISION_RE.test(text);
    const rationaleMatched = RATIONALE_RE.test(text);
    const timeMatched = TIME_RE.test(text);

    if (anchorMatched) {
      hasAnchor = true;
      signalStrength += 0.35;
    }
    if (decisionMatched) {
      hasDecisionLikeSignal = true;
      signalStrength += 0.35;
    }
    if (rationaleMatched) {
      hasDecisionLikeSignal = true;
      signalStrength += 0.2;
    }
    if (timeMatched) {
      hasDecisionLikeSignal = true;
      signalStrength += 0.2;
    }
    if (STRONG_EVENT_RE.test(text)) {
      strongEvent = true;
      signalStrength += 0.2;
    }
    for (const field of possibleDecisionFields(text)) {
      possibleFields.add(field);
    }
  }

  if (allBoring && !hasAnchor) {
    return {
      dirty: false,
      dirtyReason: "boring_message",
      signalStrength: 0,
      usedSemanticGate: false,
      strongEvent: false,
      possibleFields: [],
      gateReason: null,
      gateConfidence: null,
    };
  }

  if (hasAnchor && hasDecisionLikeSignal) {
    return {
      dirty: true,
      dirtyReason: "decision_memory_candidate",
      signalStrength: Math.min(1, signalStrength),
      usedSemanticGate: false,
      strongEvent,
      possibleFields: [...possibleFields],
      gateReason: null,
      gateConfidence: null,
    };
  }

  const gateText = entries.map((entry) => textForSignal(entry)).join("\n");
  const gate = runSemanticGate(gateText);
  usedSemanticGate = true;
  gateReason = gate.reason;
  gateConfidence = gate.confidence;
  if (!gate.should_enqueue) {
    return {
      dirty: false,
      dirtyReason: gate.reason,
      signalStrength: 0,
      usedSemanticGate,
      strongEvent: false,
      possibleFields: gate.possible_fields,
      gateReason,
      gateConfidence,
    };
  }
  return {
    dirty: true,
    dirtyReason: "decision_memory_candidate",
    signalStrength: Math.max(Math.min(1, signalStrength), gate.confidence),
    usedSemanticGate,
    strongEvent,
    possibleFields: gate.possible_fields,
    gateReason,
    gateConfidence,
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

function renderProjectionBatch(
  sourceId: string,
  entries: MemoryTranscriptSpanEntry[],
): {
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

type ExtractionChunk = {
  entries: MemoryTranscriptSpanEntry[];
  coreEntries: MemoryTranscriptSpanEntry[];
  contextEntries: MemoryTranscriptSpanEntry[];
  coreText: string;
  contextText: string;
  envelope: DecisionExtractionEnvelope;
  rendered: {
    text: string;
    sourceRef: string;
  };
};

const EXTRACTION_CHUNK_ENTRY_LIMIT = 24;
const EXTRACTION_CHUNK_CHAR_LIMIT = 6_000;

function parseStringArrayJson(value: string | null | undefined): string[] {
  if (!value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
      : [];
  } catch {
    return [];
  }
}

function payloadClaimText(payloadJson: string): string | null {
  try {
    const payload = JSON.parse(payloadJson) as Record<string, unknown>;
    return typeof payload.claim_text === "string" && payload.claim_text.trim()
      ? payload.claim_text.trim()
      : null;
  } catch {
    return null;
  }
}

function toPromptEntry(entry: MemoryTranscriptSpanEntry): DecisionPromptEntry {
  return {
    entry_id: entry.entryId,
    parent_id: entry.parentId ?? null,
    role: entry.messageRole?.trim() || entry.entryType,
    content: entry.messageContent.trim(),
    timestamp: entry.timestamp ?? null,
  };
}

function extractAnchorsFromEntries(params: {
  sourceId: string;
  entries: MemoryTranscriptSpanEntry[];
}): DecisionExtractionEnvelope["anchors"] {
  const taskRefs = new Set<string>();
  const threadIds = new Set<string>();
  const docRefs = new Set<string>();
  const projectNames = new Set<string>();
  const sourceChatIds = new Set<string>();
  const docLinkRe = /\/docx\/([A-Za-z0-9]+)/gi;
  const projectNameRe =
    /\b((?:Q[1-4]\s+)?[A-Za-z0-9\u4e00-\u9fff_-]{2,}\s+(?:项目|发布|release))\b/giu;

  if (params.sourceId.trim()) {
    sourceChatIds.add(params.sourceId.trim());
  }
  for (const entry of params.entries) {
    const text = textForSignal(entry);
    for (const match of text.matchAll(/\b[A-Z][A-Z0-9]+-\d+\b/g)) {
      taskRefs.add(`task:${match[0]}`);
    }
    for (const match of text.matchAll(docLinkRe)) {
      docRefs.add(`doc:${match[1]}`);
    }
    for (const match of text.matchAll(projectNameRe)) {
      projectNames.add(match[1].trim());
    }
    if (entry.parentId?.trim()) {
      threadIds.add(entry.parentId.trim());
    }
  }
  return {
    task_refs: [...taskRefs],
    thread_ids: [...threadIds],
    doc_refs: [...docRefs],
    project_names: [...projectNames],
    source_chat_ids: [...sourceChatIds],
  };
}

function summarizeCurrentStateContext(params: {
  store: ReturnType<typeof getCanonicalStore>;
  anchors: DecisionExtractionEnvelope["anchors"];
}): DecisionCurrentStateContext | null {
  const lookups: Array<{ anchorType: "task" | "thread" | "doc" | "project"; anchorRef: string }> = [
    ...params.anchors.task_refs.map((ref) => ({ anchorType: "task" as const, anchorRef: ref.replace(/^task:/, "") })),
    ...params.anchors.thread_ids.map((ref) => ({ anchorType: "thread" as const, anchorRef: ref })),
    ...params.anchors.doc_refs.map((ref) => ({ anchorType: "doc" as const, anchorRef: ref.replace(/^doc:/, "") })),
    ...params.anchors.project_names.map((ref) => ({ anchorType: "project" as const, anchorRef: ref })),
  ];
  for (const lookup of lookups) {
    const state = params.store.findDecisionStatesByAnchor({
      anchorType: lookup.anchorType,
      anchorRef: lookup.anchorRef,
      limit: 1,
    })[0];
    if (!state) {
      continue;
    }
    const eventIds = [
      state.active_conclusion_event_id,
      state.active_stage_event_id,
      ...parseStringArrayJson(state.active_time_point_event_ids_json),
      ...parseStringArrayJson(state.active_rationale_event_ids_json),
      ...parseStringArrayJson(state.active_objection_event_ids_json),
    ].filter((value): value is string => Boolean(value));
    const eventsById = new Map(
      params.store.getEventsByIdsV2(eventIds).map((event) => [event.event_id, event]),
    );
    const claimTexts = (ids: string[]) =>
      ids
        .map((id) => eventsById.get(id))
        .map((event) => (event ? payloadClaimText(event.payload_json) : null))
        .filter((value): value is string => Boolean(value));
    return {
      topic_ref: state.topic_ref,
      decision_axis_key: state.decision_axis_key,
      active_conclusion: state.active_conclusion_event_id
        ? (payloadClaimText(eventsById.get(state.active_conclusion_event_id)?.payload_json ?? "") ?? null)
        : null,
      active_time_points: claimTexts(parseStringArrayJson(state.active_time_point_event_ids_json)),
      active_rationales: claimTexts(parseStringArrayJson(state.active_rationale_event_ids_json)),
      active_objections: claimTexts(parseStringArrayJson(state.active_objection_event_ids_json)),
    };
  }
  return null;
}

function buildContextEntries(params: {
  allEntries: MemoryTranscriptSpanEntry[];
  coreEntries: MemoryTranscriptSpanEntry[];
  anchors: DecisionExtractionEnvelope["anchors"];
}): MemoryTranscriptSpanEntry[] {
  const coreIds = new Set(params.coreEntries.map((entry) => entry.entryId));
  const byId = new Map(params.allEntries.map((entry) => [entry.entryId, entry]));
  const indexById = new Map(params.allEntries.map((entry, index) => [entry.entryId, index]));
  const contextById = new Map<string, MemoryTranscriptSpanEntry>();
  const hasReliableAnchor =
    params.anchors.task_refs.length > 0 ||
    params.anchors.thread_ids.length > 0 ||
    params.anchors.doc_refs.length > 0 ||
    params.anchors.project_names.length > 0;

  const add = (entry: MemoryTranscriptSpanEntry | null | undefined) => {
    if (!entry || coreIds.has(entry.entryId)) {
      return;
    }
    contextById.set(entry.entryId, entry);
  };

  const firstCoreIndex = Math.min(
    ...params.coreEntries.map((entry) => indexById.get(entry.entryId) ?? Number.MAX_SAFE_INTEGER),
  );
  const lastCoreIndex = Math.max(
    ...params.coreEntries.map((entry) => indexById.get(entry.entryId) ?? -1),
  );

  for (const coreEntry of params.coreEntries) {
    let cursor = coreEntry.parentId ? byId.get(coreEntry.parentId) : null;
    while (cursor) {
      add(cursor);
      cursor = cursor.parentId ? byId.get(cursor.parentId) : null;
    }
  }

  if (hasReliableAnchor || params.coreEntries.some((entry) => entry.parentId)) {
    for (let index = Math.max(0, firstCoreIndex - 5); index < firstCoreIndex; index += 1) {
      add(params.allEntries[index]);
    }
    for (
      let index = lastCoreIndex + 1;
      index <= Math.min(params.allEntries.length - 1, lastCoreIndex + 2);
      index += 1
    ) {
      add(params.allEntries[index]);
    }
  }

  return [...contextById.values()].toSorted(
    (left, right) =>
      (indexById.get(left.entryId) ?? 0) - (indexById.get(right.entryId) ?? 0),
  );
}

function renderEntriesText(entries: MemoryTranscriptSpanEntry[]): string {
  return entries.map(renderEntry).filter(Boolean).join("\n");
}

function buildExtractionChunksFromCoreEntries(params: {
  sourceId: string;
  coreEntries: MemoryTranscriptSpanEntry[];
  allEntries: MemoryTranscriptSpanEntry[];
  store: ReturnType<typeof getCanonicalStore>;
}): ExtractionChunk[] {
  const chunks: ExtractionChunk[] = [];
  let current: MemoryTranscriptSpanEntry[] = [];
  let currentChars = 0;
  for (const entry of params.coreEntries) {
    const rendered = renderEntry(entry);
    const nextChars = currentChars + rendered.length + 1;
    const exceedsLimit =
      current.length >= EXTRACTION_CHUNK_ENTRY_LIMIT || nextChars > EXTRACTION_CHUNK_CHAR_LIMIT;
    if (current.length > 0 && exceedsLimit) {
      const anchors = extractAnchorsFromEntries({
        sourceId: params.sourceId,
        entries: params.allEntries,
      });
      const contextEntries = buildContextEntries({
        allEntries: params.allEntries,
        coreEntries: current,
        anchors,
      });
      const envelope: DecisionExtractionEnvelope = {
        anchors,
        current_state_context: summarizeCurrentStateContext({ store: params.store, anchors }),
        context_entries: contextEntries.map(toPromptEntry),
        core_entries: current.map(toPromptEntry),
      };
      chunks.push({
        entries: current,
        coreEntries: current,
        contextEntries,
        coreText: renderEntriesText(current),
        contextText: renderEntriesText(contextEntries),
        envelope,
        rendered: renderProjectionBatch(params.sourceId, current),
      });
      current = [];
      currentChars = 0;
    }
    current.push(entry);
    currentChars += rendered.length + 1;
  }
  if (current.length > 0) {
    const anchors = extractAnchorsFromEntries({
      sourceId: params.sourceId,
      entries: params.allEntries,
    });
    const contextEntries = buildContextEntries({
      allEntries: params.allEntries,
      coreEntries: current,
      anchors,
    });
    const envelope: DecisionExtractionEnvelope = {
      anchors,
      current_state_context: summarizeCurrentStateContext({ store: params.store, anchors }),
      context_entries: contextEntries.map(toPromptEntry),
      core_entries: current.map(toPromptEntry),
    };
    chunks.push({
      entries: current,
      coreEntries: current,
      contextEntries,
      coreText: renderEntriesText(current),
      contextText: renderEntriesText(contextEntries),
      envelope,
      rendered: renderProjectionBatch(params.sourceId, current),
    });
  }
  return chunks;
}

function buildExtractionChunks(params: {
  sourceId: string;
  coreGroups: MemoryTranscriptSpanEntry[][];
  allEntries: MemoryTranscriptSpanEntry[];
  store: ReturnType<typeof getCanonicalStore>;
}): ExtractionChunk[] {
  return params.coreGroups.flatMap((coreEntries) =>
    buildExtractionChunksFromCoreEntries({
      sourceId: params.sourceId,
      coreEntries,
      allEntries: params.allEntries,
      store: params.store,
    }),
  );
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

function parseInboxEntryGroups(rows: ProjectionInboxEntry[]): MemoryTranscriptSpanEntry[][] {
  return rows
    .map((row) => {
      try {
        const parsed = JSON.parse(row.entries_json) as unknown;
        if (!Array.isArray(parsed)) {
          return [];
        }
        return parsed
          .filter((value) => value && typeof value === "object" && !Array.isArray(value))
          .map((value) => {
            const candidate = value as Partial<MemoryTranscriptSpanEntry>;
            return {
              entryId: typeof candidate.entryId === "string" ? candidate.entryId : "",
              parentId: typeof candidate.parentId === "string" ? candidate.parentId : null,
              entryType: candidate.entryType ?? "custom",
              messageRole: typeof candidate.messageRole === "string" ? candidate.messageRole : null,
              messageContent:
                typeof candidate.messageContent === "string" ? candidate.messageContent : "",
              toolName: typeof candidate.toolName === "string" ? candidate.toolName : null,
              toolResult: typeof candidate.toolResult === "string" ? candidate.toolResult : null,
              timestamp: typeof candidate.timestamp === "string" ? candidate.timestamp : null,
            } satisfies MemoryTranscriptSpanEntry;
          })
          .filter((entry) => entry.entryId.trim().length > 0);
      } catch {
        log.warn(`canonical.projection.inbox_group_parse_failed id=${row.id}`);
        return [];
      }
    })
    .filter((group) => group.length > 0);
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
      log.warn(
        `[canonical] projection.async_drain_failed reason=${params.reason} error=${String(err)}`,
      );
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
  if (
    isGraphExtractorSessionKey(params.sessionKey) ||
    isGraphExtractorSessionKey(params.sessionId)
  ) {
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
    summary: `dirty inserted=${inserted} source=${sourceId} reason=${detected.dirtyReason} strength=${detected.signalStrength.toFixed(2)} gate=${detected.usedSemanticGate} strong=${detected.strongEvent}`,
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
        used_semantic_gate: detected.usedSemanticGate,
        strong_event: detected.strongEvent,
        possible_fields: detected.possibleFields,
        gate_reason: detected.gateReason,
        gate_confidence: detected.gateConfidence,
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
  if (
    isGraphExtractorSessionKey(params.sessionKey) ||
    isGraphExtractorSessionKey(params.sessionId)
  ) {
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
      const entryGroups = parseInboxEntryGroups(rows);
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
      const coreGroups = entryGroups
        .map((group) => entriesForExtraction(group))
        .filter((group) => group.length > 0);
      const chunks = buildExtractionChunks({
        sourceId: summary.source_id,
        coreGroups,
        allEntries: extractEntries,
        store,
      });
      const startedAt = Date.now();
      const extractions: Array<{
        chunk: ExtractionChunk;
        extraction: Awaited<ReturnType<typeof extract>>;
      }> = [];
      for (const chunk of chunks) {
        const extraction = await extract(chunk.envelope, chunk.rendered.sourceRef);
        extractions.push({ chunk, extraction });
      }
      const extractionMs = Date.now() - startedAt;
      store.recordExtractorLatency(extractionMs);
      store.bumpMetric("extractSuccesses", 1);
      const extractedClaimCount = extractions.reduce(
        (total, item) => total + item.extraction.claims.length,
        0,
      );
      const extractedDecisionCount = extractions.filter(
        (item) => item.extraction.should_extract,
      ).length;
      parsedEvents += extractedClaimCount;
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.projection.extractor",
        summary: `completed reason=${params.reason} source=${summary.source_id} entries=${entries.length} decisions=${extractedDecisionCount} claims=${extractedClaimCount} latency_ms=${extractionMs}`,
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
            core_groups: coreGroups.length,
            chunks: chunks.length,
            decisions: extractedDecisionCount,
            claims: extractedClaimCount,
            latency_ms: extractionMs,
            rendered_source_refs: chunks.map((chunk) => chunk.rendered.sourceRef),
            envelopes_json: chunks.map((chunk) => ({
              source_ref: chunk.rendered.sourceRef,
              core_entry_ids: chunk.coreEntries.map((entry) => entry.entryId),
              context_entry_ids: chunk.contextEntries.map((entry) => entry.entryId),
              anchors: chunk.envelope.anchors,
              has_current_state_context: chunk.envelope.current_state_context !== null,
            })),
            extractions_json: extractions.map(({ chunk, extraction }) => ({
              source_ref: chunk.rendered.sourceRef,
              should_extract: extraction.should_extract,
              topic_ref: extraction.topic_ref,
              decision_axis_key: extraction.decision_axis_key,
              decision_axis_text: extraction.decision_axis_text,
              claim_count: extraction.claims.length,
              claims: extraction.claims.map((claim) =>
                traceDecisionClaim(claim as unknown as Record<string, unknown>),
              ),
              overflow_warning: extraction.overflow_warning === true,
            })),
          },
          input: {
            ...buildTraceInput(entries),
            extractable_entry_count: extractEntries.length,
            skipped_echo_entry_count: entries.length - extractEntries.length,
            rendered_transcript_refs: chunks.map((chunk) => chunk.rendered.sourceRef),
          },
          call: {
            function: "extract",
            steps: ["buildExtractionChunks", "extract"],
          },
        },
      });
      const canonicalizedChunks = extractions
        .map(({ chunk, extraction }) =>
          canonicalizeV2({
            sourceId: summary.source_id,
            sourceRef: chunk.rendered.sourceRef,
            firstEntryId: chunk.entries[0]?.entryId ?? summary.first_entry_id,
            lastEntryId: chunk.entries.at(-1)?.entryId ?? coveredUntilEntryId,
            text: chunk.rendered.text,
            entries: chunk.entries,
            coreEntries: chunk.coreEntries,
            contextEntries: chunk.contextEntries,
            coreText: chunk.coreText,
            contextText: chunk.contextText,
            extraction,
          }),
        )
        .filter((result) => result.events.length > 0 || result.evidence.length > 0);
      let persistedEventCountForSource = 0;
      if (canonicalizedChunks.length > 0) {
        const persisted = await store.persistSemanticBatchV2({
          evidence: canonicalizedChunks.flatMap((result) => result.evidence),
          events: canonicalizedChunks.flatMap((result) => result.events),
        });
        persistedEventCountForSource = persisted.events.length;
        recordGraphIndexTrace({
          cfg: params.cfg,
          message: "canonical.projection.events_persisted",
          summary: `source=${summary.source_id} records=${persisted.events.length}`,
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
              evidence_records: {
                table: "evidence_records",
                persisted: persisted.evidence.length,
                evidence_ids: persisted.evidence.map((row) => row.evidence_id),
              },
              event_records_v2: {
                table: "event_records_v2",
                persisted: persisted.events.length,
                canonical_records_json: persisted.events.map((record) => ({
                  event_id: record.event_id,
                  event_type: record.event_type,
                  subject_ref: record.subject_ref,
                  actor_ref: record.actor_ref,
                  object_ref: record.object_ref,
                  occurred_at: record.occurred_at,
                  evidence_id: record.evidence_id,
                })),
              },
            },
            call: {
              function: "persistSemanticBatchV2",
              steps: ["canonicalizeV2", "evidence_records", "event_records_v2"],
            },
          },
        });
        recordGraphIndexTrace({
          cfg: params.cfg,
          message: "canonical.projection.kg_objects_derived",
          summary: `source=${summary.source_id} entities=${persisted.entities.length} edges=${persisted.edges.length}`,
          event: {
            trace_id: traceId,
            stage: "kg_objects_derived",
            source_kind: "transcript",
            source_id: summary.source_id,
            entry_range: {
              first: summary.first_entry_id,
              last: coveredUntilEntryId,
            },
            tables: {
              graph_entities_v2: {
                table: "graph_entities_v2",
                persisted: persisted.entities.length,
                entities: persisted.entities,
              },
              graph_edges_v2: {
                table: "graph_edges_v2",
                persisted: persisted.edges.length,
                edges: persisted.edges,
              },
            },
            call: {
              function: "persistSemanticBatchV2",
              steps: ["graph_entities_v2", "graph_edges_v2"],
            },
          },
        });
        recordGraphIndexTrace({
          cfg: params.cfg,
          message: "canonical.projection.entity_states_merged",
          summary: `source=${summary.source_id} states=${persisted.decisionStates.length}`,
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
              decision_state_view_v2: {
                table: "decision_state_view_v2",
                merged: persisted.decisionStates.length,
                next_states: persisted.decisionStates,
              },
            },
            call: {
              function: "persistSemanticBatchV2",
              steps: ["decision_state_view_v2 upsert"],
            },
          },
        });
        persistedEvents += persisted.events.length;
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
              event_records_v2: {
                persisted: 0,
              },
              evidence_records: {
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
        summary: `reason=${params.reason} source=${summary.source_id} entries=${entries.length} claims=${extractedClaimCount} persisted=${persistedEventCountForSource} covered_until=${coveredUntilEntryId}`,
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
      const extractorErrorCode = getGraphExtractorErrorCode(err) ?? "unknown";
      store.bumpMetric("extractFailures", 1);
      store.markProjectionFailed(summary.source_id);
      if (params.reason === "pre_compaction") {
        store.recordKgRetryMarker({
          scope: `pre_compaction:${summary.source_id}`,
          status: "failed",
          error: String(err),
          retryMarker: {
            source_id: summary.source_id,
            first_entry_id: summary.first_entry_id,
            last_entry_id: summary.last_entry_id,
            reason: params.reason,
            error_code: extractorErrorCode,
          },
        });
      }
      recordGraphIndexTrace({
        cfg: params.cfg,
        message: "canonical.projection.drain_failed",
        summary: `reason=${params.reason} source=${summary.source_id} error_code=${extractorErrorCode} error=${String(err)}`,
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
            error_code: extractorErrorCode,
          },
          error: String(err),
        },
      });
      log.warn(
        `[canonical] projection.drain_failed reason=${params.reason} source=${summary.source_id} error_code=${extractorErrorCode} error=${String(err)}`,
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
