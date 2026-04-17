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
      status_before: "in_progress",
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
      status_before: "in_progress",
      status_after: "blocked",
      session_id: null,
      covered_until_entry_id: null,
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
      source_type: "memory_file",
      actor: null,
      object: null,
      status_before: null,
      status_after: null,
      session_id: null,
      covered_until_entry_id: null,
      confidence: 0.5,
      occurred_at: expect.stringMatching(/^20\d{2}-\d{2}-\d{2}T/),
      entity_id: expect.stringMatching(/^ent_/),
    });
  });

  it("keeps event ids stable when status_before changes", () => {
    const base: RawEvent = {
      action: "changed_status",
      object: "task_123",
      status_after: "blocked",
      occurred_at: "2026-04-15",
      source_ref: "memory/2026-04-15.md#L12-L18",
    };
    const withoutStatusBefore: RawEvent = { ...base, status_before: undefined };
    const withStatusBefore: RawEvent = { ...base, status_before: "open" };

    expect(createEventId(withoutStatusBefore)).toBe(createEventId(withStatusBefore));
  });
});
