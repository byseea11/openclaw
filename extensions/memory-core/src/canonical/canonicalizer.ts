import crypto from "node:crypto";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { isMemorySourceRef, type EventRecord, type RawEvent } from "./schema.js";

const log = createSubsystemLogger("memory");

function sha1(value: string): string {
  return crypto.createHash("sha1").update(value).digest("hex");
}

function sha256(value: string): string {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function normalizeOptionalString(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function normalizeOccurredAt(value: string | undefined): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return new Date().toISOString();
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    return `${trimmed}T00:00:00.000Z`;
  }
  const parsed = Date.parse(trimmed);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : new Date().toISOString();
}

function normalizeConfidence(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0.5;
  }
  return Math.min(1, Math.max(0, value));
}

export function canonicalizeEntityId(raw: string): string {
  const normalized = raw
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^\p{L}\p{N}_-]/gu, "");
  const stable = normalized || "unknown";
  return `ent_${sha1(stable).slice(0, 12)}`;
}

export function createEventId(
  event: Pick<
    RawEvent,
    "source_ref" | "actor" | "action" | "object" | "status_after" | "occurred_at"
  >,
): string {
  return sha256(
    [
      event.source_ref,
      normalizeOptionalString(event.actor) ?? "",
      event.action.trim(),
      normalizeOptionalString(event.object) ?? "",
      normalizeOptionalString(event.status_after) ?? "",
    ].join("\0"),
  );
}

type CanonicalizeOptions = {
  sourceType?: EventRecord["source_type"];
  sessionId?: string | null;
  coveredUntilEntryId?: string | null;
};

function inferSourceType(sourceRef: string): EventRecord["source_type"] {
  if (isMemorySourceRef(sourceRef)) {
    return "memory_file";
  }
  if (sourceRef.startsWith("transcripts/")) {
    return "transcript";
  }
  return "flush";
}

export function canonicalize(
  raw: RawEvent[],
  extractorVersion: string,
  options: CanonicalizeOptions = {},
): EventRecord[] {
  const createdAt = Date.now();
  const seenEventIds = new Set<string>();
  const records = raw.flatMap((event): EventRecord[] => {
    const action = event.action?.trim();
    const sourceRef = event.source_ref?.trim();
    if (!action || !sourceRef) {
      return [];
    }
    const eventId = createEventId(event);
    if (seenEventIds.has(eventId)) {
      return [];
    }
    seenEventIds.add(eventId);
    const actor = normalizeOptionalString(event.actor);
    const object = normalizeOptionalString(event.object);
    const entityBasis = object ?? (actor ? `${actor}:${action}` : `${action}:${sourceRef}`);
    return [
      {
        event_id: eventId,
        source_type: options.sourceType ?? inferSourceType(sourceRef),
        source_ref: sourceRef,
        occurred_at: normalizeOccurredAt(event.occurred_at),
        entity_id: canonicalizeEntityId(entityBasis),
        actor,
        action,
        object,
        status_before: normalizeOptionalString(event.status_before),
        status_after: normalizeOptionalString(event.status_after),
        session_id: options.sessionId ?? null,
        covered_until_entry_id: options.coveredUntilEntryId ?? null,
        confidence: normalizeConfidence(event.confidence),
        extractor_version: extractorVersion,
        created_at: createdAt,
      },
    ];
  });
  log.info(`canonical.canonicalize input=${raw.length} output=${records.length}`);
  return records;
}
