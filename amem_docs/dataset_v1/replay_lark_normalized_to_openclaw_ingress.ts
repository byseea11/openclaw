#!/usr/bin/env tsx

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseFeishuMessageEvent, type FeishuMessageEvent } from "../../extensions/feishu/src/bot.ts";

type NormalizedMention = {
  id?: string;
  key?: string;
  name?: string;
};

type LarkNormalizedRow = {
  source_platform: "feishu";
  source_file?: string | null;
  source_record_id?: string | null;
  source_command?: string | null;
  chat_id: string;
  chat_type: "group" | "p2p" | "private" | "unknown";
  message_scope: "main_chat" | "thread_reply";
  message_id: string;
  root_id?: string | null;
  parent_id?: string | null;
  thread_id?: string | null;
  message_type: string;
  content_text: string;
  sender_open_id?: string | null;
  sender_id_type?: string | null;
  sender_type?: string | null;
  sender_name?: string | null;
  tenant_key?: string | null;
  mentions?: NormalizedMention[];
  create_time?: string | null;
  deleted?: boolean;
  updated?: boolean;
};

type ReplayValidation = {
  hasUrl: boolean;
  linkKinds: string[];
  mentionCount: number;
  contentChangedByParser: boolean;
  parserRestoredMentionTags: boolean;
  parserExpandedLinkedDocument: boolean;
};

const DATASET_DIR = resolve("amem_docs/dataset_v1");
const INPUT_FILE = resolve(DATASET_DIR, "lark_normalized_im_v0.jsonl");
const OUTPUT_FILE = resolve(DATASET_DIR, "openclaw_ingress_replay_v0.jsonl");
const REPORT_FILE = resolve(DATASET_DIR, "openclaw_ingress_replay_report_v0.json");

function parseJsonl<T>(file: string): T[] {
  return readFileSync(file, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as T);
}

function detectLinkKinds(text: string): string[] {
  const kinds = new Set<string>();
  if (/https?:\/\/\S+\/docx\//u.test(text)) kinds.add("docx");
  if (/https?:\/\/\S+\/wiki\//u.test(text)) kinds.add("wiki");
  if (/https?:\/\/\S+\/sheets\//u.test(text)) kinds.add("sheet");
  if (/https?:\/\/\S+\/base\//u.test(text)) kinds.add("base");
  return [...kinds];
}

function wrapMentions(mentions: NormalizedMention[] | undefined): FeishuMessageEvent["message"]["mentions"] {
  if (!mentions || mentions.length === 0) {
    return undefined;
  }
  return mentions
    .filter((mention) => typeof mention.id === "string" && mention.id.trim().length > 0)
    .map((mention, index) => ({
      key: mention.key ?? `@_user_${index + 1}`,
      id: { open_id: mention.id?.trim() },
      name: mention.name ?? "",
    }));
}

function toChatType(value: LarkNormalizedRow["chat_type"]): "group" | "p2p" | "private" {
  if (value === "p2p" || value === "private") {
    return value;
  }
  return "group";
}

function wrapEvent(row: LarkNormalizedRow): FeishuMessageEvent | null {
  if (row.message_type === "system") {
    return null;
  }

  return {
    sender: {
      sender_id: {
        open_id: row.sender_open_id?.trim() || undefined,
      },
      sender_type: row.sender_type || undefined,
      tenant_key: row.tenant_key || undefined,
    },
    message: {
      message_id: row.message_id,
      root_id: row.root_id || undefined,
      parent_id: row.parent_id || undefined,
      thread_id: row.thread_id || undefined,
      chat_id: row.chat_id,
      chat_type: toChatType(row.chat_type),
      message_type: row.message_type,
      content: JSON.stringify({ text: row.content_text }),
      create_time: row.create_time || undefined,
      mentions: wrapMentions(row.mentions),
    },
  };
}

function validateReplay(row: LarkNormalizedRow, parsedContent: string): ReplayValidation {
  const linkKinds = detectLinkKinds(row.content_text);
  const hasUrl = linkKinds.length > 0 || /https?:\/\//u.test(row.content_text);
  const parserRestoredMentionTags = parsedContent.includes("<at user_id=");
  const contentChangedByParser = parsedContent !== row.content_text;
  const parserExpandedLinkedDocument = parsedContent.length > row.content_text.length + 20;

  return {
    hasUrl,
    linkKinds,
    mentionCount: row.mentions?.length ?? 0,
    contentChangedByParser,
    parserRestoredMentionTags,
    parserExpandedLinkedDocument,
  };
}

const rows = parseJsonl<LarkNormalizedRow>(INPUT_FILE);
const replayRows: Array<Record<string, unknown>> = [];
const skipped: Array<{ messageId: string; reason: string }> = [];

for (const row of rows) {
  const event = wrapEvent(row);
  if (!event) {
    skipped.push({
      messageId: row.message_id,
      reason: `message_type=${row.message_type} is not replayed in v0`,
    });
    continue;
  }

  const context = parseFeishuMessageEvent(event);
  replayRows.push({
    source: row,
    event,
    context,
    validation: validateReplay(row, context.content),
  });
}

writeFileSync(OUTPUT_FILE, replayRows.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");

const report = {
  inputRows: rows.length,
  replayedRows: replayRows.length,
  skippedRows: skipped.length,
  skipped,
  docOrWikiOrSheetOrBaseLinkRows: replayRows.filter((row) => {
    const validation = row.validation as ReplayValidation;
    return validation.linkKinds.length > 0;
  }).length,
  parserExpandedLinkedDocumentRows: replayRows.filter((row) => {
    const validation = row.validation as ReplayValidation;
    return validation.parserExpandedLinkedDocument;
  }).length,
  parserRestoredMentionTagRows: replayRows.filter((row) => {
    const validation = row.validation as ReplayValidation;
    return validation.parserRestoredMentionTags;
  }).length,
};

writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2) + "\n", "utf8");

console.log(
  JSON.stringify(
    {
      ok: true,
      input: INPUT_FILE,
      outputs: {
        replay: OUTPUT_FILE,
        report: REPORT_FILE,
      },
      report,
    },
    null,
    2,
  ),
);
