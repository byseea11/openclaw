import { describe, expect, it } from "vitest";
import { deriveGraphObjects } from "./kg.js";
import type { EventRecord } from "./schema.js";

function record(overrides: Partial<EventRecord> = {}): EventRecord {
  return {
    event_id: "evt_task",
    source_type: "transcript",
    source_ref: "transcripts/session.txt#L4-L4",
    occurred_at: "2026-04-19T00:00:00.000Z",
    entity_id: "ent_task",
    actor: "Alice",
    action: "assigned_owner",
    object: "FEISHU-231",
    object_type: "task",
    status_before: null,
    status_after: null,
    session_id: "session-1",
    covered_until_entry_id: "entry-4",
    confidence: 0.9,
    extractor_version: "v-test",
    created_at: 1_765_000_000_000,
    ...overrides,
  };
}

describe("canonical KG derivation", () => {
  it("derives task/person nodes, aliases, and owner edges", () => {
    const graph = deriveGraphObjects([record()], 1_765_000_000_000);

    expect(graph.entities).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          entity_id: "ent_task",
          entity_type: "task",
          canonical_name: "FEISHU-231",
        }),
        expect.objectContaining({
          entity_type: "person",
          canonical_name: "Alice",
        }),
      ]),
    );
    expect(graph.aliases).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ alias: "feishu-231", entity_id: "ent_task" }),
      ]),
    );
    expect(graph.edges).toEqual([
      expect.objectContaining({
        relation: "owned_by",
        src_entity_id: "ent_task",
        evidence_event_id: "evt_task",
      }),
    ]);
  });

  it("keeps tentative schedule and mention-only facts out of strong relations", () => {
    const graph = deriveGraphObjects([
      record({
        event_id: "evt_tentative",
        actor: "user",
        action: "mentioned",
        object: "Maybe arrange a meeting with Alice next week",
        object_type: "meeting",
      }),
    ]);

    expect(graph.edges).toEqual([
      expect.objectContaining({
        relation: "about",
      }),
    ]);
    expect(graph.edges).not.toEqual([
      expect.objectContaining({
        relation: "scheduled_for",
      }),
    ]);
  });

  it("uses stable edge ids for idempotent replays", () => {
    const first = deriveGraphObjects([record()]);
    const second = deriveGraphObjects([record()]);

    expect(first.edges.map((edge) => edge.edge_id)).toEqual(
      second.edges.map((edge) => edge.edge_id),
    );
  });
});
