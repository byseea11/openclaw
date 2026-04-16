import { describe, expect, it } from "vitest";
import { buildMemoryFlushPlan } from "./flush-plan.js";

describe("memory flush plan", () => {
  it("adds graph JSON instructions only when graph flush extraction is enabled", () => {
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
                  extractDuringFlush: true,
                },
              },
            },
          },
        },
      },
      nowMs: Date.parse("2026-04-16T00:00:00.000Z"),
    });

    expect(enabled?.prompt).toContain("graph index");
    expect(enabled?.prompt).toContain('"events":[]');
    expect(enabled?.prompt).toContain("memory/2026-04-16.md#L12-L18");
  });
});
