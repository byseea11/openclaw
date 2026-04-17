import { describe, expect, it } from "vitest";
import { reduce } from "./reducer.js";
import type { EntityState, EventRecord } from "./schema.js";

function event(overrides: Partial<EventRecord>): EventRecord {
  return {
    event_id: "evt",
    source_type: "memory_file",
    source_ref: "memory/2026-04-15.md#L1-L1",
    occurred_at: "2026-04-15T00:00:00.000Z",
    entity_id: "ent_task",
    actor: "Alice",
    action: "changed_status",
    object: "task",
    status_before: null,
    status_after: "open",
    session_id: null,
    covered_until_entry_id: null,
    confidence: 0.5,
    extractor_version: "v-test",
    created_at: 1,
    ...overrides,
  };
}

describe("canonical graph reducer", () => {
  it("returns no states for empty input", () => {
    expect(reduce([], new Map())).toEqual([]);
  });

  it("keeps the latest event per entity", () => {
    const previous: EntityState = {
      entity_id: "ent_task",
      latest_status: "old",
      latest_owner: "Old Owner",
      last_event_id: "old",
      last_updated_at: 1,
      entity_type: "other",
      supporting_event_ids: ["old"],
      confidence: 0.4,
    };

    const states = reduce(
      [
        event({ event_id: "older", occurred_at: "2026-04-14T00:00:00.000Z" }),
        event({
          event_id: "newer",
          occurred_at: "2026-04-16T00:00:00.000Z",
          actor: "Bob",
          status_after: "blocked",
        }),
      ],
      new Map([["ent_task", previous]]),
    );

    expect(states).toEqual([
      expect.objectContaining({
        entity_id: "ent_task",
        latest_status: "blocked",
        latest_owner: "Bob",
        last_event_id: "newer",
        entity_type: "task",
        supporting_event_ids: ["newer"],
        confidence: 0.5,
      }),
    ]);
  });

  it("marks obvious task objects as task entities", () => {
    const states = reduce(
      [
        event({
          event_id: "task",
          object: "task_123",
          status_after: "done",
          confidence: 0.9,
        }),
      ],
      new Map(),
    );

    expect(states).toEqual([
      expect.objectContaining({
        entity_type: "task",
        supporting_event_ids: ["task"],
        confidence: 0.9,
      }),
    ]);
  });
});
