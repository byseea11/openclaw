import type { FeishuMessageContext } from "./types.js";
import type { FeishuMessageEvent } from "./event-types.js";
import type { ResolvedFeishuGroupSession } from "./bot-content.js";

export const FEISHU_TRACE_ENV = "OPENCLAW_FEISHU_TRACE";
export const FEISHU_TRACE_TAG = "FEISHU_TRACE";

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
