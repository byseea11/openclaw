import type { ContextEngine } from "openclaw/plugin-sdk";
import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import type { MemorySearchResult } from "openclaw/plugin-sdk/memory-core-host-runtime-files";
import { getMemoryManagerContext } from "./tools.shared.js";

type AssembleParams = Parameters<ContextEngine["assemble"]>[0];

const TAIL_EVIDENCE_BUDGET_CHARS = 1_800;
const TAIL_EVIDENCE_LIMIT = 3;
const MEMORY_INTENT_RE =
  /\b([A-Z][A-Z0-9]+-\d+|AP-\d+)\b|why|blocked|blocker|dependency|timeline|changed|owner|approval|status|todo|next action|memory|remember|decision|conclusion|rationale|objection|release date|之前|上次|历史|演进|为什么|原因|卡在哪|哪些|列出|关系|依赖|负责人|审批|状态|下一步|结论|口径|反对意见|决策|发布日期/i;

function hasMemoryIntent(prompt: string): boolean {
  return MEMORY_INTENT_RE.test(prompt);
}

function isContextRecallEnabled(cfg: OpenClawConfig): boolean {
  const value =
    cfg.plugins?.entries?.["memory-core"]?.config &&
    typeof cfg.plugins.entries["memory-core"].config === "object"
      ? (cfg.plugins.entries["memory-core"].config as { contextRecall?: { enabled?: boolean } })
          .contextRecall?.enabled
      : undefined;
  return value !== false;
}

function resultRef(
  result: Pick<MemorySearchResult, "path" | "startLine" | "endLine">,
): string {
  return `${result.path}#L${result.startLine ?? 1}-L${result.endLine ?? result.startLine ?? 1}`;
}

function orderMemoryEvidence(results: MemorySearchResult[]): MemorySearchResult[] {
  return results.toSorted((left, right) => {
    if (left.score !== right.score) {
      return right.score - left.score;
    }
    const pathDelta = left.path.localeCompare(right.path);
    if (pathDelta !== 0) {
      return pathDelta;
    }
    return (left.startLine ?? 0) - (right.startLine ?? 0);
  });
}

function appendWithinBudget(params: {
  lines: string[];
  next: string;
  maxChars: number;
}): boolean {
  const nextTotal =
    params.lines.reduce((total, line) => total + line.length + 1, 0) + params.next.length;
  if (nextTotal > params.maxChars) {
    return false;
  }
  params.lines.push(params.next);
  return true;
}

function compactSnippet(snippet: string, maxChars: number): string {
  const normalized = snippet
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .filter(Boolean)
    .join(" | ");
  return normalized.length <= maxChars ? normalized : `${normalized.slice(0, maxChars - 1)}…`;
}

function buildCurrentUserPromptPrefix(results: MemorySearchResult[]): string | undefined {
  const lines = [
    "## Current Memory Context",
    "Top evidence recalled for the current query. Use it if relevant; call memory_search or memory_get only if you need more detail or exact wording.",
  ];
  for (const result of results.slice(0, TAIL_EVIDENCE_LIMIT)) {
    const entry = `- ${compactSnippet(result.snippet, 360)} [source: ${resultRef(result)}]`;
    if (!appendWithinBudget({ lines, next: entry, maxChars: TAIL_EVIDENCE_BUDGET_CHARS })) {
      break;
    }
  }
  return lines.length > 2 ? lines.join("\n") : undefined;
}

async function searchMemoryEvidence(params: {
  cfg: OpenClawConfig;
  agentId: string;
  query: string;
  sessionKey?: string;
}): Promise<MemorySearchResult[]> {
  const memory = await getMemoryManagerContext({ cfg: params.cfg, agentId: params.agentId });
  if ("error" in memory) {
    return [];
  }
  const results = await memory.manager.search(params.query, {
    maxResults: TAIL_EVIDENCE_LIMIT,
    sessionKey: params.sessionKey,
  });
  return results;
}

export class MemoryCoreContextEngine implements ContextEngine {
  readonly info = {
    id: "memory-core",
    name: "Memory Core Context Engine",
    version: "0.1.0",
  };

  async ingest(): Promise<{ ingested: boolean }> {
    return { ingested: false };
  }

  async assemble(params: AssembleParams) {
    const prompt = params.prompt?.trim() ?? "";
    if (
      !prompt ||
      !hasMemoryIntent(prompt) ||
      !params.config ||
      !isContextRecallEnabled(params.config) ||
      !params.agentId ||
      !params.availableTools?.has("memory_search")
    ) {
      return { messages: params.messages, estimatedTokens: 0 };
    }

    try {
      const memoryResults = await searchMemoryEvidence({
        cfg: params.config,
        agentId: params.agentId,
        query: prompt,
        sessionKey: params.sessionKey,
      });
      const ordered = orderMemoryEvidence(memoryResults);
      return {
        messages: params.messages,
        estimatedTokens: 0,
        currentUserPromptPrefix: buildCurrentUserPromptPrefix(ordered),
      };
    } catch {
      return { messages: params.messages, estimatedTokens: 0 };
    }
  }

  async compact(
    _params: Parameters<ContextEngine["compact"]>[0],
  ): Promise<{ ok: true; compacted: false; reason: string }> {
    return {
      ok: true,
      compacted: false,
      reason: "memory-core-context-engine-noop",
    };
  }
}

export function createMemoryCoreContextEngine(): ContextEngine {
  return new MemoryCoreContextEngine();
}
