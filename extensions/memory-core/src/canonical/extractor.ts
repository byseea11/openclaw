import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type {
  DecisionClaimValueJson,
  DecisionExtractionResult,
  DecisionSupportingContextQuote,
} from "./schema.js";

const log = createSubsystemLogger("memory");

export type CanonicalExtractorRequest = {
  prompt: string;
  sourceRef: string;
  sourcePath: string;
  lineCount: number;
};

export type DecisionPromptEntry = {
  entry_id: string;
  parent_id?: string | null;
  role: string;
  content: string;
  timestamp?: string | null;
};

export type DecisionCurrentStateContext = {
  topic_ref: string | null;
  decision_axis_key: string | null;
  active_conclusion: string | null;
  active_time_points: string[];
  active_rationales: string[];
  active_objections: string[];
};

export type DecisionExtractionEnvelope = {
  anchors: {
    task_refs: string[];
    thread_ids: string[];
    doc_refs: string[];
    project_names: string[];
    source_chat_ids: string[];
  };
  current_state_context: DecisionCurrentStateContext | null;
  context_entries: DecisionPromptEntry[];
  core_entries: DecisionPromptEntry[];
};

export type LLMClient = {
  extractGraphEvents(
    params: CanonicalExtractorRequest,
  ): Promise<string | { outputText?: string; extraction?: DecisionExtractionResult }>;
};

type DecisionJsonParseResult = {
  ok: boolean;
  extraction: DecisionExtractionResult;
};

export const GRAPH_EXTRACTOR_ERROR_CODES = [
  "extractor_unavailable",
  "extractor_timeout",
  "extractor_invalid_json",
  "extractor_empty_output",
] as const;

export type GraphExtractorErrorCode = (typeof GRAPH_EXTRACTOR_ERROR_CODES)[number];

