import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { parseSourceRef, type RawEvent } from "./schema.js";

const log = createSubsystemLogger("memory");

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

type DateContext = {
  currentDate?: string;
  defaultDate?: string;
  currentEntity?: string;
};

const CHECKBOX_RE = /^[-*]\s+\[( |x|X)\]\s+(.+)$/;
const STATUS_LINE_RE =
  /^(?<prefix>.+?)?(?:[-*]\s*)?(?:\*\*)?(?:status|当前状态|状态)(?:\*\*)?\s*[:：]\s*(?<status>[A-Za-z][A-Za-z _-]*)(?:\s*[（(][^)）]+[)）])?$/i;
const OWNER_LINE_RE =
  /^(?<prefix>.+?)?(?:[-*]\s*)?(?:\*\*)?(?:owner|跟进人|负责人)(?:\*\*)?\s*[:：]\s*(?<owner>.+)$/i;
const DECIDED_RE = /^(?:(?<actor>[A-Z][A-Za-z0-9_.-]+)\s+)?decided to\s+(?<decision>.+)$/i;
const EXPLICIT_STATUS_RE =
  /\b(?<object>[A-Za-z][\w./:-]*\d[\w./:-]*)\s+is\s+(?<status>blocked|done|in progress|pending|open)\b/i;
const INLINE_DATE_RE = /\b(20\d{2}-\d{2}-\d{2})\b/;
const DATE_HEADING_RE = /^(?:#{1,6}\s*)?(20\d{2}-\d{2}-\d{2})(?:\b.*)?$/;
const ENTITY_HEADING_RE =
  /^(?:\[[^\]]+\]\s+[A-Za-z_]+:\s*)?(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?<entity>[A-Za-z][\w./:-]*\d[\w./:-]*)\b/i;

const EXTRACTOR_SYSTEM_PROMPT = [
  "You extract canonical graph events from OpenClaw transcript or memory-file spans.",
  "Return JSON only, with this exact shape:",
  '{"events":[{"actor":"Alice","action":"assigned_owner","object":"FEISHU-231","status_before":null,"status_after":null,"occurred_at":"2026-04-18","source_ref":"transcripts/example.txt#L2-L2","confidence":0.82}]}',
  "Rules:",
  "- Never call tools and never add prose.",
  "- Use only facts that are explicitly supported by the provided text.",
  "- Prefer these actions when applicable: changed_status, assigned_owner, decided, updated_deadline.",
  "- `source_ref` must always point at the most specific supporting line using the provided source path and line numbers.",
  "- If nothing should be extracted, return {\"events\":[]}.",
].join("\n");

let defaultLlmClient: LLMClient | null = null;

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
  return parseSourceRef(sourceRef)?.path ?? sourceRef.split("#", 1)[0]?.replaceAll("\\", "/") ?? sourceRef;
}

function sourceRefForLine(path: string, line: number): string {
  return `${path}#L${line}-L${line}`;
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
      "Extract canonical graph events from the numbered lines below.",
      "Each event must use a line-precise source_ref like SOURCE_PATH#Lx-Lx.",
      "",
      numberedText,
    ].join("\n"),
  };
}

function normalizeStatus(raw: string): string {
  const normalized = normalizeWhitespace(raw).toLowerCase();
  switch (normalized) {
    case "x":
    case "done":
    case "complete":
    case "completed":
      return "done";
    case "blocked":
      return "blocked";
    case "in-progress":
    case "in progress":
      return "in_progress";
    case "todo":
    case "open":
    case "pending":
      return "pending";
    default:
      return normalized.replace(/\s+/g, "_");
  }
}

function extractDateFromSourcePath(sourcePath: string): string | undefined {
  const match = sourcePath.match(/(?:^|\/)(20\d{2}-\d{2}-\d{2})\.md$/);
  return match?.[1];
}

function updateDateContext(line: string, ctx: DateContext): void {
  const headingMatch = line.trim().match(DATE_HEADING_RE);
  if (headingMatch?.[1]) {
    ctx.currentDate = headingMatch[1];
    return;
  }
  const inlineMatch = line.match(INLINE_DATE_RE);
  if (inlineMatch?.[1]) {
    ctx.currentDate = inlineMatch[1];
  }
}

