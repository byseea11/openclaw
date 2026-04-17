import { describe, expect, it } from "vitest";
import { extract, parseGraphJsonBlock } from "./extractor.js";

describe("canonical graph extractor", () => {
  it("parses the final fenced graph JSON block", () => {
    const events = parseGraphJsonBlock(
      [
        "NO_REPLY",
        "```json",
        '{"events":[{"actor":"Alice","action":"changed_status","object":"task_123","source_ref":"memory/2026-04-15.md#L12-L18"}]}',
        "```",
      ].join("\n"),
    );

    expect(events).toEqual([
      expect.objectContaining({
        actor: "Alice",
        action: "changed_status",
        object: "task_123",
        source_ref: "memory/2026-04-15.md#L12-L18",
      }),
    ]);
  });

  it("returns an empty event list for malformed JSON", () => {
    expect(parseGraphJsonBlock("```json\n{nope\n```")).toEqual([]);
  });

  it("extracts rule-based events with precise source refs", async () => {
    const events = await extract(
      [
        "# 2026-04-15",
        "- [ ] task_123 owner: Alice",
        "task_123 is blocked",
        "owner: Bob",
        "Alice decided to ship task_123 tomorrow",
        "status: done",
      ].join("\n"),
      "memory/2026-04-15.md#L1-L6",
    );

    expect(events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          action: "changed_status",
          object: "task_123",
          status_after: "pending",
          source_ref: "memory/2026-04-15.md#L2-L2",
          occurred_at: "2026-04-15",
        }),
        expect.objectContaining({
          action: "changed_status",
          object: "task_123",
          status_after: "blocked",
          source_ref: "memory/2026-04-15.md#L3-L3",
        }),
        expect.objectContaining({
          action: "assigned_owner",
          actor: "Bob",
          source_ref: "memory/2026-04-15.md#L4-L4",
        }),
        expect.objectContaining({
          action: "decided",
          actor: "Alice",
          object: "ship task_123 tomorrow",
          source_ref: "memory/2026-04-15.md#L5-L5",
        }),
        expect.objectContaining({
          action: "changed_status",
          status_after: "done",
          source_ref: "memory/2026-04-15.md#L6-L6",
        }),
      ]),
    );
  });
});
