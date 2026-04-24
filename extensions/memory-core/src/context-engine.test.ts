import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { OpenClawConfig } from "../api.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { generateUlid } from "./canonical/id-v2.js";
import { closeAllCanonicalStores, getCanonicalStore } from "./canonical/index.js";
import { buildEvidenceFingerprint, buildEventFingerprint } from "./canonical/schema-v2.js";
import {
  getMemorySearchManagerMockCalls,
  resetMemoryToolMockState,
  setMemorySearchImpl,
} from "./memory-tool-manager-mock.js";
import { MemoryCoreContextEngine } from "./context-engine.js";

function cfg(): OpenClawConfig {
  return {
    agents: { list: [{ id: "main", default: true }] },
    memory: { backend: "builtin" },
    plugins: {
      slots: { contextEngine: "memory-core" },
      entries: {
        "memory-core": {
          config: {
            graphIndex: { enabled: true },
          },
        },
      },
    },
  } as OpenClawConfig;
}

function cfgWithContextRecall(enabled: boolean): OpenClawConfig {
  return {
    ...cfg(),
    plugins: {
      slots: { contextEngine: "memory-core" },
      entries: {
        "memory-core": {
          config: {
            graphIndex: { enabled: true },
            contextRecall: { enabled },
          },
        },
      },
    },
  } as OpenClawConfig;
}

async function seedBlockedTask() {
  const store = getCanonicalStore("main");
  const evidenceId = generateUlid();
  const occurredAt = "2026-04-20T12:00:00.000Z";
  await store.persistSemanticBatchV2({
    evidence: {
      evidence_id: evidenceId,
      evidence_fingerprint: buildEvidenceFingerprint({
        sourcePlatform: "transcript",
        sourceKind: "transcript_span",
        sessionKey: "agent:main:feishu:thread",
        firstEntryId: "entry-1",
        lastEntryId: "entry-1",
        occurredAt,
        contentText: "FEISHU-231 is blocked by AP-778 and Alice owns the follow-up.",
        contentJson: {},
      }),
      source_platform: "transcript",
      source_kind: "transcript_span",
      session_key: "agent:main:feishu:thread",
      message_id: null,
      chat_id: null,
      chat_type: null,
      thread_id: null,
      root_id: null,
      parent_id: null,
      first_entry_id: "entry-1",
      last_entry_id: "entry-1",
      content_text: "FEISHU-231 is blocked by AP-778 and Alice owns the follow-up.",
      content_json: "{}",
      source_locator_json: JSON.stringify({ source_ref: "transcripts/test.txt#L1-L1" }),
      occurred_at: occurredAt,
      created_at: Date.now(),
    },
    events: [
      {
        event_id: generateUlid(),
        event_fingerprint: buildEventFingerprint({
          evidenceId,
          eventType: "blocked",
          subjectRef: "task:FEISHU-231",
          objectRef: "approval:AP-778",
          occurredAt,
          payloadJson: { blocker_ref: "approval:AP-778" },
        }),
        evidence_id: evidenceId,
        event_type: "blocked",
        subject_ref: "task:FEISHU-231",
        actor_ref: "person_name:alice",
        object_ref: "approval:AP-778",
        related_refs_json: JSON.stringify(["approval:AP-778", "person_name:alice"]),
        occurred_at: occurredAt,
        payload_json: JSON.stringify({ blocker_ref: "approval:AP-778" }),
        confidence: 0.95,
        extraction_version: "test",
        created_at: Date.now(),
      },
    ],
  });
}

describe("memory-core context engine", () => {
  let stateDir = "";
  let previousStateDir: string | undefined;

  beforeEach(async () => {
    stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-memory-context-engine-"));
    previousStateDir = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    resetMemoryToolMockState();
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    if (previousStateDir === undefined) {
      delete process.env.OPENCLAW_STATE_DIR;
    } else {
      process.env.OPENCLAW_STATE_DIR = previousStateDir;
    }
    await fs.rm(stateDir, { recursive: true, force: true });
  });

  it("injects project state and top evidence before memory-oriented prompts", async () => {
    await seedBlockedTask();
    setMemorySearchImpl(async () => [
      {
        path: "memory/2026-04-20.md",
        startLine: 10,
        endLine: 12,
        score: 0.99,
        snippet: "Raw memory chunk: FEISHU-231 was discussed in a long meeting note.",
        source: "memory",
      },
    ]);
    const engine = new MemoryCoreContextEngine();

    const result = await engine.assemble({
      sessionId: "session-1",
      sessionKey: "agent:main:feishu:thread",
      messages: [{ role: "user", content: "seed", timestamp: 1 }],
      config: cfg(),
      agentId: "main",
      availableTools: new Set(["memory_search", "memory_get"]),
      model: "gpt-test",
      prompt: "FEISHU-231 为什么 blocked?",
    });

    expect(result.currentUserPromptPrefix).toContain("## Current Memory Context");
    expect(result.currentUserPromptPrefix).toContain("graph:");
    expect(result.currentUserPromptPrefix).toContain("memory/2026-04-20.md#L10-L12");
    if (result.systemPromptAddition) {
      expect(result.systemPromptAddition).toContain("## Current Project State");
    }
    const prefix = result.currentUserPromptPrefix ?? "";
    expect(prefix.indexOf("graph:")).toBeLessThan(prefix.indexOf("memory/2026-04-20.md"));
    expect(result.messages).toHaveLength(1);
  });

  it("does not proactively search for prompts without memory intent", async () => {
    const engine = new MemoryCoreContextEngine();

    const result = await engine.assemble({
      sessionId: "session-1",
      sessionKey: "agent:main:feishu:thread",
      messages: [{ role: "user", content: "seed", timestamp: 1 }],
      config: cfg(),
      agentId: "main",
      availableTools: new Set(["memory_search"]),
      model: "gpt-test",
      prompt: "hello",
    });

    expect(result.systemPromptAddition).toBeUndefined();
    expect(result.currentUserPromptPrefix).toBeUndefined();
    expect(getMemorySearchManagerMockCalls()).toBe(0);
  });

  it("skips assemble-time recall when context recall is disabled", async () => {
    await seedBlockedTask();
    setMemorySearchImpl(async () => [
      {
        path: "memory/2026-04-20.md",
        startLine: 10,
        endLine: 12,
        score: 0.99,
        snippet: "Raw memory chunk: FEISHU-231 was discussed in a long meeting note.",
        source: "memory",
      },
    ]);
    const engine = new MemoryCoreContextEngine();

    const result = await engine.assemble({
      sessionId: "session-1",
      sessionKey: "agent:main:feishu:thread",
      messages: [{ role: "user", content: "seed", timestamp: 1 }],
      config: cfgWithContextRecall(false),
      agentId: "main",
      availableTools: new Set(["memory_search", "memory_get"]),
      model: "gpt-test",
      prompt: "FEISHU-231 为什么 blocked?",
    });

    expect(result.systemPromptAddition).toBeUndefined();
    expect(result.currentUserPromptPrefix).toBeUndefined();
    expect(getMemorySearchManagerMockCalls()).toBe(0);
  });
});
