import type { MemoryTranscriptSpanEntry } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import {
  canonicalJson,
  normalizeName,
  normalizeWhitespace,
  sha1,
} from "./id-v2.js";
import {
  buildTaskSessionEventFingerprint,
  buildEvidenceFingerprint,
  type EvidenceRecordV2,
  type EventRecordV2,
} from "./schema-v2.js";
import {
  EXTRACTOR_VERSION,
  type DecisionAxisKey,
  type DecisionClaimField,
  type DecisionClaimValueJson,
  type DecisionExtractionResult,
  type ExtractedDecisionClaim,
  type DecisionSupportingContextQuote,
} from "./schema.js";

const CLAIM_FIELD_SET = new Set<DecisionClaimField>([
  "conclusion",
  "rationale",
  "objection",
  "stage",
  "time_point",
]);

const DECISION_AXIS_KEY_SET = new Set<DecisionAxisKey>([
  "release_date",
  "solution_choice",
  "gray_release_plan",
  "dependency_readiness",
  "external_communication",
  "project_stage",
  "risk_handling",
  "general_decision",
]);

const CLAIM_CONFIDENCE_THRESHOLD = 0.55;
const MAX_VALID_CLAIMS_PER_BATCH = 20;
const TASK_REF_RE = /\b([A-Z][A-Z0-9]+-\d+)\b/g;
const DOC_TOKEN_RE = /\b([A-Za-z0-9]{16,})\b/;
const ACK_ONLY_RE = /^(收到|好的|我看下|了解|ok|okay|thanks|辛苦了)[。！!，,\s]*$/iu;
const CORE_ACTION_RE =
  /(先按|按这个来|按刚才的来|不要(?:对外)?说死|先别说死|不是已确认|暂定|确认|顺延|改成|最终|口径|结论|风险|blocker|未锁定|还没锁定|延期|推迟|不同意|反对|这个日期|那个日期)/iu;

type TopicAnchorType = "task" | "thread" | "doc" | "project";

type TopicAnchorSelection = {
  anchorType: TopicAnchorType;
  anchorId: string;
  topicAnchorsJson: Record<string, unknown>;
};

type CanonicalizeV2Params = {
  sourceId: string;
  sourceRef: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
  text: string;
  entries: MemoryTranscriptSpanEntry[];
  coreEntries?: MemoryTranscriptSpanEntry[];
  contextEntries?: MemoryTranscriptSpanEntry[];
  coreText?: string;
  contextText?: string;
  extraction: DecisionExtractionResult;
  sourcePlatform?: EvidenceRecordV2["source_platform"];
  sourceKind?: EvidenceRecordV2["source_kind"];
};

export type CanonicalizeV2Result = {
  evidence: EvidenceRecordV2[];
  events: EventRecordV2[];
  overflowWarning: boolean;
};

function shortHash(value: string): string {
  return sha1(value).slice(0, 12);
}

function normalizeTaskRef(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.startsWith("task:")) {
    return trimmed;
  }
  const match = trimmed.match(/\b([A-Z][A-Z0-9]+-\d+)\b/);
  return match ? `task:${match[1]}` : null;
}

function normalizeThreadId(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function normalizeDocRef(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.startsWith("doc:")) {
    return trimmed;
  }
  const urlMatch = trimmed.match(/\/docx\/([A-Za-z0-9]+)/i);
  if (urlMatch) {
    return `doc:${urlMatch[1]}`;
  }
  const tokenMatch = trimmed.match(DOC_TOKEN_RE);
  return tokenMatch ? `doc:${tokenMatch[1]}` : null;
}

function normalizeProjectName(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = normalizeWhitespace(value);
  return normalized || null;
}

function normalizeAnchorArray(
  value: unknown,
  normalizer: (value: unknown) => string | null,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.map((entry) => normalizer(entry)).filter((entry): entry is string => Boolean(entry)))];
}

