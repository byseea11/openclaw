import type {
  CanonicalTaskRecord,
  InMemoryTaskBindingIndex,
  TaskBindingMatchReason,
  TaskSourceBindingRecord,
  TaskBindingSourceType,
  TaskInitializationContext,
} from "./task-binding.ts";
import { buildCanonicalTaskRecord, buildTaskSourceBindingRecord, resolveSourceScope } from "./task-binding.ts";

export type TaskScopedRoute = {
  kind: "task_bound";
  taskId: string;
  taskTitle: string;
  sourceScope: string;
  sessionKey: string;
  reason: TaskBindingMatchReason | "initialized";
  task: CanonicalTaskRecord;
  binding: TaskSourceBindingRecord;
};

export type ConversationScopedRoute = {
  kind: "conversation";
  sessionKey: string;
};

export type TaskRouteDecision = TaskScopedRoute | ConversationScopedRoute;

export type RuntimeRouteInput = {
  agentId: string;
  conversationSessionKey: string;
  sourceType: TaskBindingSourceType;
  sourceId: string;
  chatId?: string | null;
  threadId?: string | null;
  rootId?: string | null;
  rootMessageText?: string;
  replyTexts?: string[];
  chatTitle?: string | null;
  docTitle?: string | null;
  allowInitialization?: boolean;
};

export function buildTaskSessionKey(params: {
  agentId: string;
  taskId: string;
  sourceScope: string;
}): string {
  return `agent:${params.agentId}:feishu-task:${params.taskId}:${params.sourceScope}`;
}

function buildInitializationContext(input: RuntimeRouteInput): TaskInitializationContext | null {
  const rootMessageText = input.rootMessageText?.trim();
  if (!rootMessageText) {
    return null;
  }
  return {
    accountId: input.agentId,
    sourceType: input.sourceType,
    sourceId: input.sourceId,
    chatId: input.chatId,
    threadId: input.threadId,
    rootId: input.rootId,
    rootMessageText,
    replyTexts: input.replyTexts,
    chatTitle: input.chatTitle,
    docTitle: input.docTitle,
  };
}

export function resolveTaskFirstRoute(params: {
  bindingIndex: InMemoryTaskBindingIndex;
  input: RuntimeRouteInput;
}): TaskRouteDecision {
  const initContext = buildInitializationContext(params.input);
  const resolved = initContext ? params.bindingIndex.resolveOrInitializeTask(initContext) : null;
  if (resolved) {
    const sourceScope = resolveSourceScope(resolved.binding);
    return {
      kind: "task_bound",
      taskId: resolved.task.taskId,
      taskTitle: resolved.task.taskTitle,
      sourceScope,
      sessionKey: buildTaskSessionKey({
        agentId: params.input.agentId,
        taskId: resolved.task.taskId,
        sourceScope,
      }),
      reason: resolved.reason,
      task: resolved.task,
      binding: resolved.binding,
    };
  }

  return {
    kind: "conversation",
    sessionKey: params.input.conversationSessionKey,
  };
}

export function buildBoundRouteFromContext(params: {
  agentId: string;
  context: TaskInitializationContext;
}): TaskScopedRoute {
  const task = buildCanonicalTaskRecord(params.context);
  if (!task) {
    throw new Error("task key is required to build a task-bound route");
  }
  const binding = buildTaskSourceBindingRecord(params.context, task.taskId);
  const sourceScope = resolveSourceScope(binding);
  return {
    kind: "task_bound",
    taskId: task.taskId,
    taskTitle: task.taskTitle,
    sourceScope,
    sessionKey: buildTaskSessionKey({
      agentId: params.agentId,
      taskId: task.taskId,
      sourceScope,
    }),
    reason: "initialized",
    task,
    binding,
  };
}
