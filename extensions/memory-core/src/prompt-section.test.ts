import { describe, expect, it } from "vitest";
import { buildPromptSection } from "./prompt-section.js";

describe("memory prompt section", () => {
  it("documents memory recall guidance in the existing recall section", () => {
    const lines = buildPromptSection({
      availableTools: new Set(["memory_search", "memory_get"]),
    });

    expect(lines.join("\n")).toContain("memory_get");
    expect(lines.join("\n")).toContain(
      "Do not use generic file reads on MEMORY.md or memory/*.md before memory_search",
    );
    expect(lines[0]).toBe("## Memory Recall");
  });
});
