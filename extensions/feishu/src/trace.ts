import fs from "node:fs/promises";
import path from "node:path";
import type { FeishuMessageContext } from "./types.js";
import type { FeishuMessageEvent } from "./event-types.js";
import type { ResolvedFeishuGroupSession } from "./bot-content.js";

export const FEISHU_TRACE_ENV = "OPENCLAW_FEISHU_TRACE";
export const FEISHU_TRACE_TAG = "FEISHU_TRACE";
export const FEISHU_INGRESS_CAPTURE_DIR_ENV = "OPENCLAW_FEISHU_INGRESS_CAPTURE_DIR";

const ingressCaptureWriteQueue = new Map<string, Promise<void>>();

type FeishuLogger = ((...args: unknown[]) => void) | undefined;

function isTruthyEnv(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  return ["1", "true", "yes", "on", "debug"].includes(value.trim().toLowerCase());
}

function normalizeWhitespace(value: string, limit = 600): string {
  return value.replace(/\s+/g, " ").trim().slice(0, limit);
}

function simplifyMentions(mentions: FeishuMessageEvent["message"]["mentions"]): Array<Record<string, unknown>> {
  if (!mentions?.length) {
    return [];
  }
  return mentions.map((mention) => ({
    key: mention.key,
    name: mention.name,
    open_id: mention.id.open_id ?? null,
    user_id: mention.id.user_id ?? null,
    union_id: mention.id.union_id ?? null,
    tenant_key: mention.tenant_key ?? null,
  }));
}

function recordTrace(params: {
  log?: FeishuLogger;
  accountId: string;
  stage: string;
  payload: Record<string, unknown>;
}): void {
  if (!isTruthyEnv(process.env[FEISHU_TRACE_ENV])) {
    return;
  }
  const traceEvent = {
    ts: new Date().toISOString(),
    tag: FEISHU_TRACE_TAG,
    stage: params.stage,
    ...params.payload,
  };
  try {
    params.log?.(`feishu[${params.accountId}]: ${JSON.stringify(traceEvent)}`);
  } catch (err) {
    params.log?.(`feishu[${params.accountId}]: ${FEISHU_TRACE_TAG} serialize_failed=${String(err)}`);
  }
}

function resolveFeishuIngressCaptureDir(): string | null {
  const dir = process.env[FEISHU_INGRESS_CAPTURE_DIR_ENV]?.trim();
  return dir ? dir : null;
}

function enqueueIngressCaptureWrite(filePath: string, row: Record<string, unknown>): Promise<void> {
  const previous = ingressCaptureWriteQueue.get(filePath) ?? Promise.resolve();
  const next = previous.then(async () => {
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.appendFile(filePath, `${JSON.stringify(row)}\n`, "utf8");
  });
  ingressCaptureWriteQueue.set(filePath, next.catch(() => {}));
  return next;
}

function recordFeishuIngressCaptureRow(params: {
  log?: FeishuLogger;
  accountId: string;
  fileName: string;
  row: Record<string, unknown>;
}): void {
  const captureDir = resolveFeishuIngressCaptureDir();
  if (!captureDir) {
    return;
  }
  const filePath = path.join(captureDir, params.fileName);
  void enqueueIngressCaptureWrite(filePath, {
    ts: new Date().toISOString(),
    account_id: params.accountId,
    ...params.row,
  }).catch((err) => {
    params.log?.(
      `feishu[${params.accountId}]: failed to write ingress capture ${params.fileName}: ${String(err)}`,
    );
  });
}

export async function flushFeishuIngressCaptureWritesForTest(): Promise<void> {
  await Promise.all([...ingressCaptureWriteQueue.values()]);
}

