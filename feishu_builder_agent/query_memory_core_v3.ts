import fs from "node:fs/promises";
import path from "node:path";

type Payload = {
  workspaceDir: string;
  query: string;
  maxResults?: number;
};

function debugLog(message: string) {
  if (process.env.FEISHU_BUILDER_DEBUG_MEMORY_BASELINE === "1") {
    console.error(`[memory-md-baseline] ${message}`);
  }
}

async function main() {
  const raw = process.argv[2];
  if (!raw) {
    throw new Error("missing JSON payload");
  }
  const payload = JSON.parse(raw) as Payload;
  const cfg = {
    memory: { backend: "builtin" },
    plugins: {
      allow: ["memory-core"],
      entries: {
        "memory-core": {
          enabled: true,
          config: {},
        },
      },
    },
    agents: {
      defaults: {
        workspace: payload.workspaceDir,
        memorySearch: {
          enabled: true,
          provider: "openai",
          model: "text-embedding-3-small",
          store: {
            path: `${payload.workspaceDir}/.memory-index.sqlite`,
            vector: { enabled: false },
          },
          sync: {
            watch: false,
            onSessionStart: false,
            onSearch: false,
          },
          query: {
            minScore: 0,
            hybrid: { enabled: false },
          },
          sources: ["memory"],
          experimental: { sessionMemory: false },
        },
      },
      list: [{ id: "main", default: true, workspace: payload.workspaceDir }],
    },
  };
  const configPath = path.join(payload.workspaceDir, ".openclaw-memory-benchmark.json");
  await fs.writeFile(configPath, JSON.stringify(cfg, null, 2), "utf-8");
  process.env.OPENCLAW_CONFIG_PATH = configPath;
  debugLog(`config ready: ${configPath}`);
  const runtime = await import("../extensions/memory-core/src/memory/index.ts");
  const { getMemorySearchManager, closeAllMemorySearchManagers } = runtime;
  debugLog("memory runtime imported");
  const result = await getMemorySearchManager({ cfg, agentId: "main" });
  debugLog("memory manager resolved");
  if (!result.manager) {
    throw new Error(result.error ?? "memory search manager unavailable");
  }
  const results = await result.manager.search(payload.query, {
    maxResults: payload.maxResults ?? 5,
    sessionKey: "benchmark:memory-md",
  });
  debugLog(`memory search completed: ${results.length} hits`);
  const reads = [];
  for (const hit of results.slice(0, 3)) {
    debugLog(`reading hit: ${hit.path}:${hit.startLine}-${hit.endLine}`);
    const detail = await result.manager.readFile({
      relPath: hit.path,
      from: hit.startLine,
      lines: Math.max(1, (hit.endLine ?? hit.startLine) - hit.startLine + 1),
    });
    reads.push({
      path: detail.path,
      text: detail.text,
    });
  }
  console.log(JSON.stringify({ results, reads }));
  debugLog("memory query finished");
  await closeAllMemorySearchManagers();
  process.exit(0);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack ?? error.message : String(error));
  process.exit(1);
});
