import { normalizeName } from "./id-v2.js";
import type { EvidenceRecordV2, EventRecordV2, GraphEntityV2 } from "./schema-v2.js";

function labelFromRef(ref: string): string {
  const [, raw] = ref.split(":", 2);
  return raw?.trim() || ref;
}

function nameForRef(
  ref: string,
  payload: Record<string, unknown>,
  evidence: EvidenceRecordV2,
): string {
  if (typeof payload.name === "string" && payload.name.trim()) {
    return payload.name.trim();
  }
  if (ref.startsWith("person_name:")) {
    const text = evidence.content_text?.trim();
    return text ? normalizeName(text).slice(0, 80) : labelFromRef(ref);
  }
  return labelFromRef(ref);
}

function asPayload(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function refsForEvent(event: EventRecordV2): string[] {
  const refs = new Set<string>();
  if (event.subject_ref) {
    refs.add(event.subject_ref);
  }
  if (event.actor_ref) {
    refs.add(event.actor_ref);
  }
  if (event.object_ref) {
    refs.add(event.object_ref);
  }
  try {
    const related = JSON.parse(event.related_refs_json) as unknown;
    if (Array.isArray(related)) {
      for (const ref of related) {
        if (typeof ref === "string" && ref.includes(":")) {
          refs.add(ref);
        }
      }
    }
  } catch {
    // ignore malformed related refs
  }
  return [...refs];
}

function entityTypeForRef(ref: string): GraphEntityV2["entity_type"] {
  const prefix = ref.split(":", 1)[0] || "blocker";
  if (prefix === "topic") {
    return "topic";
  }
  if (prefix === "thread") {
    return "thread";
  }
  if (prefix === "doc") {
    return "doc";
  }
  if (prefix === "project") {
    return "project";
  }
  if (prefix === "event") {
    return "claim";
  }
  if (prefix === "evidence") {
    return "evidence";
  }
  if (prefix === "date") {
    return "date";
  }
  if (prefix === "stage") {
    return "stage";
  }
  if (prefix === "person_name") {
    return "person";
  }
  if (prefix === "task" || prefix === "approval" || prefix === "person" || prefix === "blocker") {
    return prefix;
  }
  return "blocker";
}

export function deriveGraphEntitiesV2(
  evidence: EvidenceRecordV2,
  events: EventRecordV2[],
): GraphEntityV2[] {
  const entities = new Map<string, GraphEntityV2>();
  for (const event of events) {
    const payload = asPayload(event.payload_json);
    if (event.event_type === "decision_claim_recorded") {
      const refs = new Set<string>();
      refs.add(event.subject_ref);
      refs.add(`event:${event.event_id}`);
      refs.add(`evidence:${evidence.evidence_id}`);
      const anchors =
        payload.topic_anchors_json && typeof payload.topic_anchors_json === "object"
          ? (payload.topic_anchors_json as Record<string, unknown>)
          : {};
      for (const key of ["task_refs", "thread_ids", "doc_refs", "project_names"]) {
        const values = anchors[key];
        if (!Array.isArray(values)) {
          continue;
        }
        for (const value of values) {
          if (typeof value !== "string" || !value.trim()) {
            continue;
          }
          if (key === "task_refs") {
            refs.add(value.startsWith("task:") ? value : `task:${value}`);
          } else if (key === "thread_ids") {
            refs.add(`thread:${value}`);
          } else if (key === "doc_refs") {
            refs.add(value.includes(":") ? value : `doc:${value}`);
          } else if (key === "project_names") {
            refs.add(`project:${normalizeName(value).replaceAll(" ", "-")}`);
          }
        }
      }
      const claimValue =
        payload.claim_value_json && typeof payload.claim_value_json === "object"
          ? (payload.claim_value_json as Record<string, unknown>)
          : {};
      if (typeof claimValue.date === "string" && claimValue.date.trim()) {
        refs.add(`date:${claimValue.date.trim()}`);
      }
      if (
        typeof payload.claim_field === "string" &&
        payload.claim_field === "stage" &&
        typeof payload.claim_text === "string" &&
        payload.claim_text.trim()
      ) {
        refs.add(`stage:${normalizeName(payload.claim_text).replaceAll(" ", "_")}`);
      }
      for (const ref of refs) {
        const current = entities.get(ref);
        const candidate: GraphEntityV2 = {
          entity_ref: ref,
          entity_type: entityTypeForRef(ref),
          canonical_name:
            current?.canonical_name ??
            (ref === event.subject_ref
              ? String(payload.decision_axis_text ?? ref)
              : ref === `event:${event.event_id}`
                ? String(payload.claim_text ?? ref)
                : ref === `evidence:${evidence.evidence_id}`
                  ? String(payload.evidence_quote ?? evidence.content_text ?? ref)
                  : nameForRef(ref, payload, evidence)),
          alias_json: current?.alias_json ?? "[]",
          first_seen_at: current?.first_seen_at ?? event.occurred_at,
          last_seen_at: event.occurred_at,
          last_evidence_id: evidence.evidence_id,
          updated_at: Date.now(),
        };
        entities.set(ref, candidate);
      }
      continue;
    }
    for (const ref of refsForEvent(event)) {
      const current = entities.get(ref);
      const candidate: GraphEntityV2 = {
        entity_ref: ref,
        entity_type: entityTypeForRef(ref),
        canonical_name: current?.canonical_name ?? nameForRef(ref, payload, evidence),
        alias_json: current?.alias_json ?? "[]",
        first_seen_at: current?.first_seen_at ?? event.occurred_at,
        last_seen_at: event.occurred_at,
        last_evidence_id: evidence.evidence_id,
        updated_at: Date.now(),
      };
      entities.set(ref, candidate);
    }
  }
  return [...entities.values()];
}
