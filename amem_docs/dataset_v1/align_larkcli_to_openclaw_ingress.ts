#!/usr/bin/env bun

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseFeishuMessageEvent, type FeishuMessageEvent } from "../../extensions/feishu/src/bot.ts";

type RawMention = {
  id?: string;
  key?: string;
  name?: string;
};

type RawMessage = {
  content: string;
  create_time?: string;
  deleted?: boolean;
  mentions?: RawMention[];
  message_id: string;
  msg_type: string;
  sender?: {
    id?: string;
    id_type?: string;
    name?: string;
    sender_type?: string;
    tenant_key?: string;
  };
  thread_id?: string;
  updated?: boolean;
};

type RawImRow = {
  source_platform: "feishu";
  chat_id: string;
  message_scope: "main_chat" | "thread_reply";
  parent_message_id?: string;
  raw_message: RawMessage;
};

type AlignmentReport = {
  inputRows: number;
  eventRows: number;
  contextRows: number;
  skippedRows: number;
  skipped: Array<{
    messageId: string;
    reason: string;
  }>;
};

const DATASET_DIR = resolve("amem_docs/dataset_v1");
const INPUT_FILE = resolve(DATASET_DIR, "raw_channel_im_v0.jsonl");
const EVENTS_FILE = resolve(DATASET_DIR, "feishu_channel_events_v0.jsonl");
const CONTEXTS_FILE = resolve(DATASET_DIR, "feishu_message_contexts_v0.jsonl");
const REPORT_FILE = resolve(DATASET_DIR, "feishu_alignment_report_v0.json");

function parseJsonl<T>(file: string): T[] {
  return readFileSync(file, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as T);
}

function inferChatType(chatId: string): "group" | "p2p" | "private" {
  if (chatId.startsWith("oc_")) {
    return "group";
  }
  return "group";
}

function toMentions(rawMentions: RawMention[] | undefined): FeishuMessageEvent["message"]["mentions"] {
  if (!rawMentions || rawMentions.length === 0) {
    return undefined;
  }
  return rawMentions
    .filter((mention) => typeof mention.id === "string" && mention.id.trim().length > 0)
    .map((mention, index) => ({
      key: mention.key ?? `@_user_${index + 1}`,
      id: {
        open_id: mention.id?.trim(),
      },
      name: mention.name ?? "",
    }));
}

function toEvent(row: RawImRow): FeishuMessageEvent | null {
  const message = row.raw_message;
  const sender = message.sender;

  if (message.msg_type === "system") {
    return null;
  }

  if (message.msg_type !== "text") {
    return null;
  }

  return {
    sender: {
      sender_id: {
        open_id: sender?.id?.trim() || undefined,
      },
      sender_type: sender?.sender_type || undefined,
      tenant_key: sender?.tenant_key || undefined,
    },
    message: {
      message_id: message.message_id,
      root_id: row.parent_message_id || message.message_id,
      parent_id: row.parent_message_id || undefined,
      thread_id: message.thread_id || undefined,
      chat_id: row.chat_id,
      chat_type: inferChatType(row.chat_id),
      message_type: message.msg_type,
      content: JSON.stringify({ text: message.content }),
      create_time: message.create_time,
      mentions: toMentions(message.mentions),
    },
  };
}

const rows = parseJsonl<RawImRow>(INPUT_FILE);
const events: Array<Record<string, unknown>> = [];
const contexts: Array<Record<string, unknown>> = [];
const skipped: AlignmentReport["skipped"] = [];

for (const row of rows) {
  const event = toEvent(row);
  if (!event) {
    skipped.push({
      messageId: row.raw_message.message_id,
      reason: `unsupported message type for ingress alignment: ${row.raw_message.msg_type}`,
    });
    continue;
  }

  const context = parseFeishuMessageEvent(event);
  events.push({
    source_row_scope: row.message_scope,
    source_parent_message_id: row.parent_message_id ?? null,
    event,
  });
  contexts.push({
    source_row_scope: row.message_scope,
    source_parent_message_id: row.parent_message_id ?? null,
    context,
  });
}

writeFileSync(EVENTS_FILE, events.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");
writeFileSync(CONTEXTS_FILE, contexts.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");

const report: AlignmentReport = {
  inputRows: rows.length,
  eventRows: events.length,
  contextRows: contexts.length,
  skippedRows: skipped.length,
  skipped,
};

writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2) + "\n", "utf8");

console.log(
  JSON.stringify(
    {
      ok: true,
      input: INPUT_FILE,
      outputs: {
        events: EVENTS_FILE,
        contexts: CONTEXTS_FILE,
        report: REPORT_FILE,
      },
      report,
    },
    null,
    2,
  ),
);
