import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { parseSourceRef, type RawEvent } from "./schema.js";

const log = createSubsystemLogger("memory");

const WORKFLOW_ACTIONS = new Set([
  "assigned_owner",
  "changed_status",
  "approval_status_updated",
  "next_action_set",
]);

const PRECISE_SOURCE_REF_RE = /#L\d+-L\d+$/;

export type CanonicalExtractorRequest = {
  prompt: string;
  sourceRef: string;
  sourcePath: string;
  lineCount: number;
};

export type LLMClient = {
  extractGraphEvents(
    params: CanonicalExtractorRequest,
  ): Promise<string | { outputText?: string; events?: RawEvent[] }>;
};

type GraphJsonParseResult = {
  ok: boolean;
  events: RawEvent[];
};

export const GRAPH_EXTRACTOR_ERROR_CODES = [
  "extractor_unavailable",
  "extractor_timeout",
  "extractor_invalid_json",
  "extractor_empty_output",
] as const;

export type GraphExtractorErrorCode = (typeof GRAPH_EXTRACTOR_ERROR_CODES)[number];

const EXTRACTOR_SYSTEM_PROMPT = [
  "You extract workflow graph events from OpenClaw transcript or memory-file spans.",
  "Return JSON only with this exact shape:",
  '{"events":[{"actor":"xzy","action":"assigned_owner","object":"FEISHU-231","status_before":null,"status_after":null,"occurred_at":"2026-04-18","source_ref":"transcripts/example.txt#L2-L2","confidence":0.92}]}',
  "Only emit workflow events that can feed Graph Index V2.",
  "Allowed actions:",
  "- assigned_owner",
  "- changed_status",
  "- approval_status_updated",
  "- next_action_set",
  "How these map downstream:",
  "- owner_changed -> action=assigned_owner, actor=new owner, object=task id when possible",
  "- blocked/unblocked/stage_changed -> action=changed_status with status_after set to blocked, unblocked, resolved, pending, in_progress, done, or another explicit workflow stage",
  "- approval_status_updated -> action=approval_status_updated with object set to the approval ref when possible and status_after set to approved, rejected, pending, submitted, or unknown",
  "- next_action_set -> action=next_action_set with actor set to the assignee when known and object set to the action text",
  "Rules:",
  "- Never call tools and never add prose.",
  '- If nothing should be extracted, return {"events":[]}.',
  "- Split one span into multiple events when the text contains multiple workflow changes.",
  "- Use only facts explicitly supported by the text. Do not invent old owners, old stages, deadlines, or hidden state.",
  "- Extract only task-centric workflow events. If the text does not clearly anchor to a task/ticket/work item, return no events.",
  "- Prefer the smallest supporting line span for source_ref and always use SOURCE_PATH#Lx-Lx form.",
  "- Keep object concise. For task-centric status changes, prefer the task id in object when present.",
  "- Keep actor concise. Use the assignee/new owner only when the text states it clearly.",
  "- Do not emit conversational memory facts such as preferences, biography, relationships, location, health, or general life events.",
  "Examples:",
  '{"events":[{"actor":"xzy","action":"assigned_owner","object":"FEISHU-231","occurred_at":"2026-04-18","source_ref":"transcripts/example.txt#L2-L2","confidence":0.93}]}',
  '{"events":[{"action":"changed_status","object":"FEISHU-231","status_after":"blocked","occurred_at":"2026-04-18","source_ref":"transcripts/example.txt#L3-L3","confidence":0.95}]}',
  '{"events":[{"actor":"Bob","action":"next_action_set","object":"先补材料再提","occurred_at":"2026-04-18","source_ref":"transcripts/example.txt#L4-L4","confidence":0.88}]}',
].join("\n");

let defaultLlmClient: LLMClient | null = null;

export class GraphExtractorError extends Error {
  readonly code: GraphExtractorErrorCode;

  constructor(code: GraphExtractorErrorCode, message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "GraphExtractorError";
    this.code = code;
  }
}

function isRawEvent(value: unknown): value is RawEvent {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  return (
    typeof record?.action === "string" &&
    record.action.trim().length > 0 &&
    typeof record.source_ref === "string" &&
    record.source_ref.trim().length > 0
  );
}

function parseGraphJsonBlockDetailed(outputText: string): GraphJsonParseResult {
  const blocks = [...outputText.matchAll(/```json\s*([\s\S]*?)```/gi)].map(
    (match) => match[1] ?? "",
  );
  const candidates = blocks.length > 0 ? blocks.toReversed() : [outputText];
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.trim()) as { events?: unknown };
      const rawEvents = Array.isArray(parsed.events) ? parsed.events.filter(isRawEvent) : [];
      log.info(`canonical.extract.parse_ok events=${rawEvents.length}`);
      return { ok: true, events: rawEvents };
    } catch {
      // Continue scanning later candidates.
    }
  }
  log.warn("canonical.extract.parse_failed events=0");
  return { ok: false, events: [] };
}

function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function lineNumberedText(text: string): { numberedText: string; lineCount: number } {
  const lines = text.split(/\r?\n/);
  return {
    numberedText: lines.map((line, index) => `${index + 1} | ${line}`).join("\n"),
    lineCount: lines.length,
  };
}

function sourcePathFromSourceRef(sourceRef: string): string {
  return (
    parseSourceRef(sourceRef)?.path ??
    sourceRef.split("#", 1)[0]?.replaceAll("\\", "/") ??
    sourceRef
  );
}