const EXTRACTOR_SYSTEM_PROMPT = [
  "You extract quote-grounded decision memory events from OpenClaw transcript spans.",
  "Return JSON only with this exact shape:",
  '{"should_extract":true,"topic_ref":"topic:task:FEISHU-231:release_date","topic_anchors_json":{"task_refs":["task:FEISHU-231"]},"decision_axis_key":"release_date","decision_axis_text":"Whether the release date is confirmed","decision_axis_instance_id":null,"claims":[{"claim_field":"time_point","claim_text":"May 5 is still a target date, not a confirmed release date","claim_value_json":{"date":"2026-05-05","role":"target_date","modality":"not_confirmed"},"evidence_quote":"5 月 5 日只能视为目标日期，不是已确认发布日期","confidence":0.92}]}',
  'If nothing should be extracted, return {"should_extract":false,"topic_ref":null,"topic_anchors_json":null,"decision_axis_key":null,"decision_axis_text":null,"decision_axis_instance_id":null,"claims":[]}.',
  "Extract only atomic decision claims directly supported by evidence quotes from the text.",
  "Allowed claim_field values: conclusion, rationale, objection, stage, time_point.",
  "Do not invent anchors, topics, dates, conclusions, or reasons not directly supported by the text.",
  "Every claim must include a verbatim evidence_quote copied from a continuous span in the source text.",
  "Use CORE to decide whether to create new decision events.",
  "Use CONTEXT only to resolve references such as '这个', '刚才', '按上面说的', or '那个日期'.",
  "Do not generate a new decision event from CONTEXT alone.",
  "Do not use CURRENT_STATE_CONTEXT as evidence.",
  "Supporting context quotes may come only from CONTEXT entries.",
  "If CORE has no new semantic action, return should_extract=false or claims=[].",
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

function countEnvelopeLines(envelope: DecisionExtractionEnvelope): number {
  const lines = [
    "[ANCHORS]",
    JSON.stringify(envelope.anchors),
    "",
    "[CURRENT_STATE_CONTEXT]",
    JSON.stringify(envelope.current_state_context),
    "",
    "[CONTEXT]",
    ...envelope.context_entries.flatMap((entry) => [
      `ENTRY_ID: ${entry.entry_id}`,
      `ROLE: ${entry.role}`,
      entry.parent_id ? `PARENT_ID: ${entry.parent_id}` : null,
      entry.timestamp ? `TIMESTAMP: ${entry.timestamp}` : null,
      `CONTENT: ${entry.content}`,
      "",
    ]),
    "[CORE]",
    ...envelope.core_entries.flatMap((entry) => [
      `ENTRY_ID: ${entry.entry_id}`,
      `ROLE: ${entry.role}`,
      entry.parent_id ? `PARENT_ID: ${entry.parent_id}` : null,
      entry.timestamp ? `TIMESTAMP: ${entry.timestamp}` : null,
      `CONTENT: ${entry.content}`,
      "",
    ]),
  ].filter((line): line is string => line !== null);
  return lines.length;
}

function sourcePathFromSourceRef(sourceRef: string): string {
  return sourceRef.split("#", 1)[0]?.replaceAll("\\", "/") ?? sourceRef;
}

function renderPromptEntry(entry: DecisionPromptEntry): string {
  return [
    `ENTRY_ID: ${entry.entry_id}`,
    `ROLE: ${entry.role}`,
    entry.parent_id ? `PARENT_ID: ${entry.parent_id}` : null,
    entry.timestamp ? `TIMESTAMP: ${entry.timestamp}` : null,
    `CONTENT: ${entry.content}`,
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

function buildEnvelopePrompt(
  envelope: DecisionExtractionEnvelope,
  sourceRef: string,
): CanonicalExtractorRequest {
  const sourcePath = sourcePathFromSourceRef(sourceRef);
  const lineCount = countEnvelopeLines(envelope);
  return {
    sourceRef,
    sourcePath,
    lineCount,
    prompt: [
      `SOURCE_REF_RANGE: ${sourceRef}`,
      `SOURCE_PATH: ${sourcePath}`,
      `LINE_COUNT: ${lineCount}`,
      "",
      "Extract quote-grounded decision memory claims from the structured envelope below.",
      "Extract new claims only from CORE.",
      "Use CONTEXT only for reference resolution.",
      "Do not generate a new decision event from CONTEXT alone.",
      "Do not use CURRENT_STATE_CONTEXT as evidence.",
      "topic_ref and decision_axis must be derived only from reliable anchors in the text.",
      "",
      "[ANCHORS]",
      JSON.stringify(envelope.anchors),
      "",
      "[CURRENT_STATE_CONTEXT]",
      JSON.stringify(envelope.current_state_context),
      "",
      "[CONTEXT]",
      envelope.context_entries.map(renderPromptEntry).join("\n\n") || "(none)",
      "",
      "[CORE]",
      envelope.core_entries.map(renderPromptEntry).join("\n\n") || "(none)",
    ].join("\n"),
  };
}

function buildExtractionPrompt(
  input: string | DecisionExtractionEnvelope,
  sourceRef: string,
): CanonicalExtractorRequest {
  if (typeof input !== "string") {
    return buildEnvelopePrompt(input, sourceRef);
  }
  const sourcePath = sourcePathFromSourceRef(sourceRef);
  const { numberedText, lineCount } = lineNumberedText(input);
  return {
    sourceRef,
    sourcePath,
    lineCount,
    prompt: [
      `SOURCE_REF_RANGE: ${sourceRef}`,
      `SOURCE_PATH: ${sourcePath}`,
      `LINE_COUNT: ${lineCount}`,
      "",
      "Extract quote-grounded decision memory claims from the numbered lines below.",
      "topic_ref and decision_axis must be derived only from reliable anchors in the text.",
      "",
      numberedText,
    ].join("\n"),
  };
}

function toErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    return err.message || String(err);
  }
  return String(err);
}

function classifyRuntimeFailure(err: unknown): GraphExtractorErrorCode {
  const message = toErrorMessage(err).toLowerCase();
  if (message.includes("timeout") || message.includes("timed out")) {
    return "extractor_timeout";
  }
  return "extractor_unavailable";
}

function wrapExtractorError(err: unknown): GraphExtractorError {
  if (err instanceof GraphExtractorError) {
    return err;
  }
  return new GraphExtractorError(classifyRuntimeFailure(err), toErrorMessage(err), { cause: err });
}

function isDecisionExtractionResult(value: unknown): value is DecisionExtractionResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.should_extract === "boolean" && Array.isArray(record.claims);
}

