import type { OpenClawConfig } from "../api.js";
import { beforeEach, describe, expect, it } from "vitest";
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
          config: {},
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
            contextRecall: { enabled },
          },
        },
      },
    },
  } as OpenClawConfig;
}

describe("memory-core context engine", () => {
  beforeEach(() => {
    resetMemoryToolMockState();
  });

  it("injects top evidence before memory-oriented prompts", async () => {
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
    expect(result.currentUserPromptPrefix).toContain("memory/2026-04-20.md#L10-L12");
    expect("systemPromptAddition" in result).toBe(false);
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

    expect("systemPromptAddition" in result).toBe(false);
    expect(result.currentUserPromptPrefix).toBeUndefined();
    expect(getMemorySearchManagerMockCalls()).toBe(0);
  });

  it("skips assemble-time recall when context recall is disabled", async () => {
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

    expect("systemPromptAddition" in result).toBe(false);
    expect(result.currentUserPromptPrefix).toBeUndefined();
    expect(getMemorySearchManagerMockCalls()).toBe(0);
  });
});
