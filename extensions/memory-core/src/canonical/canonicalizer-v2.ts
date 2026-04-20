import type { MemoryTranscriptSpanEntry } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import { generateUlid, normalizeName, normalizeWhitespace } from "./id-v2.js";
import {
  buildEvidenceFingerprint,
  buildEventFingerprint,
  normalizeBlockerRef,
  normalizeTypedPersonRef,
  type EvidenceRecordV2,
  type EventRecordV2,
  type V2EventType,
} from "./schema-v2.js";
import { EXTRACTOR_VERSION, type RawEvent } from "./schema.js";

const TASK_REF_RE = /\b([A-Z][A-Z0-9]+-\d+)\b/g;
const APPROVAL_REF_RE = /\b(AP-\d+)\b/g;

type CanonicalizeV2Params = {
  sourceId: string;
  sourceRef: string;
  firstEntryId?: string | null;
  lastEntryId?: string | null;
  text: string;
  entries: MemoryTranscriptSpanEntry[];
  rawEvents: RawEvent[];
  sourcePlatform?: EvidenceRecordV2["source_platform"];
  sourceKind?: EvidenceRecordV2["source_kind"];
};

export type CanonicalizeV2Result = {
  evidence: EvidenceRecordV2;
  events: EventRecordV2[];
};

function collectMatches(pattern: RegExp, text: string): string[] {
  const matches = [...text.matchAll(pattern)].map((match) => match[1]);
  return [...new Set(matches)];
}

function lastOccurredAt(entries: MemoryTranscriptSpanEntry[], rawEvents: RawEvent[]): string {
  const candidates = [
    ...rawEvents
      .map((event) => event.occurred_at)
      .filter((value): value is string => Boolean(value)),
    ...entries.map((entry) => entry.timestamp).filter((value): value is string => Boolean(value)),
  ];
  const latest = candidates.toSorted().at(-1);
  return latest ?? new Date().toISOString();
}

function evidenceSourceLocator(params: CanonicalizeV2Params): string {
  return JSON.stringify({
    source_ref: params.sourceRef,
    source_id: params.sourceId,
    first_entry_id: params.firstEntryId ?? null,
    last_entry_id: params.lastEntryId ?? null,
  });
}

function buildEvidence(params: CanonicalizeV2Params): EvidenceRecordV2 {
  const occurredAt = lastOccurredAt(params.entries, params.rawEvents);
  const contentJson = {
    entries: params.entries,
  };
  const evidenceFingerprint = buildEvidenceFingerprint({
    sourcePlatform: params.sourcePlatform ?? "transcript",
    sourceKind: params.sourceKind ?? "transcript_span",
    sessionKey: params.sourceId,
    firstEntryId: params.firstEntryId,
    lastEntryId: params.lastEntryId,
    occurredAt,
    contentText: params.text,
    contentJson,
  });
  return {
    evidence_id: generateUlid(),
    evidence_fingerprint: evidenceFingerprint,
    source_platform: params.sourcePlatform ?? "transcript",
    source_kind: params.sourceKind ?? "transcript_span",
    session_key: params.sourceId,
    message_id: null,
    chat_id: null,
    chat_type: null,
    thread_id: null,
    root_id: null,
    parent_id: null,
    first_entry_id: params.firstEntryId ?? null,
    last_entry_id: params.lastEntryId ?? null,
    content_text: params.text,
    content_json: JSON.stringify(contentJson),
    source_locator_json: evidenceSourceLocator(params),
    occurred_at: occurredAt,
    created_at: Date.now(),
  };
}

function inferTaskRef(text: string): string | null {
  const [task] = collectMatches(TASK_REF_RE, text);
  return task ? `task:${task}` : null;
}

function inferLooseTaskRef(text: string | undefined): string | null {
  const normalized = normalizeWhitespace(text ?? "");
  if (!normalized || /\s/.test(normalized)) {
    return null;
  }
  if (normalized.toUpperCase().startsWith("AP-")) {
    return null;
  }
  return `task:${normalized}`;
}

function inferApprovalRef(text: string): string | null {
  const [approval] = collectMatches(APPROVAL_REF_RE, text);
  return approval ? `approval:${approval}` : null;
}

function inferPersonRef(text: string | undefined, fallbackName?: string | null): string | null {
  const actorRef = normalizeTypedPersonRef({ name: text ?? fallbackName ?? null });
  return actorRef;
}

function inferEventType(event: RawEvent, evidenceText: string): V2EventType | null {
  const action = normalizeName(event.action);
  const object = normalizeName(event.object ?? "");
  const status = normalizeName(event.status_after ?? "");
  const combined = `${action} ${object} ${status} ${normalizeName(evidenceText)}`;
  if (action.includes("assigned_owner")) {
    return "owner_changed";
  }
  if (action.includes("changed_status") && status === "blocked") {
    return "blocked";
  }
  if (action.includes("changed_status") && (status === "resolved" || status === "unblocked")) {
    return "unblocked";
  }
  if (action.includes("changed_status")) {
    return "stage_changed";
  }
  if (
    combined.includes("approved") ||
    combined.includes("rejected") ||
    combined.includes("approval")
  ) {
    return "approval_status_updated";
  }
  if (
    combined.includes("next action") ||
    combined.includes("next_action") ||
    combined.includes("下一步")
  ) {
    return "next_action_set";
  }
  if (combined.includes("blocked") || combined.includes("dependency") || combined.includes("卡")) {
    return "blocked";
  }
  return null;
}

