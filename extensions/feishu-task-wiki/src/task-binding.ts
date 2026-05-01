import { createHash } from "node:crypto";

export type TaskBindingStatus = "active" | "inactive";
export type TaskBindingSourceType = "thread" | "chat" | "doc" | "comment";
export type TaskBindingMatchReason = "thread_id" | "root_id" | "chat_id" | "source_id";

export type TaskProfile = {
  taskId: string;
  taskTitle: string;
  taskSummary: string;
  taskKeywords: string[];
};

export type TaskBindingRecord = TaskProfile & {
  sourceType: TaskBindingSourceType;
  sourceId: string;
  chatId: string | null;
  threadId: string | null;
  rootId: string | null;
  bindingStatus: TaskBindingStatus;
  createdAt: number;
  updatedAt: number;
};

export type TaskInitializationContext = {
  sourceType: TaskBindingSourceType;
  sourceId: string;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
  rootMessageText: string;
  replyTexts?: string[];
  chatTitle?: string | null;
  docTitle?: string | null;
  createdAt?: number;
};

export type TaskBindingLookupInput = {
  sourceType?: TaskBindingSourceType;
  sourceId?: string | null;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
};

export type TaskBindingMatch = {
  record: TaskBindingRecord;
  reason: TaskBindingMatchReason;
};

export function normalizeTaskText(input: string): string {
  return input
    .replace(/[@＠][^\s]+/g, " ")
    .replace(/[【\[][^】\]]+[】\]]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[。；;]+/g, "。")
    .trim();
}

function compactSentence(input: string, maxChars: number): string {
  const normalized = normalizeTaskText(input);
  if (!normalized) {
    return "";
  }
  return normalized.length <= maxChars ? normalized : `${normalized.slice(0, maxChars).trim()}…`;
}

function firstSentence(input: string): string {
  const normalized = normalizeTaskText(input);
  if (!normalized) {
    return "";
  }
  const split = normalized.split(/[。！？!?]/).map((part) => part.trim()).filter(Boolean);
  return split[0] ?? normalized;
}

function keywordCandidates(text: string): string[] {
  const normalized = normalizeTaskText(text);
  const matches = normalized.match(/[\u4e00-\u9fffA-Za-z0-9_-]{2,12}/g) ?? [];
  return matches.filter((token) => !/^(这个|那个|我们|你们|他们|然后|如果|所以|已经|还是)$/.test(token));
}

export function extractTaskKeywords(texts: string[], limit = 6): string[] {
  const counts = new Map<string, number>();
  for (const text of texts) {
    for (const token of keywordCandidates(text)) {
      counts.set(token, (counts.get(token) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"))
    .slice(0, limit)
    .map(([token]) => token);
}

export function resolveSourceScope(params: {
  sourceType: TaskBindingSourceType;
  sourceId: string;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
}): string {
  if (params.threadId?.trim()) {
    return `thread:${params.threadId.trim()}`;
  }
  if (params.rootId?.trim()) {
    return `thread:${params.rootId.trim()}`;
  }
  if (params.chatId?.trim()) {
    return `chat:${params.chatId.trim()}`;
  }
  return `${params.sourceType}:${params.sourceId.trim()}`;
}

export function createTaskProfile(context: TaskInitializationContext): TaskProfile {
  const rootSentence = firstSentence(context.rootMessageText);
  const titleSource = rootSentence || context.chatTitle?.trim() || context.docTitle?.trim() || "未命名任务";
  const taskTitle = compactSentence(titleSource, 36) || "未命名任务";
  const summaryParts = [
    context.chatTitle?.trim(),
    context.docTitle?.trim(),
    compactSentence(context.rootMessageText, 80),
    ...(context.replyTexts ?? []).slice(0, 3).map((text) => compactSentence(text, 48)),
  ].filter((value): value is string => Boolean(value));
  const taskSummary = compactSentence(summaryParts.join(" / "), 140) || taskTitle;
  const taskKeywords = extractTaskKeywords([
    context.rootMessageText,
    ...(context.replyTexts ?? []),
    context.chatTitle ?? "",
    context.docTitle ?? "",
  ]);
  const sourceScope = resolveSourceScope(context);
  const taskIdSeed = `${taskTitle}\n${sourceScope}`;
  const taskId = `task:${createHash("sha1").update(taskIdSeed).digest("hex").slice(0, 16)}`;
  return { taskId, taskTitle, taskSummary, taskKeywords };
}

export function buildTaskBindingRecord(context: TaskInitializationContext): TaskBindingRecord {
  const profile = createTaskProfile(context);
  const now = Number.isFinite(context.createdAt) ? (context.createdAt as number) : Date.now();
  return {
    ...profile,
    sourceType: context.sourceType,
    sourceId: context.sourceId.trim(),
    chatId: context.chatId?.trim() || null,
    threadId: context.threadId?.trim() || null,
    rootId: context.rootId?.trim() || null,
    bindingStatus: "active",
    createdAt: now,
    updatedAt: now,
  };
}

export function resolveTaskBindingMatch(
  records: TaskBindingRecord[],
  input: TaskBindingLookupInput,
): TaskBindingMatch | null {
  const activeRecords = records.filter((record) => record.bindingStatus === "active");
  const threadId = input.threadId?.trim();
  if (threadId) {
    const record = activeRecords.find((entry) => entry.threadId === threadId);
    if (record) {
      return { record, reason: "thread_id" };
    }
  }
  const rootId = input.rootId?.trim();
  if (rootId) {
    const record = activeRecords.find((entry) => entry.rootId === rootId);
    if (record) {
      return { record, reason: "root_id" };
    }
  }
  const chatId = input.chatId?.trim();
  if (chatId) {
    const record = activeRecords.find((entry) => entry.chatId === chatId);
    if (record) {
      return { record, reason: "chat_id" };
    }
  }
  const sourceId = input.sourceId?.trim();
  if (sourceId && input.sourceType) {
    const record = activeRecords.find(
      (entry) => entry.sourceType === input.sourceType && entry.sourceId === sourceId,
    );
    if (record) {
      return { record, reason: "source_id" };
    }
  }
  return null;
}

export class InMemoryTaskBindingIndex {
  private readonly records: TaskBindingRecord[] = [];

  list(): TaskBindingRecord[] {
    return [...this.records];
  }

  resolve(input: TaskBindingLookupInput): TaskBindingMatch | null {
    return resolveTaskBindingMatch(this.records, input);
  }

  bind(context: TaskInitializationContext): TaskBindingRecord {
    const existing = this.resolve({
      sourceType: context.sourceType,
      sourceId: context.sourceId,
      chatId: context.chatId,
      threadId: context.threadId,
      rootId: context.rootId,
    });
    if (existing) {
      return existing.record;
    }
    const record = buildTaskBindingRecord(context);
    this.records.push(record);
    return record;
  }
}
