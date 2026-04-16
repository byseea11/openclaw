import { describe, expect, it } from "vitest";
import { buildPromptSection } from "./prompt-section.js";

describe("memory prompt section", () => {
  it("documents graph hits in the existing recall section", () => {
    const lines = buildPromptSection({
      availableTools: new Set(["memory_search", "memory_get"]),
    });

    expect(lines.join("\n")).toContain('corpus: "graph"');
    expect(lines.join("\n")).toContain("memory_get");
    expect(lines[0]).toBe("## Memory Recall");
  });
});
