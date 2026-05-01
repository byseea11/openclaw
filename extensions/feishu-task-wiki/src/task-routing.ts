import type {
  InMemoryTaskBindingIndex,
  TaskBindingLookupInput,
  TaskBindingMatchReason,
  TaskBindingRecord,
  TaskBindingSourceType,
  TaskInitializationContext,
} from "./task-binding.ts";
import { buildTaskBindingRecord, resolveSourceScope } from "./task-binding.ts";

export type TaskScopedRoute = {
  kind: "task_bound";
  taskId: string;
  taskTitle: string;
  sourceScope: string;
  sessionKey: string;
  reason: TaskBindingMatchReason | "initialized";
  binding: TaskBindingRecord;
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

function buildLookupInput(input: RuntimeRouteInput): TaskBindingLookupInput {
  return {
    sourceType: input.sourceType,
    sourceId: input.sourceId,
    chatId: input.chatId,
    threadId: input.threadId,
    rootId: input.rootId,
  };
}

function buildInitializationContext(input: RuntimeRouteInput): TaskInitializationContext | null {
  const rootMessageText = input.rootMessageText?.trim();
  if (!rootMessageText) {
    return null;
  }
  return {
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
  const existing = params.bindingIndex.resolve(buildLookupInput(params.input));
  if (existing) {
    const sourceScope = resolveSourceScope(existing.record);
    return {
      kind: "task_bound",
      taskId: existing.record.taskId,
      taskTitle: existing.record.taskTitle,
      sourceScope,
      sessionKey: buildTaskSessionKey({
        agentId: params.input.agentId,
        taskId: existing.record.taskId,
        sourceScope,
      }),
      reason: existing.reason,
      binding: existing.record,
    };
  }

  if (params.input.allowInitialization !== false) {
    const initContext = buildInitializationContext(params.input);
    if (initContext && (initContext.threadId || initContext.rootId || initContext.chatId)) {
      const binding = params.bindingIndex.bind(initContext);
      const sourceScope = resolveSourceScope(binding);
      return {
        kind: "task_bound",
        taskId: binding.taskId,
        taskTitle: binding.taskTitle,
        sourceScope,
        sessionKey: buildTaskSessionKey({
          agentId: params.input.agentId,
          taskId: binding.taskId,
          sourceScope,
        }),
        reason: "initialized",
        binding,
      };
    }
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
  const binding = buildTaskBindingRecord(params.context);
  const sourceScope = resolveSourceScope(binding);
  return {
    kind: "task_bound",
    taskId: binding.taskId,
    taskTitle: binding.taskTitle,
    sourceScope,
    sessionKey: buildTaskSessionKey({
      agentId: params.agentId,
      taskId: binding.taskId,
      sourceScope,
    }),
    reason: "initialized",
    binding,
  };
}