function buildExtractionPrompt(text: string, sourceRef: string): CanonicalExtractorRequest {
  const sourcePath = sourcePathFromSourceRef(sourceRef);
  const { numberedText, lineCount } = lineNumberedText(text);
  return {
    sourceRef,
    sourcePath,
    lineCount,
    prompt: [
      `SOURCE_REF_RANGE: ${sourceRef}`,
      `SOURCE_PATH: ${sourcePath}`,
      `LINE_COUNT: ${lineCount}`,
      "",
      "Extract workflow graph events from the numbered lines below.",
      "Each event must use a line-precise source_ref like SOURCE_PATH#Lx-Lx.",
      "",
      numberedText,
    ].join("\n"),
  };
}

function coerceLlmOutputText(
  result: string | { outputText?: string; events?: RawEvent[] },
): string {
  if (typeof result === "string") {
    return result;
  }
  if (Array.isArray(result.events)) {
    return JSON.stringify({ events: result.events });
  }
  return result.outputText ?? "";
}

function normalizeEventSourceRef(sourceRef: string, candidate: string): string {
  const trimmed = candidate.trim();
  if (!trimmed) {
    return sourceRef;
  }
  const sourcePath = sourcePathFromSourceRef(sourceRef);
  if (trimmed.startsWith("#L")) {
    return `${sourcePath}${trimmed}`;
  }
  if (trimmed === sourcePath) {
    return sourceRef;
  }
  return trimmed;
}

function toErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    return err.message || String(err);
  }
  return String(err);
}

function validateWorkflowEvents(sourceRef: string, events: RawEvent[]): RawEvent[] {
  return events.map((event) => {
    const action = normalizeWhitespace(event.action);
    if (!WORKFLOW_ACTIONS.has(action)) {
      throw new GraphExtractorError(
        "extractor_invalid_json",
        `graph extractor returned unsupported action=${JSON.stringify(action)}`,
      );
    }
    const normalizedSourceRef = normalizeEventSourceRef(sourceRef, event.source_ref);
    if (!PRECISE_SOURCE_REF_RE.test(normalizedSourceRef)) {
      throw new GraphExtractorError(
        "extractor_invalid_json",
        `graph extractor returned non-precise source_ref=${JSON.stringify(normalizedSourceRef)}`,
      );
    }
    return {
      ...event,
      action,
      actor: event.actor ? normalizeWhitespace(event.actor) : undefined,
      object: event.object ? normalizeWhitespace(event.object) : undefined,
      source_ref: normalizedSourceRef,
    };
  });
}

function isGraphExtractorError(value: unknown): value is GraphExtractorError {
  return value instanceof GraphExtractorError;
}

function classifyRuntimeFailure(err: unknown): GraphExtractorErrorCode {
  const message = toErrorMessage(err).toLowerCase();
  if (message.includes("timeout") || message.includes("timed out")) {
    return "extractor_timeout";
  }
  return "extractor_unavailable";
}

function wrapExtractorError(err: unknown): GraphExtractorError {
  if (isGraphExtractorError(err)) {
    return err;
  }
  const code = classifyRuntimeFailure(err);
  return new GraphExtractorError(code, toErrorMessage(err), { cause: err });
}

async function extractWithLlm(
  text: string,
  sourceRef: string,
  llmClient: LLMClient,
): Promise<RawEvent[]> {
  const request = buildExtractionPrompt(text, sourceRef);
  let outputText = "";
  try {
    outputText = coerceLlmOutputText(await llmClient.extractGraphEvents(request));
  } catch (err) {
    throw wrapExtractorError(err);
  }
  if (!outputText.trim()) {
    throw new GraphExtractorError(
      "extractor_empty_output",
      `graph extractor produced empty output for ${request.sourcePath}`,
    );
  }
  const parsed = parseGraphJsonBlockDetailed(outputText);
  if (!parsed.ok) {
    throw new GraphExtractorError(
      "extractor_invalid_json",
      `graph extractor output was not valid JSON for ${request.sourcePath}`,
    );
  }
  const events = validateWorkflowEvents(sourceRef, parsed.events);
  log.info(
    `canonical.extract.llm source_ref=${request.sourcePath} events=${events.length} precise=${events.every((event) => event.source_ref.includes("#L"))}`,
  );
  return events;
}

export function setDefaultExtractorClient(client: LLMClient | null): void {
  defaultLlmClient = client;
}

export function getDefaultExtractorSystemPrompt(): string {
  return EXTRACTOR_SYSTEM_PROMPT;
}

export function getGraphExtractorErrorCode(err: unknown): GraphExtractorErrorCode | null {
  return isGraphExtractorError(err) ? err.code : null;
}

export async function extract(
  text: string,
  sourceRef: string,
  llmClient?: LLMClient,
): Promise<RawEvent[]> {
  const client = llmClient ?? defaultLlmClient;
  if (!client) {
    throw new GraphExtractorError(
      "extractor_unavailable",
      `graph extractor runtime unavailable for ${sourceRef}`,
    );
  }
  try {
    return await extractWithLlm(text, sourceRef, client);
  } catch (err) {
    const extractorError = wrapExtractorError(err);
    log.warn(
      `[canonical] extract.llm_failed source_ref=${sourceRef} code=${extractorError.code} error=${extractorError.message}`,
    );
    throw extractorError;
  }
}

export function parseGraphJsonBlock(outputText: string): RawEvent[] {
  return parseGraphJsonBlockDetailed(outputText).events;
}

export function parseGraphJsonBlockWithStatus(outputText: string): GraphJsonParseResult {
  return parseGraphJsonBlockDetailed(outputText);
}
