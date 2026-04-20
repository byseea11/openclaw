import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FEISHU_TRACE_ENV,
  FEISHU_TRACE_TAG,
  recordFeishuIngressTrace,
  recordFeishuNormalizedTrace,
  recordFeishuRouteTrace,
} from "./trace.js";
import type { FeishuMessageEvent } from "./event-types.js";
import type { FeishuMessageContext } from "./types.js";

const originalTraceEnv = process.env[FEISHU_TRACE_ENV];

function buildEvent(): FeishuMessageEvent {
  return {
    sender: {
      sender_id: {
        open_id: "ou_user_123",
        user_id: "user_123",
        union_id: "union_123",
      },
      sender_type: "user",
      tenant_key: "tenant_123",
    },
    message: {
      message_id: "om_123",
      root_id: "om_root_1",
      parent_id: "om_parent_1",
      thread_id: "omt_1",
      chat_id: "oc_123",
      chat_type: "group",
      message_type: "text",
      content: "{\"text\":\"FEISHU-231 blocked by legal approval\"}",
      create_time: "1710000000",
      mentions: [
        {
          key: "@_user_1",
          id: { open_id: "ou_bot_1" },
          name: "OpenClaw",
        },
      ],
    },
  };
}

function buildContext(): FeishuMessageContext {
  return {
    chatId: "oc_123",
    messageId: "om_123",
    senderId: "user_123",
    senderOpenId: "ou_user_123",
    chatType: "group",
    mentionedBot: true,
    hasAnyMention: true,
    rootId: "om_root_1",
    parentId: "om_parent_1",
    threadId: "omt_1",
    content: "FEISHU-231 blocked by legal approval",
    contentType: "text",
    mentionTargets: [{ openId: "ou_reviewer_1", name: "Carol", key: "@_user_2" }],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  if (originalTraceEnv === undefined) {
    delete process.env[FEISHU_TRACE_ENV];
    return;
  }
  process.env[FEISHU_TRACE_ENV] = originalTraceEnv;
});

describe("Feishu trace logging", () => {
  it("stays silent when the env switch is disabled", () => {
    delete process.env[FEISHU_TRACE_ENV];
    const log = vi.fn();

    recordFeishuIngressTrace({
      log,
      accountId: "default",
      event: buildEvent(),
    });

    expect(log).not.toHaveBeenCalled();
  });

  it("logs ingress, normalized content, and route details when enabled", () => {
    process.env[FEISHU_TRACE_ENV] = "1";
    const log = vi.fn();
    const event = buildEvent();
    const ctx = buildContext();

    recordFeishuIngressTrace({
      log,
      accountId: "default",
      event,
    });
    recordFeishuNormalizedTrace({
      log,
      accountId: "default",
      ctx,
      rawContent: event.message.content,
      senderUserId: event.sender.sender_id.user_id ?? null,
      senderName: "Alice",
    });
    recordFeishuRouteTrace({
      log,
      accountId: "default",
      ctx,
      groupSession: {
        peerId: "oc_123:topic:om_root_1",
        parentPeer: { kind: "group", id: "oc_123" },
        groupSessionScope: "group_topic",
        replyInThread: true,
        threadReply: true,
      },
      route: {
        sessionKey: "agent:main:feishu:group:oc_123:topic:om_root_1",
        agentId: "main",
        matchedBy: "binding.channel",
        lastRoutePolicy: "sticky",
      },
      peerId: "oc_123:topic:om_root_1",
      parentPeerId: "oc_123",
      replyInThread: true,
      currentConversationId: "oc_123:topic:om_root_1",
      parentConversationId: "oc_123",
    });

    const loggedJson = log.mock.calls.map((call) => {
      const line = String(call[0]);
      const jsonStart = line.indexOf("{");
      return JSON.parse(line.slice(jsonStart)) as Record<string, unknown>;
    });

    expect(loggedJson).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          tag: FEISHU_TRACE_TAG,
          stage: "message_event_received",
          raw_event: expect.objectContaining({
            sender: expect.objectContaining({
              open_id: "ou_user_123",
            }),
            message: expect.objectContaining({
              chat_id: "oc_123",
              content: "{\"text\":\"FEISHU-231 blocked by legal approval\"}",
            }),
          }),
        }),
        expect.objectContaining({
          tag: FEISHU_TRACE_TAG,
          stage: "message_normalized",
          normalized: expect.objectContaining({
            parsed_content: "FEISHU-231 blocked by legal approval",
            sender_name: "Alice",
            mention_targets: [{ open_id: "ou_reviewer_1", name: "Carol", key: "@_user_2" }],
          }),
        }),
        expect.objectContaining({
          tag: FEISHU_TRACE_TAG,
          stage: "route_resolved",
          route: expect.objectContaining({
            session_key: "agent:main:feishu:group:oc_123:topic:om_root_1",
          }),
          session_scope: expect.objectContaining({
            peer_id: "oc_123:topic:om_root_1",
            group_session: expect.objectContaining({
              group_session_scope: "group_topic",
            }),
          }),
        }),
      ]),
    );
  });
});
