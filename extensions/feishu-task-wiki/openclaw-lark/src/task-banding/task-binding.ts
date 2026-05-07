import { createHash } from "node:crypto";

export type TaskStatus = "active" | "inactive";
export type TaskBindingStatus = "active" | "inactive";
export type TaskBindingSourceType = "thread" | "chat" | "doc" | "comment";
export type TaskBindingMatchReason =
  | "thread_id"
  | "root_id"
  | "chat_id"
  | "source_id"
  | "task_key"
  | "thread_backfill"
  | "root_backfill";

export type CanonicalTaskRecord = {
  accountId: string;
  taskId: string;
  taskKey: string;
  taskTitle: string;
  taskSummary: string;
  taskKeywords: string[];
  taskStatus: TaskStatus;
  createdAt: number;
  updatedAt: number;
};

export type TaskSourceBindingRecord = {
  accountId: string;
  taskId: string;
  sourceType: TaskBindingSourceType;
  sourceId: string;
  chatId: string | null;
  threadId: string | null;
  rootId: string | null;
  bindingStatus: TaskBindingStatus;
  createdAt: number;
  updatedAt: number;
};

export type TaskProfile = Pick<
  CanonicalTaskRecord,
  "taskId" | "taskKey" | "taskTitle" | "taskSummary" | "taskKeywords"
>;

export type TaskInitializationContext = {
  accountId: string;
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
  accountId: string;
  sourceType?: TaskBindingSourceType;
  sourceId?: string | null;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
  taskKey?: string | null;
};

export type TaskBindingMatch = {
  task: CanonicalTaskRecord;
  binding: TaskSourceBindingRecord;
  reason: TaskBindingMatchReason;
};

export type TaskBindResult = {
  task: CanonicalTaskRecord;
  binding: TaskSourceBindingRecord;
  reason: TaskBindingMatchReason | "initialized";
};

