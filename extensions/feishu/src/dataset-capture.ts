import fs from "node:fs/promises";
import path from "node:path";
import type { MentionTarget } from "./mention-target.types.js";
import type { FeishuMessageEvent } from "./event-types.js";
import type { FeishuMessageContext, FeishuDatasetCaptureConfig } from "./types.js";

const TASK_REF_RE = /\b(?:TASK|PROD|DEV|FEISHU)-\d+\b/gi;
const APPROVAL_REF_RE = /\b(?:AP|APPROVAL)-\d+\b/gi;
const URL_RE = /https?:\/\/[^\s)]+/gi;

const eventWriteQueue = new Map<string, Promise<void>>();

type CaptureHostConfig = {
  datasetCapture?: FeishuDatasetCaptureConfig;
};

function resolveDatasetCaptureConfig(cfg: CaptureHostConfig | undefined): FeishuDatasetCaptureConfig | null {
  const capture = cfg?.datasetCapture;
  if (!capture?.enabled) {
    return null;
  }
  const rootDir = capture.rootDir?.trim();
  const captureId = capture.captureId?.trim();
  const workspaceId = capture.workspaceId?.trim();
  if (!rootDir || !captureId || !workspaceId) {
    return null;
  }
  return {
    ...capture,
    rootDir,
    captureId,
    workspaceId,
  };
}

function uniqueStrings(values: Array<string | undefined | null>): string[] {
  return [...new Set(values.map((value) => String(value ?? "").trim()).filter(Boolean))].sort();
}

function matchRefs(text: string, pattern: RegExp): string[] {
  return uniqueStrings(text.match(pattern) ?? []);
}

function extractDocRefs(text: string): Array<{ id: string; url: string }> {
  return uniqueStrings(text.match(URL_RE) ?? [])
    .filter((url) => url.includes("feishu.cn") || url.includes("larksuite.com"))
    .map((url) => ({ id: url, url }));
}

function deriveTaskRefs(
  text: string,
  senderOpenId: string,
): Array<{ id: string; status?: string; owner_open_id?: string; blocked_by?: string }> {
  const taskIds = matchRefs(text, TASK_REF_RE);
  const approvalIds = matchRefs(text, APPROVAL_REF_RE);
  const lower = text.toLowerCase();
  return taskIds.map((id) => {
    const item: { id: string; status?: string; owner_open_id?: string; blocked_by?: string } = { id };
    if (/\b(done|completed|finished)\b/i.test(text) || /已完成|完成了/.test(text)) {
      item.status = "done";
    } else if (/\b(started|starting|in progress)\b/i.test(text) || /开始|进行中/.test(text)) {
      item.status = "in_progress";
    } else if (/\b(blocked|waiting)\b/i.test(text) || /阻塞|卡住|卡在|依赖/.test(text)) {
      item.status = "blocked";
    }
    if (/\b(owner|assignee|assigned)\b/i.test(lower) || /负责人|owner|指派/.test(text)) {
      item.owner_open_id = senderOpenId;
    }
    if (approvalIds.length > 0 && (/\b(blocked|waiting)\b/i.test(lower) || /阻塞|卡住|卡在|依赖/.test(text))) {
      item.blocked_by = approvalIds[0];
    }
    return item;
  });
}

function deriveApprovalRefs(
  text: string,
  senderOpenId: string,
): Array<{ id: string; status?: string; approved_by?: string }> {
  const approvalIds = matchRefs(text, APPROVAL_REF_RE);
  const lower = text.toLowerCase();
  return approvalIds.map((id) => {
    const item: { id: string; status?: string; approved_by?: string } = { id };
    if (/\b(approved|granted)\b/i.test(lower) || /通过|批准/.test(text)) {
      item.status = "approved";
      item.approved_by = senderOpenId;
    } else if (/\b(rejected|denied)\b/i.test(lower) || /拒绝|驳回/.test(text)) {
      item.status = "rejected";
    } else if (/\b(pending|waiting)\b/i.test(lower) || /待审批|审批中/.test(text)) {
      item.status = "pending";
    }
    return item;
  });
}

