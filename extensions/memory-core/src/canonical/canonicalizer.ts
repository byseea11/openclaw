import crypto from "node:crypto";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { EventRecord, RawEvent } from "./schema.js";

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
  event: Pick<RawEvent, "source_ref" | "actor" | "action" | "object" | "occurred_at">,
): string {
  return sha256(
    [
      event.source_ref,
      normalizeOptionalString(event.actor) ?? "",
      event.action.trim(),
      normalizeOptionalString(event.object) ?? "",
      normalizeOccurredAt(event.occurred_at),
    ].join("\0"),
  );
}

export function canonicalize(raw: RawEvent[], extractorVersion: string): EventRecord[] {
  const createdAt = Date.now();
  const records = raw.flatMap((event): EventRecord[] => {
    const action = event.action?.trim();
    const sourceRef = event.source_ref?.trim();
    if (!action || !sourceRef) {
      return [];
    }
    const actor = normalizeOptionalString(event.actor);
    const object = normalizeOptionalString(event.object);
    const entityBasis = object ?? actor ?? action;
    return [
      {
        event_id: createEventId(event),
        source_type:
          sourceRef.startsWith("memory/") || sourceRef === "MEMORY.md"
            ? "memory_file"
            : "flush_turn",
        source_ref: sourceRef,
        occurred_at: normalizeOccurredAt(event.occurred_at),
        entity_id: canonicalizeEntityId(entityBasis),
        actor,
        action,
        object,
        status_after: normalizeOptionalString(event.status_after),
        confidence: normalizeConfidence(event.confidence),
        extractor_version: extractorVersion,
        created_at: createdAt,
      },
    ];
  });
  log.info(`canonical.canonicalize input=${raw.length} output=${records.length}`);
  return records;
}
