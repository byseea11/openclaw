import crypto from "node:crypto";
import { formatErrorMessage } from "openclaw/plugin-sdk/error-runtime";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/memory-core";
import {
  GraphExtractorError,
  getDefaultExtractorSystemPrompt,
  type CanonicalExtractorRequest,
  type LLMClient,
} from "./extractor.js";

const GRAPH_EXTRACTOR_SESSION_KEY_PREFIX = "memory-graph-extractor-";
const GRAPH_EXTRACTOR_TIMEOUT_MS = 60_000;

type SubagentRuntime = OpenClawPluginApi["runtime"]["subagent"];
type Logger = Pick<OpenClawPluginApi["logger"], "warn">;

function buildExtractorSessionKey(sourceRef: string): string {
  const digest = crypto.createHash("sha1").update(sourceRef).digest("hex").slice(0, 16);
  return `${GRAPH_EXTRACTOR_SESSION_KEY_PREFIX}${digest}`;
}

function extractAssistantText(messages: unknown[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || typeof message !== "object" || Array.isArray(message)) {
      continue;
    }
    const record = message as Record<string, unknown>;
    if (record.role !== "assistant") {
      continue;
    }
    const content = record.content;
    if (typeof content === "string" && content.trim()) {
      return content.trim();
    }
    if (!Array.isArray(content)) {
      continue;
    }
    const text = content
      .filter(
        (part: unknown) =>
          part &&
          typeof part === "object" &&
          !Array.isArray(part) &&
          (part as Record<string, unknown>).type === "text" &&
          typeof (part as Record<string, unknown>).text === "string",
      )
      .map((part) => (part as { text: string }).text)
      .join("\n")
      .trim();
    if (text) {
      return text;
    }
  }
  return null;
}

async function deleteExtractorSession(
  subagent: SubagentRuntime,
  sessionKey: string,
  logger?: Logger,
): Promise<void> {
  try {
    await subagent.deleteSession({ sessionKey, deleteTranscript: true });
  } catch (err) {
    logger?.warn(
      `memory-core: graph extractor session cleanup failed (${formatErrorMessage(err)})`,
    );
  }
}

export function isGraphExtractorSessionKey(value: string | null | undefined): boolean {
  return value?.includes(GRAPH_EXTRACTOR_SESSION_KEY_PREFIX) ?? false;
}

export function createSubagentExtractorClient(
  subagent: SubagentRuntime | undefined,
  logger?: Logger,
): LLMClient | null {
  if (!subagent) {
    return null;
  }
  return {
    async extractGraphEvents(params: CanonicalExtractorRequest): Promise<string> {
      const sessionKey = buildExtractorSessionKey(params.sourceRef);
      let runId: string | null = null;
      try {
        const run = await subagent.run({
          sessionKey,
          idempotencyKey: sessionKey,
          message: params.prompt,
          extraSystemPrompt: getDefaultExtractorSystemPrompt(),
          deliver: false,
          disableTools: true,
          lane: "memory-graph-extractor",
        });
        runId = run.runId;
        const result = await subagent.waitForRun({
          runId,
          timeoutMs: GRAPH_EXTRACTOR_TIMEOUT_MS,
        });
        if (result.status !== "ok") {
          const detail =
            result.error && typeof result.error === "string" ? ` error=${result.error}` : "";
          const code =
            String(result.status).toLowerCase().includes("timeout") ||
            (typeof result.error === "string" && /timeout|timed out/i.test(result.error))
              ? "extractor_timeout"
              : "extractor_unavailable";
          throw new GraphExtractorError(
            code,
            `graph extractor subagent ended with status=${result.status}${detail}`,
          );
        }
        const { messages } = await subagent.getSessionMessages({
          sessionKey,
          limit: 12,
        });
        const outputText = extractAssistantText(messages);
        if (!outputText) {
          throw new GraphExtractorError(
            "extractor_empty_output",
            "graph extractor produced no assistant text",
          );
        }
        return outputText;
      } finally {
        await deleteExtractorSession(subagent, sessionKey, logger);
      }
    },
  };
}
