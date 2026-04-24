import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { bootstrapCanonicalIndex } from "./bootstrap.js";
import { closeAllCanonicalStores } from "./store.js";
import { setDefaultExtractorClient } from "./extractor.js";

describe("canonical graph bootstrap", () => {
  let workspaceDir = "";
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    workspaceDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-bootstrap-"));
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-graph-bootstrap-state-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    await fs.mkdir(path.join(workspaceDir, "memory"), { recursive: true });
    await fs.writeFile(
      path.join(workspaceDir, "memory", "2026-04-18.md"),
      "FEISHU-231 blocked by AP-778\n",
      "utf8",
    );
    setDefaultExtractorClient(null);
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    setDefaultExtractorClient(null);
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(workspaceDir, { recursive: true, force: true });
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("fails bootstrap when the extractor runtime is unavailable", async () => {
    await expect(
      bootstrapCanonicalIndex({
        agentId: "main",
        workspaceDir,
      }),
    ).rejects.toMatchObject({
      code: "extractor_unavailable",
    });
  });
});