export function recordFeishuIngressTrace(params: {
  log?: FeishuLogger;
  accountId: string;
  event: FeishuMessageEvent;
}): void {
  const { event } = params;
  recordTrace({
    log: params.log,
    accountId: params.accountId,
    stage: "message_event_received",
    payload: {
      raw_event: {
        sender: {
          open_id: event.sender.sender_id.open_id ?? null,
          user_id: event.sender.sender_id.user_id ?? null,
          union_id: event.sender.sender_id.union_id ?? null,
          sender_type: event.sender.sender_type ?? null,
          tenant_key: event.sender.tenant_key ?? null,
        },
        message: {
          message_id: event.message.message_id,
          chat_id: event.message.chat_id,
          chat_type: event.message.chat_type,
          root_id: event.message.root_id ?? null,
          parent_id: event.message.parent_id ?? null,
          thread_id: event.message.thread_id ?? null,
          message_type: event.message.message_type,
          content: event.message.content,
          create_time: event.message.create_time ?? null,
          mentions: simplifyMentions(event.message.mentions),
        },
      },
    },
  });
  recordFeishuIngressCaptureRow({
    log: params.log,
    accountId: params.accountId,
    fileName: "feishu_message_events.jsonl",
    row: {
      stage: "message_event_received",
      event,
    },
  });
}

export function recordFeishuNormalizedTrace(params: {
  log?: FeishuLogger;
  accountId: string;
  ctx: FeishuMessageContext;
  rawContent: string;
  senderUserId?: string | null;
  senderName?: string | null;
}): void {
  recordTrace({
    log: params.log,
    accountId: params.accountId,
    stage: "message_normalized",
    payload: {
      normalized: {
        chat_id: params.ctx.chatId,
        chat_type: params.ctx.chatType,
        message_id: params.ctx.messageId,
        sender_open_id: params.ctx.senderOpenId,
        sender_user_id: params.senderUserId ?? null,
        sender_name: params.senderName ?? null,
        root_id: params.ctx.rootId ?? null,
        parent_id: params.ctx.parentId ?? null,
        thread_id: params.ctx.threadId ?? null,
        content_type: params.ctx.contentType,
        raw_content: normalizeWhitespace(params.rawContent, 1000),
        parsed_content: normalizeWhitespace(params.ctx.content, 1000),
        mentioned_bot: params.ctx.mentionedBot,
        has_any_mention: params.ctx.hasAnyMention,
        mention_targets:
          params.ctx.mentionTargets?.map((target) => ({
            open_id: target.openId,
            name: target.name,
            key: target.key,
          })) ?? [],
      },
    },
  });
  recordFeishuIngressCaptureRow({
    log: params.log,
    accountId: params.accountId,
    fileName: "feishu_message_contexts.jsonl",
    row: {
      stage: "message_normalized",
      raw_content: params.rawContent,
      sender_user_id: params.senderUserId ?? null,
      sender_name: params.senderName ?? null,
      context: params.ctx,
    },
  });
}

export function recordFeishuRouteTrace(params: {
  log?: FeishuLogger;
  accountId: string;
  ctx: FeishuMessageContext;
  groupSession: ResolvedFeishuGroupSession | null;
  route: {
    sessionKey: string;
    agentId?: string;
    matchedBy?: string;
    lastRoutePolicy?: string;
  };
  peerId: string;
  parentPeerId: string | null;
  replyInThread: boolean;
  currentConversationId: string;
  parentConversationId?: string;
}): void {
  recordTrace({
    log: params.log,
    accountId: params.accountId,
    stage: "route_resolved",
    payload: {
      route: {
        session_key: params.route.sessionKey,
        agent_id: params.route.agentId ?? null,
        matched_by: params.route.matchedBy ?? null,
        last_route_policy: params.route.lastRoutePolicy ?? null,
      },
      session_scope: {
        chat_id: params.ctx.chatId,
        chat_type: params.ctx.chatType,
        peer_id: params.peerId,
        parent_peer_id: params.parentPeerId,
        current_conversation_id: params.currentConversationId,
        parent_conversation_id: params.parentConversationId ?? null,
        reply_in_thread: params.replyInThread,
        group_session:
          params.groupSession === null
            ? null
            : {
                peer_id: params.groupSession.peerId,
                parent_peer_id: params.groupSession.parentPeer?.id ?? null,
                group_session_scope: params.groupSession.groupSessionScope,
                reply_in_thread: params.groupSession.replyInThread,
                thread_reply: params.groupSession.threadReply,
              },
      },
    },
  });
}