export function normalizeTaskText(input: string): string {
  return input
    .replace(/[@＠][^\s]+/g, " ")
    .replace(/[【[][^】\]]+[】\]]/g, " ")
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
    .toSorted((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"))
    .slice(0, limit)
    .map(([token]) => token);
}

function normalizeAsciiTaskKey(prefix: string, sequence: string): string {
  return `${prefix.toUpperCase()}-${sequence}`;
}

function normalizeCjkTaskKey(prefix: string, sequence: string): string {
  return `${prefix}-${sequence}`;
}

export function extractCanonicalTaskKey(texts: string[]): string | null {
  for (const rawText of texts) {
    const text = normalizeTaskText(rawText);
    if (!text) {
      continue;
    }
    const asciiMatch = text.match(/\b([A-Za-z][A-Za-z0-9]{1,31})\s*[-_]\s*(\d{1,8})\b/u);
    if (asciiMatch) {
      return normalizeAsciiTaskKey(asciiMatch[1] ?? "", asciiMatch[2] ?? "");
    }
    const cjkMatch = text.match(/([\u4e00-\u9fff]{2,24})\s*[-－_]\s*(\d{1,8})/u);
    if (cjkMatch) {
      return normalizeCjkTaskKey(cjkMatch[1] ?? "", cjkMatch[2] ?? "");
    }
  }
  return null;
}

export function resolveSourceScope(params: {
  sourceType: TaskBindingSourceType;
  sourceId: string;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
}): string {
  if (params.sourceType === "doc" || params.sourceType === "comment") {
    return params.sourceId.trim();
  }
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

export function createTaskProfile(context: TaskInitializationContext): TaskProfile | null {
  const taskKey = extractCanonicalTaskKey([
    context.rootMessageText,
    ...(context.replyTexts ?? []),
    context.chatTitle ?? "",
    context.docTitle ?? "",
  ]);
  if (!taskKey) {
    return null;
  }
  const rootSentence = firstSentence(context.rootMessageText);
  const titleSource = rootSentence || context.chatTitle?.trim() || context.docTitle?.trim() || taskKey;
  const taskTitle = compactSentence(titleSource, 36) || taskKey;
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
  return {
    taskId: `task:${taskKey}`,
    taskKey,
    taskTitle,
    taskSummary,
    taskKeywords,
  };
}

export function buildCanonicalTaskRecord(context: TaskInitializationContext): CanonicalTaskRecord | null {
  const profile = createTaskProfile(context);
  if (!profile) {
    return null;
  }
  const now = Number.isFinite(context.createdAt) ? (context.createdAt as number) : Date.now();
  return {
    accountId: context.accountId,
    ...profile,
    taskStatus: "active",
    createdAt: now,
    updatedAt: now,
  };
}

export function buildTaskSourceBindingRecord(
  context: TaskInitializationContext,
  taskId: string,
): TaskSourceBindingRecord {
  const now = Number.isFinite(context.createdAt) ? (context.createdAt as number) : Date.now();
  return {
    accountId: context.accountId,
    taskId,
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

function mergeTaskKeywords(primary: string[], secondary: string[]): string[] {
  const merged = new Set<string>();
  for (const keyword of [...primary, ...secondary]) {
    const normalized = keyword.trim();
    if (normalized) {
      merged.add(normalized);
    }
  }
  return [...merged].slice(0, 8);
}

export function mergeTaskProfile(
  existing: CanonicalTaskRecord,
  incoming: TaskProfile | null,
): CanonicalTaskRecord {
  if (!incoming) {
    return existing;
  }
  return {
    ...existing,
    taskTitle: existing.taskTitle || incoming.taskTitle,
    taskSummary: existing.taskSummary || incoming.taskSummary,
    taskKeywords: mergeTaskKeywords(existing.taskKeywords, incoming.taskKeywords),
  };
}

export function findTaskById(
  tasks: CanonicalTaskRecord[],
  accountId: string,
  taskId: string,
): CanonicalTaskRecord | null {
  return tasks.find((task) => task.accountId === accountId && task.taskId === taskId && task.taskStatus === "active") ?? null;
}

export function findTaskByKey(
  tasks: CanonicalTaskRecord[],
  accountId: string,
  taskKey: string,
): CanonicalTaskRecord | null {
  return tasks.find((task) => task.accountId === accountId && task.taskKey === taskKey && task.taskStatus === "active") ?? null;
}

function resolveTaskForBinding(
  tasks: CanonicalTaskRecord[],
  binding: TaskSourceBindingRecord,
): CanonicalTaskRecord | null {
  return findTaskById(tasks, binding.accountId, binding.taskId);
}

export function resolveTaskBindingMatch(
  tasks: CanonicalTaskRecord[],
  bindings: TaskSourceBindingRecord[],
  input: TaskBindingLookupInput,
): TaskBindingMatch | null {
  const activeBindings = bindings.filter(
    (binding) => binding.accountId === input.accountId && binding.bindingStatus === "active",
  );

  const threadId = input.threadId?.trim();
  if (threadId) {
    const binding = activeBindings.find((entry) => entry.threadId === threadId);
    if (binding) {
      const task = resolveTaskForBinding(tasks, binding);
      if (task) {
        return { task, binding, reason: "thread_id" };
      }
    }
  }

  const rootId = input.rootId?.trim();
  if (rootId) {
    const binding = activeBindings.find((entry) => entry.rootId === rootId);
    if (binding) {
      const task = resolveTaskForBinding(tasks, binding);
      if (task) {
        return { task, binding, reason: "root_id" };
      }
    }
  }

  const sourceId = input.sourceId?.trim();
  if (sourceId && input.sourceType) {
    const binding = activeBindings.find(
      (entry) => entry.sourceType === input.sourceType && entry.sourceId === sourceId,
    );
    if (binding) {
      const task = resolveTaskForBinding(tasks, binding);
      if (task) {
        return { task, binding, reason: "source_id" };
      }
    }
  }

  const chatId = input.chatId?.trim();
  if (chatId) {
    const chatBindings = activeBindings.filter((entry) => entry.chatId === chatId);
    if (chatBindings.length > 0 && input.taskKey?.trim()) {
      const semantic = chatBindings.find((entry) => {
        const task = resolveTaskForBinding(tasks, entry);
        return task?.taskKey === input.taskKey;
      });
      if (semantic) {
        const task = resolveTaskForBinding(tasks, semantic);
        if (task) {
          return { task, binding: semantic, reason: "task_key" };
        }
      }
    }
    if (chatBindings.length > 1) {
      const taskIds = new Set(chatBindings.map((entry) => entry.taskId));
      if (taskIds.size === 1) {
        const preferred =
          chatBindings.find((entry) => !entry.threadId && !entry.rootId) ??
          chatBindings[0];
        const task = resolveTaskForBinding(tasks, preferred);
        if (task) {
          return { task, binding: preferred, reason: "chat_id" };
        }
      }
    }
    if (chatBindings.length === 1) {
      const task = resolveTaskForBinding(tasks, chatBindings[0]);
      if (task) {
        return { task, binding: chatBindings[0], reason: "chat_id" };
      }
    }
  }

  return null;
}

function shouldBackfillThreadBinding(
  existing: TaskBindingMatch,
  input: TaskInitializationContext,
): "thread_backfill" | "root_backfill" | null {
  if (existing.binding.threadId || existing.binding.rootId) {
    return null;
  }
  if (input.threadId?.trim()) {
    return "thread_backfill";
  }
  if (input.rootId?.trim()) {
    return "root_backfill";
  }
  return null;
}

function resolveExactSourceBinding(
  tasks: CanonicalTaskRecord[],
  bindings: TaskSourceBindingRecord[],
  input: TaskBindingLookupInput,
): TaskBindingMatch | null {
  const activeBindings = bindings.filter(
    (binding) => binding.accountId === input.accountId && binding.bindingStatus === "active",
  );
  const threadId = input.threadId?.trim();
  if (threadId) {
    const binding = activeBindings.find((entry) => entry.threadId === threadId);
    if (binding) {
      const task = resolveTaskForBinding(tasks, binding);
      if (task) {
        return { task, binding, reason: "thread_id" };
      }
    }
  }
  const rootId = input.rootId?.trim();
  if (rootId) {
    const binding = activeBindings.find((entry) => entry.rootId === rootId);
    if (binding) {
      const task = resolveTaskForBinding(tasks, binding);
      if (task) {
        return { task, binding, reason: "root_id" };
      }
    }
  }
  const sourceId = input.sourceId?.trim();
  if (sourceId && input.sourceType) {
    const binding = activeBindings.find(
      (entry) => entry.sourceType === input.sourceType && entry.sourceId === sourceId,
    );
    if (binding) {
      const task = resolveTaskForBinding(tasks, binding);
      if (task) {
        return { task, binding, reason: "source_id" };
      }
    }
  }
  return null;
}

export class InMemoryTaskBindingIndex {
  private readonly tasks: CanonicalTaskRecord[] = [];
  private readonly bindings: TaskSourceBindingRecord[] = [];

  listTasks(): CanonicalTaskRecord[] {
    return [...this.tasks];
  }

  listBindings(): TaskSourceBindingRecord[] {
    return [...this.bindings];
  }

  list(): TaskSourceBindingRecord[] {
    return this.listBindings();
  }

  resolveBinding(input: TaskBindingLookupInput): TaskBindingMatch | null {
    return resolveTaskBindingMatch(this.tasks, this.bindings, input);
  }

  listBindingsForTask(taskId: string): TaskSourceBindingRecord[] {
    return this.bindings.filter((binding) => binding.taskId === taskId && binding.bindingStatus === "active");
  }

  backfillThreadBinding(context: TaskInitializationContext, task: CanonicalTaskRecord): TaskBindResult | null {
    const reason = shouldBackfillThreadBinding(
      {
        task,
        binding: buildTaskSourceBindingRecord(
          {
            ...context,
            threadId: null,
            rootId: null,
          },
          task.taskId,
        ),
        reason: "chat_id",
      },
      context,
    );
    if (!reason) {
      return null;
    }
    const existing = resolveExactSourceBinding(this.tasks, this.bindings, {
      accountId: context.accountId,
      sourceType: "thread",
      sourceId: context.sourceId,
      chatId: context.chatId,
      threadId: context.threadId,
      rootId: context.rootId,
    });
    if (existing) {
      return {
        task: existing.task,
        binding: existing.binding,
        reason: existing.reason,
      };
    }
    const binding = buildTaskSourceBindingRecord(context, task.taskId);
    this.bindings.push(binding);
    return { task, binding, reason };
  }

  resolveOrInitializeTask(context: TaskInitializationContext): TaskBindResult | null {
    const profile = createTaskProfile(context);
    const existing = this.resolveBinding({
      accountId: context.accountId,
      sourceType: context.sourceType,
      sourceId: context.sourceId,
      chatId: context.chatId,
      threadId: context.threadId,
      rootId: context.rootId,
      taskKey: profile?.taskKey ?? null,
    });
    if (existing) {
      const backfilled = shouldBackfillThreadBinding(existing, context)
        ? this.backfillThreadBinding(context, existing.task)
        : null;
      return backfilled ?? existing;
    }

    if (!profile) {
      return null;
    }

    const existingTask = findTaskByKey(this.tasks, context.accountId, profile.taskKey);
    if (existingTask) {
      const mergedTask = mergeTaskProfile(existingTask, profile);
      Object.assign(existingTask, { ...mergedTask, updatedAt: Date.now() });
      const binding = buildTaskSourceBindingRecord(context, existingTask.taskId);
      this.bindings.push(binding);
      return {
        task: existingTask,
        binding,
        reason: "task_key",
      };
    }

    const task = buildCanonicalTaskRecord(context);
    if (!task) {
      return null;
    }
    this.tasks.push(task);
    const binding = buildTaskSourceBindingRecord(context, task.taskId);
    this.bindings.push(binding);
    return {
      task,
      binding,
      reason: "initialized",
    };
  }
}