function updateEntityContext(line: string, ctx: DateContext): void {
  const headingMatch = line.trim().match(ENTITY_HEADING_RE);
  if (headingMatch?.groups?.entity) {
    ctx.currentEntity = headingMatch.groups.entity;
  }
}

function occurredAtForLine(line: string, ctx: DateContext): string | undefined {
  const inlineMatch = line.match(INLINE_DATE_RE);
  return inlineMatch?.[1] ?? ctx.currentDate ?? ctx.defaultDate;
}

function cleanTaskText(raw: string): string {
  return normalizeWhitespace(raw.replace(/\b(owner|status):.+$/i, "").replace(/\s+\([^)]*\)\s*$/, ""));
}

function extractEntityToken(body: string, fallback?: string): string | undefined {
  const tokenMatch = body.match(/\b([A-Za-z][\w./:-]*\d[\w./:-]*)\b/);
  if (tokenMatch?.[1]) {
    return tokenMatch[1];
  }
  const quoted = body.match(/"([^"]+)"/);
  if (quoted?.[1]) {
    return cleanTaskText(quoted[1]);
  }
  const cleaned = cleanTaskText(body)
    .replace(/^[-*]\s+/, "")
    .replace(/^task[:\s-]+/i, "");
  return /[\p{L}\p{N}]/u.test(cleaned) ? cleaned : fallback;
}

function extractOwner(prefix: string | undefined): string | undefined {
  const trimmed = normalizeWhitespace(prefix ?? "");
  if (!trimmed) {
    return undefined;
  }
  const ownerMatch = trimmed.match(/owner:\s*([@A-Za-z0-9_.-][A-Za-z0-9_@ .-]*)$/i);
  return ownerMatch?.[1] ? normalizeWhitespace(ownerMatch[1]).replace(/^@/, "") : undefined;
}

function normalizeOwnerValue(raw: string): string | undefined {
  const trimmed = normalizeWhitespace(raw);
  if (!trimmed) {
    return undefined;
  }
  const withoutTrailingNotes = trimmed
    .replace(/\s*[（(][^()（）]*[)）]\s*$/u, "")
    .replace(/\s*(?:[-,，;；].*)$/u, "")
    .trim();
  const normalized = withoutTrailingNotes.replace(/^@/, "").trim();
  return normalized || undefined;
}

function pushEvent(
  events: RawEvent[],
  event: Omit<RawEvent, "source_ref"> & { source_ref?: string },
  sourcePath: string,
  lineNumber: number,
): void {
  const action = normalizeWhitespace(event.action);
  if (!action) {
    return;
  }
  events.push({
    actor: event.actor ? normalizeWhitespace(event.actor) : undefined,
    action,
    object: event.object ? normalizeWhitespace(event.object) : undefined,
    status_after: event.status_after ? normalizeStatus(event.status_after) : undefined,
    occurred_at: event.occurred_at,
    source_ref: event.source_ref?.trim() || sourceRefForLine(sourcePath, lineNumber),
    confidence: event.confidence,
  });
}

