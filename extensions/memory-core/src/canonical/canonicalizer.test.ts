import { describe, expect, it, vi } from "vitest";
import { canonicalize, canonicalizeEntityId, createEventId } from "./canonicalizer.js";
import type { RawEvent } from "./schema.js";

describe("canonical graph canonicalizer", () => {
  it("creates stable event and entity identifiers", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-16T00:00:00.000Z"));
    const raw: RawEvent = {
      actor: "Alice",
      action: "changed_status",
      object: "Task 123",
      status_after: "blocked",
      occurred_at: "2026-04-15",
      source_ref: "memory/2026-04-15.md#L12-L18",
      confidence: 0.8,
    };

    const first = canonicalize([raw], "v-test")[0];
    const second = canonicalize([raw], "v-test")[0];

    expect(first?.event_id).toBe(second?.event_id);
    expect(first?.event_id).toBe(createEventId(raw));
    expect(first?.entity_id).toBe(canonicalizeEntityId("Task 123"));
    expect(first).toMatchObject({
      source_type: "memory_file",
      actor: "Alice",
      action: "changed_status",
      object: "Task 123",
      status_after: "blocked",
      confidence: 0.8,
      extractor_version: "v-test",
    });
    vi.useRealTimers();
  });

  it("keeps events valid when optional fields are missing", () => {
    const records = canonicalize(
      [
        {
          action: "decided",
          source_ref: "MEMORY.md#L1-L1",
        },
      ],
      "v-test",
    );

    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      actor: null,
      object: null,
      status_after: null,
      confidence: 0.5,
    });
  });
});
