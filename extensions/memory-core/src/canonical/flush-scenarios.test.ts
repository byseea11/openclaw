import fs from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { extract } from "./extractor.js";

const FIXTURE_DIR = path.join(
  import.meta.dirname,
  "__tests__",
  "fixtures",
  "flush-scenarios",
);

describe("canonical graph flush scenario fixtures", () => {
  it("keeps three representative flush fixtures with multiple extractable events", async () => {
    const entries = (await fs.readdir(FIXTURE_DIR)).filter((entry) => entry.endsWith(".md")).sort();

    expect(entries).toEqual(["milestone-mixed.md", "multi-status.md", "owner-decision.md"]);

    for (const entry of entries) {
      const fixturePath = path.join(FIXTURE_DIR, entry);
      const text = await fs.readFile(fixturePath, "utf8");
      const events = await extract(text, `memory/2026-04-16.md#L1-L6`);

      expect(events.length).toBeGreaterThanOrEqual(3);
      expect(events.every((event) => /#L\d+-L\d+$/.test(event.source_ref))).toBe(true);
    }
  });
});