function extractLineEvents(
  line: string,
  lineNumber: number,
  sourcePath: string,
  ctx: DateContext,
): RawEvent[] {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#")) {
    return [];
  }
  const occurredAt = occurredAtForLine(line, ctx);
  const events: RawEvent[] = [];

  const checkboxMatch = trimmed.match(CHECKBOX_RE);
  if (checkboxMatch) {
    const body = checkboxMatch[2] ?? "";
    pushEvent(
      events,
      {
        action: "changed_status",
        object: extractEntityToken(body, ctx.currentEntity),
        status_after: checkboxMatch[1]?.toLowerCase() === "x" ? "done" : "pending",
        actor: extractOwner(body),
        occurred_at: occurredAt,
        confidence: 0.72,
      },
      sourcePath,
      lineNumber,
    );
  }

  const statusMatch = trimmed.match(STATUS_LINE_RE);
  if (statusMatch?.groups?.status) {
    pushEvent(
      events,
      {
        action: "changed_status",
        object: extractEntityToken(statusMatch.groups.prefix ?? trimmed, ctx.currentEntity),
        status_after: statusMatch.groups.status,
        occurred_at: occurredAt,
        confidence: 0.78,
      },
      sourcePath,
      lineNumber,
    );
  }

  const ownerMatch = trimmed.match(OWNER_LINE_RE);
  if (ownerMatch?.groups?.owner) {
    const owner = normalizeOwnerValue(ownerMatch.groups.owner);
    pushEvent(
      events,
      {
        action: "assigned_owner",
        object: extractEntityToken(ownerMatch.groups.prefix ?? trimmed, ctx.currentEntity),
        actor: owner,
        occurred_at: occurredAt,
        confidence: 0.75,
      },
      sourcePath,
      lineNumber,
    );
  }

  const decidedMatch = trimmed.match(DECIDED_RE);
  if (decidedMatch?.groups?.decision) {
    pushEvent(
      events,
      {
        action: "decided",
        actor: decidedMatch.groups.actor,
        object: cleanTaskText(decidedMatch.groups.decision),
        occurred_at: occurredAt,
        confidence: 0.68,
      },
      sourcePath,
      lineNumber,
    );
  }

  const explicitStatusMatch = trimmed.match(EXPLICIT_STATUS_RE);
  if (explicitStatusMatch?.groups?.object && explicitStatusMatch.groups.status) {
    pushEvent(
      events,
      {
        action: "changed_status",
        object: explicitStatusMatch.groups.object,
        status_after: explicitStatusMatch.groups.status,
        occurred_at: occurredAt,
        confidence: 0.82,
      },
      sourcePath,
      lineNumber,
    );
  }

  return events;
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

async function extractWithLlm(
  text: string,
  sourceRef: string,
  llmClient: LLMClient,
): Promise<RawEvent[]> {
  const request = buildExtractionPrompt(text, sourceRef);
  const outputText = coerceLlmOutputText(await llmClient.extractGraphEvents(request));
  const parsed = parseGraphJsonBlockDetailed(outputText);
  if (!parsed.ok) {
    throw new Error(`graph extractor output was not valid JSON for ${request.sourcePath}`);
  }
  const events = parsed.events.map((event) => ({
    ...event,
    source_ref: normalizeEventSourceRef(sourceRef, event.source_ref),
  }));
  log.info(
    `canonical.extract.llm source_ref=${request.sourcePath} events=${events.length} precise=${events.every((event) => event.source_ref.includes("#L"))}`,
  );
  return events;
}

function extractWithRules(text: string, sourceRef: string): RawEvent[] {
  const sourcePath = sourcePathFromSourceRef(sourceRef);
  const ctx: DateContext = {
    defaultDate: extractDateFromSourcePath(sourcePath),
  };
  const events: RawEvent[] = [];
  const lines = text.split(/\r?\n/);
  for (const [index, line] of lines.entries()) {
    updateDateContext(line, ctx);
    updateEntityContext(line, ctx);
    events.push(...extractLineEvents(line, index + 1, sourcePath, ctx));
  }
  log.info(
    `canonical.extract.rules source_ref=${sourcePath} events=${events.length} precise=${events.every((event) => event.source_ref.includes("#L"))}`,
  );
  return events;
}

export function setDefaultExtractorClient(client: LLMClient | null): void {
  defaultLlmClient = client;
}

export function getDefaultExtractorSystemPrompt(): string {
  return EXTRACTOR_SYSTEM_PROMPT;
}

export async function extract(
  text: string,
  sourceRef: string,
  llmClient?: LLMClient,
): Promise<RawEvent[]> {
  const client = llmClient ?? defaultLlmClient;
  if (client) {
    try {
      return await extractWithLlm(text, sourceRef, client);
    } catch (err) {
      log.warn(`[canonical] extract.llm_failed source_ref=${sourceRef} error=${String(err)}`);
    }
  }
  return extractWithRules(text, sourceRef);
}

export function parseGraphJsonBlock(outputText: string): RawEvent[] {
  return parseGraphJsonBlockDetailed(outputText).events;
}

export function parseGraphJsonBlockWithStatus(outputText: string): GraphJsonParseResult {
  return parseGraphJsonBlockDetailed(outputText);
}
