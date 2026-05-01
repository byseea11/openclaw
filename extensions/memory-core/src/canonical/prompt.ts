import { parseSourceRef, type GraphHit } from "./schema.js";

export type GraphMemorySearchResult = {
  path: string;
  startLine: number;
  endLine: number;
  score: number;
  snippet: string;
  source: "memory";
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
  if (hit.type === "state" && structured.query_kind === "task_memory_card") {
    const rationales = Array.isArray(structured.rationales)
      ? structured.rationales.filter((value): value is string => typeof value === "string")
      : [];
    const objections = Array.isArray(structured.objections)
      ? structured.objections.filter((value): value is string => typeof value === "string")
      : [];
    const constraints = Array.isArray(structured.constraints)
      ? structured.constraints.filter((value): value is string => typeof value === "string")
      : [];
    const statuses = Array.isArray(structured.statuses)
      ? structured.statuses.filter((value): value is string => typeof value === "string")
      : [];
    const scopeClaims = Array.isArray(structured.scope_claims)
      ? structured.scope_claims.filter((value): value is string => typeof value === "string")
      : [];
    const timePoints = Array.isArray(structured.time_point_claims)
      ? structured.time_point_claims.filter((value): value is string => typeof value === "string")
      : [];
    const commitments = Array.isArray(structured.commitments)
      ? structured.commitments.filter((value): value is string => typeof value === "string")
      : [];
    const evidenceRefs = Array.isArray(structured.evidence_refs)
      ? structured.evidence_refs
          .map((value) =>
            value && typeof value === "object" && !Array.isArray(value)
              ? (value as Record<string, unknown>)
              : null,
          )
          .filter((value): value is Record<string, unknown> => Boolean(value))
      : [];
    return [
      "[Task memory card]",
      optionalLine("task", structured.task_ref),
      optionalLine("topic", structured.primary_topic_ref),
      optionalLine("current_conclusion", structured.current_conclusion),
      statuses.length > 0 ? `status: ${statuses.join(" | ")}` : null,
      scopeClaims.length > 0 ? `scope: ${scopeClaims.join(" | ")}` : null,
      timePoints.length > 0 ? `time_points: ${timePoints.join(" | ")}` : null,
      rationales.length > 0 ? `rationales: ${rationales.join(" | ")}` : null,
      objections.length > 0 ? `objections: ${objections.join(" | ")}` : null,
      constraints.length > 0 ? `constraints: ${constraints.join(" | ")}` : null,
      commitments.length > 0 ? `commitments: ${commitments.join(" | ")}` : null,
      evidenceRefs.length > 0
        ? `evidence: ${evidenceRefs
            .map((value) =>
              typeof value.source_ref === "string" ? value.source_ref : "(unknown source)",
            )
            .join(", ")}`
        : null,
      `source: ${hit.source_ref}`,
    ]
      .filter((line): line is string => Boolean(line))
      .join("\n");
  }
  if (typeof structured.group_type === "string" && typeof structured.evidence_group === "object") {
    const group = structured.evidence_group as Record<string, unknown>;
    const label =
      typeof group.summary_label === "string" ? group.summary_label : "Grouped graph evidence";
    const freshness = typeof group.freshness === "string" ? group.freshness : "unknown";
    const relation = optionalLine("relation", group.relation);
    const conflicts = group.has_conflict === true ? "has_conflict: true" : null;
    return [
      `[Graph ${structured.group_type}]`,
      label,
      relation,
      optionalLine("freshness", freshness),
      conflicts,
      optionalLine("last_seen", group.last_seen_at),
      `source: ${hit.source_ref}`,
    ]
      .filter((line): line is string => Boolean(line))
      .join("\n");
  }
  if (hit.type === "state") {
    const owner =
      typeof structured.current_owner_ref === "string"
        ? structured.current_owner_ref
        : structured.latest_owner;
    const stage =
      typeof structured.current_stage === "string"
        ? structured.current_stage
        : structured.latest_status;
    return [
      "[Graph state]",
      `entity: ${hit.entity_id}`,
      optionalLine("status", stage),
      optionalLine("owner", owner),
      optionalLine("approval", structured.current_approval_ref),
      optionalLine("approval_status", structured.approval_status),
      optionalLine("blocker", structured.current_blocker_ref),
      `last_updated: ${formatDate(structured.last_updated_at)}`,
      `source: ${hit.source_ref}`,
    ]
      .filter((line): line is string => Boolean(line))
      .join("\n");
  }
  if (hit.type === "edge") {
    const relation = typeof structured.relation === "string" ? structured.relation : "related_to";
    const src = typeof structured.src_name === "string" ? structured.src_name : hit.entity_id;
    const dst =
      typeof structured.dst_name === "string"
        ? structured.dst_name
        : typeof structured.dst_entity_id === "string"
          ? structured.dst_entity_id
          : "(unknown entity)";
    const freshness =
      typeof structured.graph_freshness === "string"
        ? `freshness: ${structured.graph_freshness}`
        : null;
    return [
      "[Graph edge]",
      `${formatDate(structured.occurred_at)} ${src} --${relation}--> ${dst}`,
      freshness,
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
