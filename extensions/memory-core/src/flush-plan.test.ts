import { describe, expect, it } from "vitest";
import { buildMemoryFlushPlan } from "./flush-plan.js";

describe("memory flush plan", () => {
  it("does not add graph JSON instructions to flush prompts", () => {
    const disabled = buildMemoryFlushPlan({
      cfg: {},
      nowMs: Date.parse("2026-04-16T00:00:00.000Z"),
    });
    expect(disabled?.prompt).not.toContain("graph index");

    const enabled = buildMemoryFlushPlan({
      cfg: {
        plugins: {
          entries: {
            "memory-core": {
              config: {
                graphIndex: {
                  enabled: true,
                },
              },
            },
          },
        },
      },
      nowMs: Date.parse("2026-04-16T00:00:00.000Z"),
    });

    expect(enabled?.prompt).not.toContain("graph index");
    expect(enabled?.prompt).not.toContain('"events":[]');
    expect(enabled?.prompt).not.toContain("memory/2026-04-16.md#L12-L18");
    expect(enabled?.prompt).not.toContain("3-10 events");
    expect(enabled?.prompt).not.toContain("status_before");
    expect(enabled?.prompt).not.toContain("source_ref");
    expect(enabled?.prompt).not.toContain("occurred_at");
  });
});