function normalizeTopicAnchors(value: unknown): Record<string, unknown> {
  const record =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const taskRefs = normalizeAnchorArray(record.task_refs, normalizeTaskRef);
  const threadIds = normalizeAnchorArray(record.thread_ids, normalizeThreadId);
  const docRefs = normalizeAnchorArray(record.doc_refs, normalizeDocRef);
  const projectNames = normalizeAnchorArray(record.project_names, normalizeProjectName);
  const sourceChatIds = normalizeAnchorArray(record.source_chat_ids, normalizeThreadId);
  return {
    task_refs: taskRefs,
    thread_ids: threadIds,
    doc_refs: docRefs,
    project_names: projectNames,
    source_chat_ids: sourceChatIds,
  };
}

function normalizeAnchorIdentifier(anchorType: TopicAnchorType, anchorValue: string): string {
  if (anchorType === "task") {
    return anchorValue.replace(/^task:/, "");
  }
  if (anchorType === "doc") {
    return anchorValue.replace(/^doc:/, "");
  }
  if (anchorType === "project") {
    return shortHash(normalizeName(anchorValue));
  }
  return anchorValue;
}

function selectCanonicalAnchor(topicAnchorsJson: Record<string, unknown>): TopicAnchorSelection | null {
  const taskRefs = topicAnchorsJson.task_refs as string[];
  const threadIds = topicAnchorsJson.thread_ids as string[];
  const docRefs = topicAnchorsJson.doc_refs as string[];
  const projectNames = topicAnchorsJson.project_names as string[];
  if (taskRefs.length > 1) {
    return null;
  }
  if (taskRefs.length === 1) {
    return {
      anchorType: "task",
      anchorId: normalizeAnchorIdentifier("task", taskRefs[0]),
      topicAnchorsJson,
    };
  }
  if (threadIds.length === 1) {
    return {
      anchorType: "thread",
      anchorId: normalizeAnchorIdentifier("thread", threadIds[0]),
      topicAnchorsJson,
    };
  }
  if (docRefs.length === 1) {
    return {
      anchorType: "doc",
      anchorId: normalizeAnchorIdentifier("doc", docRefs[0]),
      topicAnchorsJson,
    };
  }
  if (projectNames.length === 1) {
    return {
      anchorType: "project",
      anchorId: normalizeAnchorIdentifier("project", projectNames[0]),
      topicAnchorsJson,
    };
  }
  return null;
}

function canonicalTopicRef(params: {
  anchor: TopicAnchorSelection;
  decisionAxisKey: DecisionAxisKey;
  decisionAxisText: string;
  decisionAxisInstanceId: string | null;
}): { topicRef: string; decisionAxisInstanceId: string | null } {
  if (params.decisionAxisKey === "general_decision") {
    const instanceId =
      params.decisionAxisInstanceId?.trim() ||
      shortHash(
        `${params.anchor.anchorType}:${params.anchor.anchorId}|${normalizeName(
          params.decisionAxisText,
        )}`,
      );
    return {
      topicRef: `topic:${params.anchor.anchorType}:${params.anchor.anchorId}:general_decision:${instanceId}`,
      decisionAxisInstanceId: instanceId,
    };
  }
  return {
    topicRef: `topic:${params.anchor.anchorType}:${params.anchor.anchorId}:${params.decisionAxisKey}`,
    decisionAxisInstanceId: null,
  };
}

function occurredAtForBatch(entries: MemoryTranscriptSpanEntry[]): string {
  const latest = entries
    .map((entry) => entry.timestamp)
    .filter((value): value is string => Boolean(value))
    .toSorted()
    .at(-1);
  return latest ?? new Date().toISOString();
}

function findEvidenceQuoteInText(text: string, quote: string): string | null {
  const trimmedQuote = quote.trim();
  if (!trimmedQuote) {
    return null;
  }
  if (text.includes(trimmedQuote)) {
    return trimmedQuote;
  }
  const normalizedText = normalizeWhitespace(text);
  const normalizedQuote = normalizeWhitespace(trimmedQuote);
  return normalizedText.includes(normalizedQuote) ? trimmedQuote : null;
}