function normalizeExtraction(result: DecisionExtractionResult): DecisionExtractionResult {
  function sanitizeSupportingContextQuotes(
    value: unknown,
  ): DecisionSupportingContextQuote[] | undefined {
    if (!Array.isArray(value)) {
      return undefined;
    }
    const quotes = value
      .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry))
      .map((entry) => {
        const record = entry as Record<string, unknown>;
        if (typeof record.quote !== "string" || record.source !== "context") {
          return null;
        }
        return {
          quote: record.quote.trim(),
          entry_id: typeof record.entry_id === "string" ? record.entry_id.trim() : null,
          source: "context" as const,
        };
      })
      .filter((entry): entry is DecisionSupportingContextQuote => Boolean(entry?.quote));
    return quotes.length > 0 ? quotes : undefined;
  }

  function sanitizeClaimValueJson(value: unknown): DecisionClaimValueJson | null {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }
    const next: DecisionClaimValueJson = { ...(value as Record<string, unknown>) };
    if (typeof next.core_entry_id === "string") {
      next.core_entry_id = next.core_entry_id.trim();
    } else {
      delete next.core_entry_id;
    }
    const quotes = sanitizeSupportingContextQuotes(next.supporting_context_quotes);
    if (quotes) {
      next.supporting_context_quotes = quotes;
    } else {
      delete next.supporting_context_quotes;
    }
    return next;
  }

  return {
    should_extract: result.should_extract,
    topic_ref: typeof result.topic_ref === "string" ? result.topic_ref.trim() : null,
    topic_anchors_json:
      result.topic_anchors_json && typeof result.topic_anchors_json === "object"
        ? result.topic_anchors_json
        : null,
    decision_axis_key:
      typeof result.decision_axis_key === "string" ? result.decision_axis_key.trim() as never : null,
    decision_axis_text:
      typeof result.decision_axis_text === "string" ? normalizeWhitespace(result.decision_axis_text) : null,
    decision_axis_instance_id:
      typeof result.decision_axis_instance_id === "string"
        ? result.decision_axis_instance_id.trim()
        : null,
    claims: result.claims
      .filter((claim) => claim && typeof claim === "object")
      .map((claim) => ({
        claim_field: claim.claim_field,
        claim_text: normalizeWhitespace(claim.claim_text),
        claim_value_json: sanitizeClaimValueJson(claim.claim_value_json),
        evidence_quote: claim.evidence_quote.trim(),
        confidence: Number(claim.confidence ?? 0),
      })),
    overflow_warning: result.overflow_warning === true,
  };
}

function parseDecisionJsonBlockDetailed(outputText: string): DecisionJsonParseResult {
  const blocks = [...outputText.matchAll(/```json\s*([\s\S]*?)```/gi)].map(
    (match) => match[1] ?? "",
  );
  const candidates = blocks.length > 0 ? blocks.toReversed() : [outputText];
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.trim()) as unknown;
      if (!isDecisionExtractionResult(parsed)) {
        continue;
      }
      return { ok: true, extraction: normalizeExtraction(parsed) };
    } catch {
      // continue
    }
  }
  return {
    ok: false,
    extraction: {
      should_extract: false,
      topic_ref: null,
      topic_anchors_json: null,
      decision_axis_key: null,
      decision_axis_text: null,
      decision_axis_instance_id: null,
      claims: [],
    },
  };
}

function coerceLlmOutputText(
  result: string | { outputText?: string; extraction?: DecisionExtractionResult },
): string {
  if (typeof result === "string") {
    return result;
  }
  if (result.extraction) {
    return JSON.stringify(result.extraction);
  }
  return result.outputText ?? "";
}

async function extractWithLlm(
  input: string | DecisionExtractionEnvelope,
  sourceRef: string,
  llmClient: LLMClient,
): Promise<DecisionExtractionResult> {
  const request = buildExtractionPrompt(input, sourceRef);
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
  const parsed = parseDecisionJsonBlockDetailed(outputText);
  if (!parsed.ok) {
    throw new GraphExtractorError(
      "extractor_invalid_json",
      `graph extractor output was not valid JSON for ${request.sourcePath}`,
    );
  }
  log.info(
    `canonical.extract.llm source_ref=${request.sourcePath} claims=${parsed.extraction.claims.length} should_extract=${parsed.extraction.should_extract}`,
  );
  return parsed.extraction;
}

export function setDefaultExtractorClient(client: LLMClient | null): void {
  defaultLlmClient = client;
}

export function getDefaultExtractorSystemPrompt(): string {
  return EXTRACTOR_SYSTEM_PROMPT;
}

export function getGraphExtractorErrorCode(err: unknown): GraphExtractorErrorCode | null {
  return err instanceof GraphExtractorError ? err.code : null;
}

export async function extract(
  input: string | DecisionExtractionEnvelope,
  sourceRef: string,
  llmClient?: LLMClient,
): Promise<DecisionExtractionResult> {
  const client = llmClient ?? defaultLlmClient;
  if (!client) {
    throw new GraphExtractorError(
      "extractor_unavailable",
      `graph extractor runtime unavailable for ${sourceRef}`,
    );
  }
  try {
    return await extractWithLlm(input, sourceRef, client);
  } catch (err) {
    const extractorError = wrapExtractorError(err);
    log.warn(
      `[canonical] extract.llm_failed source_ref=${sourceRef} code=${extractorError.code} error=${extractorError.message}`,
    );
    throw extractorError;
  }
}

export function parseGraphJsonBlock(outputText: string): DecisionExtractionResult {
  return parseDecisionJsonBlockDetailed(outputText).extraction;
}

export function parseGraphJsonBlockWithStatus(outputText: string): DecisionJsonParseResult {
  return parseDecisionJsonBlockDetailed(outputText);
}
