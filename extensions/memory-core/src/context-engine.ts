import type { ContextEngine } from "openclaw/plugin-sdk";
import type { OpenClawConfig } from "openclaw/plugin-sdk/memory-core-host-runtime-core";
import type { MemorySearchResult } from "openclaw/plugin-sdk/memory-core-host-runtime-files";
import {
  searchGraphForMemoryTool,
  type GraphMemorySearchResult,
} from "./canonical/index.js";
import { classifyQueryV2 } from "./canonical/query-v2.js";
import { getMemoryManagerContext, type MemorySearchResultWithCorpus } from "./tools.shared.js";

type AssembleParams = Parameters<ContextEngine["assemble"]>[0];
type QueryClass = ReturnType<typeof classifyQueryV2>;

const STATE_SUMMARY_BUDGET_CHARS = 900;
const TAIL_EVIDENCE_BUDGET_CHARS = 1_800;
const TAIL_EVIDENCE_LIMIT = 3;
const MEMORY_INTENT_RE =
  /\b([A-Z][A-Z0-9]+-\d+|AP-\d+)\b|why|blocked|blocker|dependency|timeline|changed|owner|approval|status|todo|next action|memory|remember|之前|上次|历史|演进|为什么|原因|卡在哪|哪些|列出|关系|依赖|负责人|审批|状态|下一步/i;

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

function resultRef(result: Pick<MemorySearchResult, "path" | "startLine" | "endLine">): string {
  return `${result.path}#L${result.startLine}-L${result.endLine}`;
}

function resultCorpus(result: MemorySearchResultWithCorpus): string {
  return result.corpus === "graph" ? `graph:${result.graphMeta.type}` : result.corpus;
}

function graphType(result: MemorySearchResultWithCorpus): string | null {
  return result.corpus === "graph" ? result.graphMeta.type : null;
}

function evidencePriority(queryClass: QueryClass, result: MemorySearchResultWithCorpus): number {
  const type = graphType(result);
  if (queryClass === "state") {
    return type === "state" ? 0 : type === "event" ? 1 : result.corpus === "memory" ? 2 : 3;
  }
  if (queryClass === "why") {
    return type === "event" ? 0 : type === "state" ? 1 : result.corpus === "memory" ? 2 : 3;
  }
  if (queryClass === "timeline") {
    return type === "event" ? 0 : result.corpus === "memory" ? 1 : type === "state" ? 2 : 3;
  }
  return type === "edge" ? 0 : type === "state" ? 1 : result.corpus === "memory" ? 2 : 3;
}

function orderHybridEvidenceForQuery(params: {
  queryClass: QueryClass;
  results: MemorySearchResultWithCorpus[];
}): MemorySearchResultWithCorpus[] {
  return params.results.toSorted((left, right) => {
    const priorityDelta =
      evidencePriority(params.queryClass, left) - evidencePriority(params.queryClass, right);
    if (priorityDelta !== 0) {
      return priorityDelta;
    }
    if (left.score !== right.score) {
      return right.score - left.score;
    }
    const corpusDelta = resultCorpus(left).localeCompare(resultCorpus(right));
    if (corpusDelta !== 0) {
      return corpusDelta;
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

function buildProjectStateSummary(results: MemorySearchResultWithCorpus[]): string | undefined {
  const stateResults = results.filter((result) => graphType(result) === "state").slice(0, 5);
  if (stateResults.length === 0) {
    return undefined;
  }
  const lines = [
    "## Current Project State",
    "Structured graph state recalled before this turn. Use only if relevant to the user's request.",
  ];
  for (const result of stateResults) {
    const entry = `- ${compactSnippet(result.snippet, 220)} [source: ${resultRef(result)}]`;
    if (!appendWithinBudget({ lines, next: entry, maxChars: STATE_SUMMARY_BUDGET_CHARS })) {
      break;
    }
  }
  return lines.length > 2 ? lines.join("\n") : undefined;
}

function buildCurrentUserPromptPrefix(results: MemorySearchResultWithCorpus[]): string | undefined {
  const lines = [
    "## Current Memory Context",
    "Top evidence recalled for the current query. Use it if relevant; call memory_search or memory_get only if you need more detail or exact wording.",
  ];
  for (const result of results.slice(0, TAIL_EVIDENCE_LIMIT)) {
    const entry = `- (${resultCorpus(result)}) ${compactSnippet(result.snippet, 360)} [source: ${resultRef(result)}]`;
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
}): Promise<Array<MemorySearchResult & { corpus: "memory" }>> {
  const memory = await getMemoryManagerContext({ cfg: params.cfg, agentId: params.agentId });
  if ("error" in memory) {
    return [];
  }
  const results = await memory.manager.search(params.query, {
    maxResults: TAIL_EVIDENCE_LIMIT,
    sessionKey: params.sessionKey,
  });
  return results.map((result) => ({ ...result, corpus: "memory" as const }));
}

async function searchGraphEvidence(params: {
  cfg: OpenClawConfig;
  agentId: string;
  query: string;
  sessionKey?: string;
}): Promise<GraphMemorySearchResult[]> {
  const graph = await searchGraphForMemoryTool({
    cfg: params.cfg,
    agentId: params.agentId,
    query: params.query,
    maxResults: 5,
    sessionKey: params.sessionKey,
  });
  return graph.results;
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
      const queryClass = classifyQueryV2(prompt);
      const graphResults = await searchGraphEvidence({
        cfg: params.config,
        agentId: params.agentId,
        query: prompt,
        sessionKey: params.sessionKey,
      });
      const memoryResults = await searchMemoryEvidence({
        cfg: params.config,
        agentId: params.agentId,
        query: prompt,
        sessionKey: params.sessionKey,
      });
      const ordered = orderHybridEvidenceForQuery({
        queryClass,
        results: [...graphResults, ...memoryResults],
      });
      return {
        messages: params.messages,
        estimatedTokens: 0,
        systemPromptAddition: buildProjectStateSummary(ordered),
        currentUserPromptPrefix: buildCurrentUserPromptPrefix(ordered),
      };
    } catch {
      return { messages: params.messages, estimatedTokens: 0 };
    }
  }
}

export function createMemoryCoreContextEngine(): ContextEngine {
  return new MemoryCoreContextEngine();
}