function quoteHasNewSemanticAction(quote: string): boolean {
  const normalized = normalizeWhitespace(quote);
  if (!normalized || ACK_ONLY_RE.test(normalized)) {
    return false;
  }
  return CORE_ACTION_RE.test(normalized);
}

function validateClaimTextSupport(
  claimText: string,
  evidenceQuote: string,
  supportingQuotes: string[] = [],
): boolean {
  const normalizedClaim = normalizeWhitespace(claimText);
  const normalizedQuote = normalizeWhitespace(evidenceQuote);
  if (!normalizedClaim || !normalizedQuote) {
    return false;
  }
  const normalizedSupporting = supportingQuotes
    .map((quote) => normalizeWhitespace(quote))
    .filter(Boolean);
  const combinedSupport = [normalizedQuote, ...normalizedSupporting].join(" ");
  if (normalizedClaim.length > combinedSupport.length + 120) {
    return false;
  }
  const quoteTokens = new Set(
    combinedSupport
      .toLowerCase()
      .split(/[^a-z0-9\u4e00-\u9fff]+/u)
      .filter(Boolean),
  );
  if (quoteTokens.size === 0) {
    return false;
  }
  const claimTokens = normalizedClaim
    .toLowerCase()
    .split(/[^a-z0-9\u4e00-\u9fff]+/u)
    .filter(Boolean);
  return claimTokens.some((token) => quoteTokens.has(token));
}

function parseClaimValueJson(
  value: ExtractedDecisionClaim["claim_value_json"],
): DecisionClaimValueJson | null {
  return value && typeof value === "object" ? value : null;
}

function resolveEntryQuoteMatches(
  entries: MemoryTranscriptSpanEntry[],
  quote: string,
): Array<{ entry: MemoryTranscriptSpanEntry; index: number }> {
  const matches: Array<{ entry: MemoryTranscriptSpanEntry; index: number }> = [];
  for (const [index, entry] of entries.entries()) {
    if (findEvidenceQuoteInText(entry.messageContent, quote)) {
      matches.push({ entry, index });
    }
  }
  return matches;
}

function resolveCoreQuote(params: {
  coreEntries: MemoryTranscriptSpanEntry[];
  evidenceQuote: string;
  claimValueJson: DecisionClaimValueJson | null;
}): { quote: string; entryId: string } | null {
  const matches = resolveEntryQuoteMatches(params.coreEntries, params.evidenceQuote);
  if (matches.length === 0) {
    return null;
  }
  const requestedEntryId =
    typeof params.claimValueJson?.core_entry_id === "string" && params.claimValueJson.core_entry_id.trim()
      ? params.claimValueJson.core_entry_id.trim()
      : null;
  if (requestedEntryId) {
    const requested = matches.find(({ entry }) => entry.entryId === requestedEntryId);
    return requested
      ? { quote: params.evidenceQuote.trim(), entryId: requested.entry.entryId }
      : null;
  }
  const [best] = matches.toSorted((left, right) => {
    if (left.index !== right.index) {
      return right.index - left.index;
    }
    return left.entry.messageContent.length - right.entry.messageContent.length;
  });
  return best ? { quote: params.evidenceQuote.trim(), entryId: best.entry.entryId } : null;
}

function resolveSupportingContextQuotes(params: {
  contextEntries: MemoryTranscriptSpanEntry[];
  quotes: DecisionSupportingContextQuote[];
}): Array<{ quote: string; entryId: string; source: "context" }> {
  const resolved: Array<{ quote: string; entryId: string; source: "context" }> = [];
  for (const quote of params.quotes) {
    if (quote.source !== "context") {
      continue;
    }
    const matches = resolveEntryQuoteMatches(params.contextEntries, quote.quote);
    if (matches.length === 0) {
      continue;
    }
    const requestedEntryId =
      typeof quote.entry_id === "string" && quote.entry_id.trim() ? quote.entry_id.trim() : null;
    const selected =
      (requestedEntryId
        ? matches.find(({ entry }) => entry.entryId === requestedEntryId)
        : null) ??
      matches.toSorted((left, right) => {
        if (left.index !== right.index) {
          return right.index - left.index;
        }
        return left.entry.messageContent.length - right.entry.messageContent.length;
      })[0];
    if (!selected) {
      continue;
    }
    resolved.push({
      quote: quote.quote.trim(),
      entryId: selected.entry.entryId,
      source: "context",
    });
  }
  return resolved;
}