function payloadForEvent(params: {
  eventType: V2EventType;
  rawEvent: RawEvent;
  evidenceText: string;
  subjectRef: string;
  objectRef: string | null;
  actorRef: string | null;
}): Record<string, unknown> {
  const { eventType, rawEvent, evidenceText, objectRef, actorRef } = params;
  switch (eventType) {
    case "owner_changed":
      return {
        new_owner_ref: objectRef ?? actorRef,
        reason: normalizeWhitespace(evidenceText),
      };
    case "stage_changed":
      return {
        new_stage: rawEvent.status_after ?? normalizeWhitespace(rawEvent.action),
        previous_stage: rawEvent.status_before ?? null,
      };
    case "approval_status_updated":
      return {
        approval_ref: objectRef,
        approval_status:
          rawEvent.status_after ??
          (normalizeName(evidenceText).includes("approved") ? "approved" : "pending"),
      };
    case "blocked":
      return {
        blocker_ref: objectRef,
        blocker_reason: normalizeWhitespace(rawEvent.object ?? evidenceText),
      };
    case "unblocked":
      return {
        blocker_ref: objectRef,
        blocker_reason: normalizeWhitespace(rawEvent.object ?? evidenceText),
      };
    case "next_action_set":
      return {
        assignee_ref: actorRef,
        action_text: normalizeWhitespace(rawEvent.object ?? evidenceText),
      };
    default:
      return {};
  }
}

function refsForRawEvent(
  event: RawEvent,
  evidenceText: string,
): {
  subjectRef: string | null;
  actorRef: string | null;
  objectRef: string | null;
  relatedRefs: string[];
} {
  const baseText = `${event.object ?? ""} ${evidenceText}`;
  const taskRef = inferTaskRef(baseText) ?? inferLooseTaskRef(event.object);
  const approvalRef = inferApprovalRef(baseText);
  const actorRef = inferPersonRef(event.actor);
  const objectPersonRef = inferPersonRef(event.object, event.actor);
  const relatedRefs = [taskRef, approvalRef, actorRef, objectPersonRef].filter(
    (value): value is string => Boolean(value),
  );

  if (approvalRef && normalizeName(event.action).includes("approval")) {
    return {
      subjectRef: taskRef ?? approvalRef,
      actorRef,
      objectRef: approvalRef,
      relatedRefs,
    };
  }

  const blockedByApproval = normalizeName(baseText).includes("ap-") ? approvalRef : null;
  return {
    subjectRef: taskRef,
    actorRef,
    objectRef:
      blockedByApproval ??
      (normalizeName(event.action).includes("assigned_owner")
        ? (objectPersonRef ?? actorRef)
        : null),
    relatedRefs,
  };
}

function fallbackBlockedRef(event: RawEvent, evidenceText: string): string {
  const approvalRef = inferApprovalRef(`${event.object ?? ""} ${evidenceText}`);
  if (approvalRef) {
    return approvalRef;
  }
  return normalizeBlockerRef(event.object ?? evidenceText);
}

export function canonicalizeV2(params: CanonicalizeV2Params): CanonicalizeV2Result {
  const evidence = buildEvidence(params);
  const occurredAtDefault = evidence.occurred_at ?? new Date().toISOString();
  const events: EventRecordV2[] = [];
  const seen = new Set<string>();

  for (const rawEvent of params.rawEvents) {
    const eventType = inferEventType(rawEvent, params.text);
    if (!eventType) {
      continue;
    }
    const refs = refsForRawEvent(rawEvent, params.text);
    const subjectRef =
      refs.subjectRef ??
      (eventType === "approval_status_updated" ? inferTaskRef(params.text) : null);
    if (!subjectRef) {
      continue;
    }
    let objectRef = refs.objectRef;
    if (eventType === "approval_status_updated") {
      objectRef = inferApprovalRef(`${rawEvent.object ?? ""} ${params.text}`) ?? objectRef;
    }
    if (eventType === "blocked") {
      objectRef = objectRef ?? fallbackBlockedRef(rawEvent, params.text);
    }
    const payloadJson = payloadForEvent({
      eventType,
      rawEvent,
      evidenceText: params.text,
      subjectRef,
      objectRef,
      actorRef: refs.actorRef,
    });
    const occurredAt = rawEvent.occurred_at?.trim() || occurredAtDefault;
    const eventFingerprint = buildEventFingerprint({
      evidenceId: evidence.evidence_id,
      eventType,
      subjectRef,
      objectRef,
      occurredAt,
      payloadJson,
    });
    if (seen.has(eventFingerprint)) {
      continue;
    }
    seen.add(eventFingerprint);
    const relatedRefs = [
      ...new Set(refs.relatedRefs.filter((ref) => ref !== subjectRef && ref !== objectRef)),
    ];
    events.push({
      event_id: generateUlid(),
      event_fingerprint: eventFingerprint,
      evidence_id: evidence.evidence_id,
      event_type: eventType,
      subject_ref: subjectRef,
      actor_ref: refs.actorRef,
      object_ref: objectRef ?? null,
      related_refs_json: JSON.stringify(relatedRefs),
      occurred_at: occurredAt,
      payload_json: JSON.stringify(payloadJson),
      confidence: typeof rawEvent.confidence === "number" ? rawEvent.confidence : 0.7,
      extraction_version: EXTRACTOR_VERSION,
      created_at: Date.now(),
    });
  }

  return { evidence, events };
}
