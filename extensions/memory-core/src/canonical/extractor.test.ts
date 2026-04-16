import { describe, expect, it } from "vitest";
import { parseGraphJsonBlock } from "./extractor.js";

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
});