function eventObjectRefForClaim(
  claim: ExtractedDecisionClaim,
): string | null {
  if (claim.claim_field === "time_point") {
    const dateValue = claim.claim_value_json?.date;
    return typeof dateValue === "string" && dateValue.trim() ? `date:${dateValue.trim()}` : null;
  }
  if (claim.claim_field === "stage") {
    return `stage:${shortHash(normalizeName(claim.claim_text))}`;
  }
  return null;
}

function taskEventTypeForClaimField(
  claimField: DecisionClaimField,
): EventRecordV2["event_type"] {
  switch (claimField) {
    case "conclusion":
      return "conclusion_event";
    case "rationale":
      return "rationale_event";
    case "objection":
      return "objection_event";
    case "stage":
      return "scope_event";
    case "time_point":
      return "time_event";
  }
}

function relatedRefsForClaim(
  anchor: TopicAnchorSelection,
  claim: ExtractedDecisionClaim,
): string[] {
  const refs = new Set<string>();
  const anchors = anchor.topicAnchorsJson;
  for (const taskRef of anchors.task_refs as string[]) {
    refs.add(taskRef);
  }
  for (const threadId of anchors.thread_ids as string[]) {
    refs.add(`thread:${threadId}`);
  }
  for (const docRef of anchors.doc_refs as string[]) {
    refs.add(docRef);
  }
  for (const projectName of anchors.project_names as string[]) {
    refs.add(`project:${shortHash(normalizeName(projectName))}`);
  }
  const objectRef = eventObjectRefForClaim(claim);
  if (objectRef) {
    refs.add(objectRef);
  }
  return [...refs];
}

function sourceLocatorJson(params: {
  sourceId: string;
  sourceRef: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
  evidenceQuote: string;
  claimField: DecisionClaimField;
}): string {
  return canonicalJson({
    source_id: params.sourceId,
    source_ref: params.sourceRef,
    first_entry_id: params.firstEntryId ?? null,
    last_entry_id: params.lastEntryId ?? null,
    evidence_quote: params.evidenceQuote,
    claim_field: params.claimField,
  });
}

function deterministicEvidenceId(params: {
  sourceLocatorJson: string;
  evidenceQuote: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
}): string {
  return `evidence:${shortHash(
    [
      params.sourceLocatorJson,
      normalizeWhitespace(params.evidenceQuote),
      params.firstEntryId ?? "",
      params.lastEntryId ?? "",
    ].join("|"),
  )}`;
}

function extractTaskRefsFromText(text: string): string[] {
  return [...new Set([...text.matchAll(TASK_REF_RE)].map((match) => `task:${match[1]}`))];
}

function addFallbackTaskAnchor(
  topicAnchorsJson: Record<string, unknown>,
  text: string,
): Record<string, unknown> {
  const taskRefs = topicAnchorsJson.task_refs as string[];
  if (taskRefs.length > 0) {
    return topicAnchorsJson;
  }
  const fallbackTaskRefs = extractTaskRefsFromText(text);
  if (fallbackTaskRefs.length !== 1) {
    return topicAnchorsJson;
  }
  return {
    ...topicAnchorsJson,
    task_refs: fallbackTaskRefs,
  };
}

function asDecisionAxisKey(value: string | null): DecisionAxisKey | null {
  if (!value || !DECISION_AXIS_KEY_SET.has(value as DecisionAxisKey)) {
    return null;
  }
  return value as DecisionAxisKey;
}

function asClaimField(value: string): DecisionClaimField | null {
  return CLAIM_FIELD_SET.has(value as DecisionClaimField)
    ? (value as DecisionClaimField)
    : null;
}

