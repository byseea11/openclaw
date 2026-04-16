import type { MemorySearchResult } from "openclaw/plugin-sdk/memory-core-host-runtime-files";
import { parseSourceRef, type GraphHit } from "./schema.js";

export type GraphMemorySearchResult = MemorySearchResult & {
  corpus: "graph";
  graphMeta: {
    type: GraphHit["type"];
    entity_id: string;
  };
};

function formatDate(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Date(value).toISOString().slice(0, 10);
  }
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? new Date(parsed).toISOString().slice(0, 10) : value;
  }
  return "unknown";
}

function optionalLine(label: string, value: unknown): string | null {
  return typeof value === "string" && value.trim() ? `${label}: ${value.trim()}` : null;
}

export function renderGraphHit(hit: GraphHit): string {
  const structured = hit.snippet_structured;
  if (hit.type === "state") {
    return [
      "[Graph state]",
      `entity: ${hit.entity_id}`,
      optionalLine("status", structured.latest_status),
      optionalLine("owner", structured.latest_owner),
      `last_updated: ${formatDate(structured.last_updated_at)}`,
      `source: ${hit.source_ref}`,
    ]
      .filter((line): line is string => Boolean(line))
      .join("\n");
  }
  const actor = typeof structured.actor === "string" ? structured.actor : "(unknown actor)";
  const action = typeof structured.action === "string" ? structured.action : "(unknown action)";
  const object = typeof structured.object === "string" ? ` ${structured.object}` : "";
  const status =
    typeof structured.status_after === "string" ? ` -> ${structured.status_after}` : "";
  return [
    "[Graph event]",
    `${formatDate(structured.occurred_at)} ${actor} ${action}${object}${status}`,
    `source: ${hit.source_ref}`,
  ].join("\n");
}

export function graphHitToMemorySearchResult(hit: GraphHit): GraphMemorySearchResult | null {
  const parsed = parseSourceRef(hit.source_ref);
  if (!parsed) {
    return null;
  }
  return {
    path: parsed.path,
    startLine: parsed.startLine,
    endLine: parsed.endLine,
    score: hit.score,
    snippet: renderGraphHit(hit),
    source: "memory",
    corpus: "graph",
    graphMeta: {
      type: hit.type,
      entity_id: hit.entity_id,
    },
  };
}