function deriveRelations(params: {
  taskRefs: Array<{ id: string; blocked_by?: string }>;
  approvalRefs: Array<{ id: string; approved_by?: string }>;
}): Array<{ type: string; source: string; target: string }> {
  const relations: Array<{ type: string; source: string; target: string }> = [];
  for (const task of params.taskRefs) {
    if (task.blocked_by) {
      relations.push({
        type: "blocked_by",
        source: `task:${task.id}`,
        target: task.blocked_by.startsWith("AP-") ? `approval:${task.blocked_by}` : `task:${task.blocked_by}`,
      });
    }
  }
  for (const approval of params.approvalRefs) {
    if (approval.approved_by) {
      relations.push({
        type: "approved_by",
        source: `approval:${approval.id}`,
        target: `employee:${approval.approved_by}`,
      });
    }
  }
  return relations;
}

async function enqueueWrite(filePath: string, row: Record<string, unknown>): Promise<void> {
  const previous = eventWriteQueue.get(filePath) ?? Promise.resolve();
  const next = previous.then(async () => {
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.appendFile(filePath, `${JSON.stringify(row)}\n`, "utf8");
  });
  eventWriteQueue.set(filePath, next.catch(() => {}));
  await next;
}

async function writeCaptureMetadata(params: {
  config: FeishuDatasetCaptureConfig;
  accountId: string;
  direction: "inbound" | "outbound";
}): Promise<void> {
  const metadataPath = path.join(
    params.config.rootDir!,
    "captures",
    params.config.captureId!,
    "capture-metadata.json",
  );
  const payload = {
    capture_id: params.config.captureId,
    workspace_id: params.config.workspaceId,
    account_id: params.accountId,
    updated_at: new Date().toISOString(),
    directions: { inbound: params.direction === "inbound", outbound: params.direction === "outbound" },
  };
  await fs.mkdir(path.dirname(metadataPath), { recursive: true });
  try {
    const existing = JSON.parse(await fs.readFile(metadataPath, "utf8")) as Record<string, unknown>;
    const directions = {
      inbound:
        Boolean((existing.directions as Record<string, unknown> | undefined)?.inbound) ||
        payload.directions.inbound,
      outbound:
        Boolean((existing.directions as Record<string, unknown> | undefined)?.outbound) ||
        payload.directions.outbound,
    };
    await fs.writeFile(
      metadataPath,
      JSON.stringify({ ...existing, ...payload, directions }, null, 2),
      "utf8",
    );
  } catch {
    await fs.writeFile(metadataPath, JSON.stringify(payload, null, 2), "utf8");
  }
}

async function recordDatasetEvent(params: {
  config: FeishuDatasetCaptureConfig;
  accountId: string;
  direction: "inbound" | "outbound";
  row: Record<string, unknown>;
}): Promise<void> {
  const filePath = path.join(
    params.config.rootDir!,
    "captures",
    params.config.captureId!,
    "office_events.jsonl",
  );
  await writeCaptureMetadata({
    config: params.config,
    accountId: params.accountId,
    direction: params.direction,
  });
  await enqueueWrite(filePath, params.row);
}

