import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { EntityState, EventRecord } from "./schema.js";

const log = createSubsystemLogger("memory");

function eventTimeMs(event: EventRecord): number {
  const occurred = Date.parse(event.occurred_at);
  return Number.isFinite(occurred) ? occurred : event.created_at;
}

function isNewer(left: EventRecord, right: EventRecord): boolean {
  const leftMs = eventTimeMs(left);
  const rightMs = eventTimeMs(right);
  return leftMs === rightMs ? left.created_at >= right.created_at : leftMs > rightMs;
}

function inferEntityType(event: EventRecord, previous?: EntityState): EntityState["entity_type"] {
  const object = event.object?.trim().toLowerCase() ?? "";
  if (/\b(task|issue|ticket)\b/.test(object) || /\btask[-_ ]?\d+\b/.test(object)) {
    return "task";
  }
  return previous?.entity_type ?? "other";
}

export function reduce(events: EventRecord[], prevStates: Map<string, EntityState>): EntityState[] {
  const latestByEntity = new Map<string, EventRecord>();
  for (const event of events) {
    const previous = latestByEntity.get(event.entity_id);
    if (!previous || isNewer(event, previous)) {
      latestByEntity.set(event.entity_id, event);
    }
  }

  const states: EntityState[] = [];
  for (const event of latestByEntity.values()) {
    const previous = prevStates.get(event.entity_id);
    const lastUpdatedAt = Math.max(eventTimeMs(event), event.created_at);
    states.push({
      entity_id: event.entity_id,
      latest_status: event.status_after ?? previous?.latest_status ?? null,
      latest_owner: event.actor ?? previous?.latest_owner ?? null,
      last_event_id: event.event_id,
      last_updated_at: Number.isFinite(lastUpdatedAt) ? lastUpdatedAt : event.created_at,
      entity_type: inferEntityType(event, previous),
      supporting_event_ids: [event.event_id],
      confidence: event.confidence,
    });
  }

  log.info(`canonical.reduce events=${events.length} states=${states.length}`);
  return states;
}