export function canonicalizeV2(params: CanonicalizeV2Params): CanonicalizeV2Result {
  const extraction = params.extraction;
  if (!extraction.should_extract) {
    return { evidence: [], events: [], overflowWarning: false };
  }

  const decisionAxisKey = asDecisionAxisKey(extraction.decision_axis_key);
  const decisionAxisText = normalizeWhitespace(extraction.decision_axis_text ?? "");
  if (!decisionAxisKey || !decisionAxisText) {
    return { evidence: [], events: [], overflowWarning: false };
  }

  const normalizedAnchors = addFallbackTaskAnchor(
    normalizeTopicAnchors(extraction.topic_anchors_json),
    params.text,
  );
  const taskRef = (normalizedAnchors.task_refs as string[])[0] ?? null;
  if (!taskRef) {
    return { evidence: [], events: [], overflowWarning: false };
  }
  const anchor = selectCanonicalAnchor(normalizedAnchors);
  if (!anchor) {
    return { evidence: [], events: [], overflowWarning: false };
  }

  const topic = canonicalTopicRef({
    anchor,
    decisionAxisKey,
    decisionAxisText,
    decisionAxisInstanceId:
      typeof extraction.decision_axis_instance_id === "string"
        ? extraction.decision_axis_instance_id.trim()
        : null,
  });
  const occurredAt = occurredAtForBatch(params.entries);
  const coreEntries = params.coreEntries ?? params.entries;
  const contextEntries = params.contextEntries ?? [];
  const validClaims: Array<
    ExtractedDecisionClaim & {
      resolved_core_entry_id: string;
      supporting_context_quotes: Array<{ quote: string; entryId: string; source: "context" }>;
    }
  > = [];

  for (const claim of extraction.claims) {
    const claimField = asClaimField(claim.claim_field);
    if (!claimField) {
      continue;
    }
    if (!Number.isFinite(claim.confidence) || claim.confidence < CLAIM_CONFIDENCE_THRESHOLD) {
      continue;
    }
    const claimText = normalizeWhitespace(claim.claim_text);
    if (!claimText) {
      continue;
    }
    const claimValueJson = parseClaimValueJson(claim.claim_value_json);
    const evidenceQuote = findEvidenceQuoteInText(params.coreText ?? params.text, claim.evidence_quote);
    if (!evidenceQuote || !quoteHasNewSemanticAction(evidenceQuote)) {
      continue;
    }
    const resolvedCoreQuote = resolveCoreQuote({
      coreEntries,
      evidenceQuote,
      claimValueJson,
    });
    if (!resolvedCoreQuote) {
      continue;
    }
    const supportingContextQuotes = resolveSupportingContextQuotes({
      contextEntries,
      quotes: Array.isArray(claimValueJson?.supporting_context_quotes)
        ? (claimValueJson.supporting_context_quotes as DecisionSupportingContextQuote[])
        : [],
    });
    const supportingQuoteTexts = supportingContextQuotes.map((quote) => quote.quote);
    if (!validateClaimTextSupport(claimText, evidenceQuote, supportingQuoteTexts)) {
      continue;
    }
    validClaims.push({
      claim_field: claimField,
      claim_text: claimText,
      claim_value_json: claimValueJson,
      evidence_quote: evidenceQuote,
      confidence: claim.confidence,
      resolved_core_entry_id: resolvedCoreQuote.entryId,
      supporting_context_quotes: supportingContextQuotes,
    });
  }

  if (validClaims.length === 0) {
    return { evidence: [], events: [], overflowWarning: false };
  }

  const overflowWarning = validClaims.length > MAX_VALID_CLAIMS_PER_BATCH;
  const acceptedClaims = validClaims.slice(0, MAX_VALID_CLAIMS_PER_BATCH);
  const evidence: EvidenceRecordV2[] = [];
  const events: EventRecordV2[] = [];
  const now = Date.now();

  for (const claim of acceptedClaims) {
    const locatorJson = sourceLocatorJson({
      sourceId: params.sourceId,
      sourceRef: params.sourceRef,
      firstEntryId: claim.resolved_core_entry_id,
      lastEntryId: claim.resolved_core_entry_id,
      evidenceQuote: claim.evidence_quote,
      claimField: claim.claim_field,
    });
    const evidenceId = deterministicEvidenceId({
      sourceLocatorJson: locatorJson,
      evidenceQuote: claim.evidence_quote,
      firstEntryId: claim.resolved_core_entry_id,
      lastEntryId: claim.resolved_core_entry_id,
    });
    const evidenceContentJson = {
      quote: claim.evidence_quote,
      full_source_ref: params.sourceRef,
      claim_field: claim.claim_field,
      decision_axis_key: decisionAxisKey,
      decision_axis_text: decisionAxisText,
      topic_ref: topic.topicRef,
      resolved_core_entry_id: claim.resolved_core_entry_id,
      supporting_context_entry_ids: claim.supporting_context_quotes.map((quote) => quote.entryId),
    };
    const evidenceRow: EvidenceRecordV2 = {
      evidence_id: evidenceId,
      evidence_fingerprint: buildEvidenceFingerprint({
        sourcePlatform: params.sourcePlatform ?? "transcript",
        sourceKind: params.sourceKind ?? "transcript_span",
        sessionKey: params.sourceId,
        firstEntryId: claim.resolved_core_entry_id,
        lastEntryId: claim.resolved_core_entry_id,
        occurredAt,
        contentText: claim.evidence_quote,
        contentJson: evidenceContentJson,
      }),
      source_platform: params.sourcePlatform ?? "transcript",
      source_kind: params.sourceKind ?? "transcript_span",
      session_key: params.sourceId,
      message_id: null,
      chat_id: null,
      chat_type: null,
      thread_id:
        anchor.anchorType === "thread"
          ? anchor.anchorId
          : (normalizedAnchors.thread_ids as string[])[0] ?? null,
      root_id: null,
      parent_id: null,
      first_entry_id: claim.resolved_core_entry_id,
      last_entry_id: claim.resolved_core_entry_id,
      content_text: claim.evidence_quote,
      content_json: canonicalJson(evidenceContentJson),
      source_locator_json: locatorJson,
      occurred_at: occurredAt,
      created_at: now,
      linked_event_ids_json: null,
    };
    evidence.push(evidenceRow);

    const eventType = taskEventTypeForClaimField(claim.claim_field);
    const payloadJson = {
      task_ref: taskRef,
      topic_ref: topic.topicRef,
      topic_anchors_json: normalizedAnchors,
      slot_key: claim.claim_field,
      claim: claim.claim_text,
      claim_value: {
        ...(claim.claim_value_json ?? {}),
        core_entry_id: claim.resolved_core_entry_id,
        supporting_context_quotes: claim.supporting_context_quotes.map((quote) => ({
          quote: quote.quote,
          entry_id: quote.entryId,
          source: quote.source,
        })),
      },
      evidence_quote: claim.evidence_quote,
      confidence: claim.confidence,
      evidence_fingerprint: evidenceRow.evidence_fingerprint,
    };
    const objectRef = eventObjectRefForClaim(claim);
    events.push({
      event_id: `event:${shortHash(
        [
          taskRef,
          eventType,
          claim.claim_text,
          evidenceId,
        ].join("|"),
      )}`,
      event_fingerprint: buildTaskSessionEventFingerprint({
        taskRef,
        eventType,
        claimText: claim.claim_text,
        evidenceId,
      }),
      evidence_id: evidenceId,
      event_type: eventType,
      subject_ref: taskRef,
      actor_ref: null,
      object_ref: objectRef,
      related_refs_json: canonicalJson(relatedRefsForClaim(anchor, claim)),
      occurred_at: occurredAt,
      payload_json: canonicalJson(payloadJson),
      confidence: claim.confidence,
      extraction_version: EXTRACTOR_VERSION,
      created_at: now,
    });
  }

  return {
    evidence,
    events,
    overflowWarning,
  };
}