export async function recordFeishuDatasetInboundEvent(params: {
  cfg: CaptureHostConfig | undefined;
  accountId: string;
  event: FeishuMessageEvent;
  ctx: FeishuMessageContext;
  senderName?: string;
}): Promise<void> {
  const config = resolveDatasetCaptureConfig(params.cfg);
  if (!config || config.collectInbound === false) {
    return;
  }

  const contentText = params.ctx.content?.trim() || "";
  const senderOpenId = params.ctx.senderOpenId?.trim() || "";
  const taskRefs = deriveTaskRefs(contentText, senderOpenId);
  const approvalRefs = deriveApprovalRefs(contentText, senderOpenId);
  const row = {
    event_id: `feishu:inbound:${params.event.message.message_id}`,
    snapshot_id: config.captureId,
    workspace_id: config.workspaceId,
    chat_id: params.ctx.chatId,
    thread_id: params.ctx.threadId ?? "",
    message_id: params.ctx.messageId,
    reply_to_message_id: params.ctx.parentId ?? "",
    event_time: params.event.message.create_time ?? new Date().toISOString(),
    sender_open_id: senderOpenId,
    sender_name: params.senderName ?? params.ctx.senderName ?? "",
    message_type: params.ctx.contentType,
    content_text: contentText,
    mentions: uniqueStrings(
      (params.event.message.mentions ?? []).map((mention) => mention.id.open_id ?? mention.id.user_id ?? ""),
    ),
    attachments: [],
    doc_refs: extractDocRefs(contentText),
    task_refs: taskRefs,
    approval_refs: approvalRefs,
    card_payload: params.event.message.message_type === "interactive" ? params.event.message.content : null,
    raw_event_ref: {
      source: "feishu",
      direction: "inbound",
      account_id: params.accountId,
      tenant_key: params.event.sender.tenant_key ?? "",
      message_id: params.event.message.message_id,
      root_id: params.event.message.root_id ?? "",
      parent_id: params.event.message.parent_id ?? "",
    },
    direction: "inbound",
    chat_type: params.ctx.chatType,
    entity_refs: [
      ...taskRefs.map((item) => ({ id: `task:${item.id}` })),
      ...approvalRefs.map((item) => ({ id: `approval:${item.id}` })),
    ],
    relations: deriveRelations({ taskRefs, approvalRefs }),
  };

  await recordDatasetEvent({
    config,
    accountId: params.accountId,
    direction: "inbound",
    row,
  });
}

export async function recordFeishuDatasetOutboundEvent(params: {
  cfg: CaptureHostConfig | undefined;
  accountId: string;
  to: string;
  chatId: string;
  messageId: string;
  replyToMessageId?: string;
  replyInThread?: boolean;
  text: string;
  messageType: string;
  mentions?: MentionTarget[];
  cardPayload?: Record<string, unknown>;
}): Promise<void> {
  const config = resolveDatasetCaptureConfig(params.cfg);
  if (!config || config.collectOutbound === false) {
    return;
  }

  const contentText = params.text.trim();
  const senderOpenId = `bot:${params.accountId}`;
  const taskRefs = deriveTaskRefs(contentText, senderOpenId);
  const approvalRefs = deriveApprovalRefs(contentText, senderOpenId);
  const row = {
    event_id: `feishu:outbound:${params.messageId}`,
    snapshot_id: config.captureId,
    workspace_id: config.workspaceId,
    chat_id: params.chatId,
    thread_id: params.replyInThread ? params.replyToMessageId ?? "" : "",
    message_id: params.messageId,
    reply_to_message_id: params.replyToMessageId ?? "",
    event_time: new Date().toISOString(),
    sender_open_id: senderOpenId,
    sender_name: params.accountId,
    message_type: params.messageType,
    content_text: contentText,
    mentions: uniqueStrings((params.mentions ?? []).map((mention) => mention.openId)),
    attachments: [],
    doc_refs: extractDocRefs(contentText),
    task_refs: taskRefs,
    approval_refs: approvalRefs,
    card_payload: params.cardPayload ?? null,
    raw_event_ref: {
      source: "feishu",
      direction: "outbound",
      account_id: params.accountId,
      to: params.to,
      message_id: params.messageId,
    },
    direction: "outbound",
    chat_type: "",
    entity_refs: [
      ...taskRefs.map((item) => ({ id: `task:${item.id}` })),
      ...approvalRefs.map((item) => ({ id: `approval:${item.id}` })),
    ],
    relations: deriveRelations({ taskRefs, approvalRefs }),
  };

  await recordDatasetEvent({
    config,
    accountId: params.accountId,
    direction: "outbound",
    row,
  });
}
