import { SessionManager } from "@mariozechner/pi-coding-agent";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import {
  resolveMemoryAfterTurnObserver,
  resolveMemoryBeforeCompactionObserver,
  type MemoryTranscriptSpanEntry,
} from "../../plugins/memory-state.js";

type SessionManagerLike = ReturnType<typeof SessionManager.open>;
type SessionBranchEntry = ReturnType<SessionManagerLike["getBranch"]>[number];

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function extractTextContent(content: unknown): string {
  if (typeof content === "string") {
    return content.trim();
  }
  if (!Array.isArray(content)) {
    return "";
  }
  const parts: string[] = [];
  for (const item of content) {
    if (typeof item === "string") {
      const trimmed = item.trim();
      if (trimmed) {
        parts.push(trimmed);
      }
      continue;
    }
    if (!item || typeof item !== "object") {
      continue;
    }
    const block = item as { type?: unknown; text?: unknown; name?: unknown; content?: unknown };
    if (typeof block.text === "string" && block.text.trim()) {
      parts.push(block.text.trim());
      continue;
    }
    if (block.type === "text" && typeof block.content === "string" && block.content.trim()) {
      parts.push(block.content.trim());
      continue;
    }
    if (block.type === "toolCall") {
      const name = normalizeOptionalString(block.name);
      if (name) {
        parts.push(`[toolCall:${name}]`);
      }
    }
  }
  return parts.join(" ").trim();
}

function normalizeTimestamp(value: unknown): string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Date(value).toISOString();
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return null;
    }
    const parsed = Date.parse(trimmed);
    return Number.isFinite(parsed) ? new Date(parsed).toISOString() : trimmed;
  }
  return null;
}

function normalizeToolName(message: Record<string, unknown>): string | null {
  return (
    normalizeOptionalString(message.toolName) ??
    normalizeOptionalString(message.name) ??
    normalizeOptionalString(message.toolCallId)
  );
}

function normalizeBranchEntry(entry: SessionBranchEntry): MemoryTranscriptSpanEntry {
  if (entry.type === "message") {
    const message = entry.message as unknown as Record<string, unknown>;
    const messageRole = normalizeOptionalString(message.role);
    const text = extractTextContent(message.content);
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "message",
      messageRole,
      messageContent: text,
      toolName: messageRole === "toolResult" ? normalizeToolName(message) : null,
      toolResult: messageRole === "toolResult" ? text : null,
      timestamp: normalizeTimestamp(message.timestamp),
    };
  }

  if (entry.type === "compaction") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "compaction",
      messageRole: null,
      messageContent: normalizeOptionalString(entry.summary) ?? "",
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  if (entry.type === "custom_message") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "custom_message",
      messageRole: null,
      messageContent: normalizeOptionalString(entry.content) ?? "",
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  if (entry.type === "branch_summary") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "branch_summary",
      messageRole: null,
      messageContent: normalizeOptionalString(entry.summary) ?? "",
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  if (entry.type === "model_change") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "model_change",
      messageRole: null,
      messageContent: [normalizeOptionalString(entry.provider), normalizeOptionalString(entry.modelId)]
        .filter((value): value is string => Boolean(value))
        .join(" "),
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  if (entry.type === "thinking_level_change") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "thinking_level_change",
      messageRole: null,
      messageContent: normalizeOptionalString(entry.thinkingLevel) ?? "",
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  if (entry.type === "session_info") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "session_info",
      messageRole: null,
      messageContent: normalizeOptionalString(entry.name) ?? "",
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  if (entry.type === "label") {
    return {
      entryId: entry.id,
      parentId: entry.parentId ?? null,
      entryType: "label_change",
      messageRole: null,
      messageContent: [normalizeOptionalString(entry.targetId), normalizeOptionalString(entry.label)]
        .filter((value): value is string => Boolean(value))
        .join(" "),
      toolName: null,
      toolResult: null,
      timestamp: null,
    };
  }

  return {
    entryId: entry.id,
    parentId: entry.parentId ?? null,
    entryType: "custom",
    messageRole: null,
    messageContent:
      entry.type === "custom" ? JSON.stringify(entry.data) : "",
    toolName: null,
    toolResult: null,
    timestamp: null,
  };
}

function normalizeEntriesFromBranch(
  branch: SessionBranchEntry[],
  options?: { messageOffset?: number },
): MemoryTranscriptSpanEntry[] {
  const normalized = branch
    .map((entry) => normalizeBranchEntry(entry))
    .filter((entry) => entry.messageContent.length > 0 || entry.entryType === "message");
  if (typeof options?.messageOffset !== "number" || options.messageOffset <= 0) {
    return normalized;
  }
  const messageEntries = normalized.filter((entry) => entry.entryType === "message");
  return messageEntries.slice(options.messageOffset);
}

function openSessionManager(sessionFile: string): SessionManagerLike | null {
  const trimmed = sessionFile.trim();
  if (!trimmed) {
    return null;
  }
  return SessionManager.open(trimmed);
}

export async function observeMemoryAfterTurn(params: {
  cfg: OpenClawConfig;
  agentId: string;
  sessionId: string;
  sessionKey?: string;
  sessionFile: string;
  sessionManager?: SessionManagerLike;
  prePromptMessageCount: number;
  tokenBudget?: number;
  runtimeContext?: Record<string, unknown>;
}): Promise<void> {
  const observer = resolveMemoryAfterTurnObserver();
  if (!observer) {
    return;
  }
  const sessionManager = params.sessionManager ?? openSessionManager(params.sessionFile);
  if (!sessionManager) {
    return;
  }
  const entries = normalizeEntriesFromBranch(sessionManager.getBranch(), {
    messageOffset: params.prePromptMessageCount,
  });
  if (entries.length === 0) {
    return;
  }
  await observer({
    cfg: params.cfg,
    agentId: params.agentId,
    sessionId: params.sessionId,
    sessionKey: params.sessionKey,
    sessionFile: params.sessionFile,
    entries,
    prePromptMessageCount: params.prePromptMessageCount,
    tokenBudget: params.tokenBudget,
    runtimeContext: params.runtimeContext,
  });
}

export async function observeMemoryBeforeCompaction(params: {
  cfg?: OpenClawConfig;
  agentId: string;
  sessionId: string;
  sessionKey?: string;
  sessionFile: string;
  tokenCount?: number;
  runtimeContext?: Record<string, unknown>;
  sessionManager?: SessionManagerLike;
}): Promise<void> {
  const observer = resolveMemoryBeforeCompactionObserver();
  if (!observer) {
    return;
  }
  const sessionManager = params.sessionManager ?? openSessionManager(params.sessionFile);
  if (!sessionManager) {
    return;
  }
  const entries = normalizeEntriesFromBranch(sessionManager.getBranch());
  if (entries.length === 0) {
    return;
  }
  await observer({
    cfg: params.cfg,
    agentId: params.agentId,
    sessionId: params.sessionId,
    sessionKey: params.sessionKey,
    sessionFile: params.sessionFile,
    entries,
    tokenCount: params.tokenCount,
    runtimeContext: params.runtimeContext,
  });
}

export const __testing = {
  extractTextContent,
  normalizeEntriesFromBranch,
};
