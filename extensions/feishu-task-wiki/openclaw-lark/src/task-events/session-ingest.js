"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const YAML = require("yaml");
const {
  extractCandidateEventsWithLLM,
  validateCandidateEvent,
  verifyCandidateEvent,
} = require("./extractor.js");

const HOT_INGEST_WINDOW = 20;
const NO_EVENT_WINDOW = 10;
const DEFAULT_DRAIN_INGEST_LIMIT = 4;
const DEFAULT_DRAIN_CHAR_LIMIT = 1600;
const INGEST_STATUS = {
  PENDING_EXTRACTION: "pending_extraction",
  QUEUED_FOR_DRAIN: "queued_for_drain",
  PENDING_VERIFICATION: "pending_verification",
  VERIFIED: "verified",
  NEEDS_REVIEW: "needs_review",
  REJECTED: "rejected",
  PROCESSED_NO_EVENT: "processed_no_event",
};

const SIGNAL_PATTERNS = [
  { reason: "status_change", weight: 3, pattern: /(阻塞|blocked|卡住|完成|done|已完成|未完成|尚未|状态|上线|发布)/iu },
  { reason: "owner_change", weight: 2, pattern: /(负责人|owner|我来|我负责|跟进|推进|assign|assigned)/iu },
  { reason: "decision", weight: 2, pattern: /(决定|结论|统一口径|先按|暂定|确认|锁定|采用)/iu },
  { reason: "time_change", weight: 2, pattern: /(\d{1,2}\s*月\s*\d{1,2}\s*日|今天|明天|后天|本周|下周|deadline|截止)/iu },
  { reason: "dependency", weight: 2, pattern: /(依赖|dependency|前置|等待|迁移窗口|blocker|风险)/iu },
];
const DRAIN_REASONS = new Set([
  "replay_runtime",
  "verification",
  "projector",
  "recall",
  "pre_compaction",
  "threshold_dirty_count",
  "threshold_span_size",
  "strong_signal",
  "idle",
  "manual",
]);

function appendTaskActivityLog(taskId, kind, detail) {
  try {
    // Lazy load to keep Layer 2 from taking a hard dependency on Stage 3
    // internals until logging is actually needed.
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree on purpose
    const { appendTaskLog } = require("../task-wiki/shared.js");
    appendTaskLog(resolveTaskRootDir(taskId), kind, detail);
  } catch {
    // Do not block Layer 2 ingest/verification on task log failures.
  }
}

function resolveStateDir() {
  const fromEnv = process.env.OPENCLAW_STATE_DIR;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.trim();
  }
  return path.join(os.homedir(), ".openclaw");
}

function normalizeText(input) {
  return String(input ?? "").replace(/\r\n/g, "\n").replace(/\s+/g, " ").trim();
}

function slugify(input) {
  const normalized = String(input ?? "")
    .replace(/^task:/, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
  const digest = crypto.createHash("sha1").update(String(input ?? "")).digest("hex").slice(0, 8);
  return `${normalized || "item"}-${digest}`;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function ensureJsonlFile(filePath) {
  ensureDir(path.dirname(filePath));
  if (!fs.existsSync(filePath)) {
    fs.writeFileSync(filePath, "", "utf8");
  }
}

function readJsonFile(filePath, fallbackValue) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallbackValue;
  }
}

function readJsonl(filePath) {
  try {
    const raw = fs.readFileSync(filePath, "utf8").trim();
    if (!raw) {
      return [];
    }
    return raw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}

function writeJsonl(filePath, entries) {
  fs.writeFileSync(
    filePath,
    entries.map((entry) => `${JSON.stringify(entry)}\n`).join(""),
    "utf8",
  );
}

function upsertJsonlRecord(filePath, record, idField) {
  const records = readJsonl(filePath);
  const index = records.findIndex((entry) => entry?.[idField] === record?.[idField]);
  if (index >= 0) {
    records[index] = record;
  } else {
    records.push(record);
  }
  writeJsonl(filePath, records);
  return records;
}

function appendJsonlRecord(filePath, record) {
  const records = readJsonl(filePath);
  records.push(record);
  writeJsonl(filePath, records);
  return records;
}

function uniqueStrings(values) {
  const result = [];
  const seen = new Set();
  for (const value of values) {
    const normalized = String(value ?? "").trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function scoreSignal(text) {
  const normalized = normalizeText(text);
  let signalStrength = 0;
  const dirtyReasons = [];
  for (const rule of SIGNAL_PATTERNS) {
    if (rule.pattern.test(normalized)) {
      signalStrength += rule.weight;
      dirtyReasons.push(rule.reason);
    }
  }
  return {
    signalStrength,
    dirtyReasons: uniqueStrings(dirtyReasons),
    needsLlmExtraction: signalStrength > 0,
  };
}

function createDrainBatchId(parts) {
  return `drain_${crypto.createHash("sha1").update(parts.join("|")).digest("hex").slice(0, 16)}`;
}

function normalizeDrainReason(reason) {
  const normalized = String(reason ?? "").trim();
  if (DRAIN_REASONS.has(normalized)) {
    return normalized;
  }
  return "manual";
}

function resolveTaskRootDir(taskId) {
  return path.join(resolveStateDir(), "feishu-task-wiki", "tasks", slugify(taskId));
}

function resolveSourceSessionId(taskId, sourceScope) {
  return `${taskId}::${sourceScope}`;
}

function resolveSourceSessionDir(taskId, sourceSessionId) {
  return path.join(resolveTaskRootDir(taskId), "sessions", slugify(sourceSessionId));
}

function resolveFilePaths(sessionDir) {
  return {
    manifest: path.join(sessionDir, "session-stream.json"),
    sessionMarkdown: path.join(sessionDir, "session.md"),
    metadata: path.join(sessionDir, "metadata.yaml"),
    pendingIngests: path.join(sessionDir, "pending_ingests.jsonl"),
    evidenceSpans: path.join(sessionDir, "evidence_spans.jsonl"),
    candidateEvents: path.join(sessionDir, "candidate_events.jsonl"),
    sessionEvents: path.join(sessionDir, "session_events.jsonl"),
    verificationJobs: path.join(sessionDir, "verification_jobs.jsonl"),
  };
}

function nextIngestVersion(sessionDir) {
  const manifest = readJsonFile(path.join(sessionDir, "session-stream.json"), null);
  if (manifest && Number.isInteger(manifest.latest_ingest_version)) {
    return manifest.latest_ingest_version + 1;
  }
  return 1;
}

function readSessionManifest(sessionDir) {
  return readJsonFile(path.join(sessionDir, "session-stream.json"), null);
}

function writeSessionManifest(sessionDir, manifest) {
  fs.writeFileSync(path.join(sessionDir, "session-stream.json"), JSON.stringify(manifest, null, 2), "utf8");
}

function buildMessageEntry(params) {
  return {
    entry_id: params.entryId ?? `entry_${Date.now()}`,
    text: normalizeText(params.content),
    sender_id: params.senderId ?? null,
    sender_name: params.senderName ?? null,
    create_time: params.createTime ?? new Date().toISOString(),
    chat_id: params.chatId ?? null,
    thread_id: params.threadId ?? null,
    root_id: params.rootId ?? null,
    source_type: params.sourceType,
    source_id: params.sourceId,
    role: params.role ?? "message",
  };
}

function buildContextEntryFromRecord(record) {
  return {
    entry_id: record.entry_id,
    text: record.text,
    sender_id: record.sender_id ?? null,
    sender_name: record.sender_name ?? null,
    create_time: record.create_time ?? null,
    chat_id: record.chat_id ?? null,
    thread_id: record.thread_id ?? null,
    root_id: record.root_id ?? null,
    source_type: record.source_type ?? null,
    source_id: record.source_id ?? null,
    role: record.role ?? "message",
  };
}

function collectPriorEntries(sessionDir, currentIngestId, limit = 6) {
  const files = resolveFilePaths(sessionDir);
  const records = readJsonl(files.pendingIngests)
    .filter((record) => record && record.ingest_id !== currentIngestId)
    .sort((a, b) => Number(a.ingest_version ?? 0) - Number(b.ingest_version ?? 0));
  const entries = [];
  for (const record of records) {
    for (const item of record.new_entries ?? []) {
      entries.push(buildContextEntryFromRecord(item));
    }
  }
  return entries.slice(-limit);
}

async function maybeFetchThreadRootEntry(params) {
  if (params.sourceType !== "thread") {
    return null;
  }
  if (normalizeText(params.rootContent)) {
    return buildMessageEntry({
      entryId: params.rootId ?? "thread_root",
      content: params.rootContent,
      senderId: params.rootSenderId ?? null,
      senderName: params.rootSenderName ?? null,
      createTime: params.rootCreateTime ?? params.createTime,
      chatId: params.chatId,
      threadId: params.threadId,
      rootId: params.rootId,
      sourceType: params.sourceType,
      sourceId: params.sourceId,
      role: "root",
    });
  }
  if (!params.cfg || !params.accountId || !params.rootId || params.messageId === params.rootId) {
    return null;
  }
  try {
    // Lazy load to keep unit tests and non-thread paths from importing the full runtime chain.
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree on purpose
    const { getMessageFeishu } = require("../messaging/shared/message-lookup.js");
    const message = await getMessageFeishu({
      cfg: params.cfg,
      accountId: params.accountId,
      messageId: params.rootId,
    });
    if (!message?.content) {
      return null;
    }
    return buildMessageEntry({
      entryId: params.rootId,
      content: message.content,
      senderId: message.senderId ?? null,
      senderName: message.senderName ?? null,
      createTime:
        typeof message.createTime === "number"
          ? new Date(message.createTime).toISOString()
          : params.rootCreateTime ?? params.createTime,
      chatId: params.chatId,
      threadId: params.threadId,
      rootId: params.rootId,
      sourceType: params.sourceType,
      sourceId: params.sourceId,
      role: "root",
    });
  } catch {
    return null;
  }
}

function buildCommentRootEntry(params) {
  if (params.sourceType !== "comment" || !normalizeText(params.rootContent) || params.messageId === params.rootId) {
    return null;
  }
  return buildMessageEntry({
    entryId: params.rootId ?? "comment_root",
    content: params.rootContent,
    senderId: params.rootSenderId ?? null,
    senderName: params.rootSenderName ?? null,
    createTime: params.rootCreateTime ?? params.createTime,
    chatId: params.chatId,
    rootId: params.rootId,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    role: "root",
  });
}

async function buildCoreAndContext(params, sessionDir, ingestId) {
  const currentEntry = buildMessageEntry({
    entryId: params.messageId ?? `entry_${Date.now()}`,
    content: params.content,
    senderId: params.senderId,
    senderName: params.senderName,
    createTime: params.createTime,
    chatId: params.chatId,
    threadId: params.threadId,
    rootId: params.rootId,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    role: "message",
  });

  const priorEntries = collectPriorEntries(sessionDir, ingestId, params.sourceType === "chat" ? 6 : 4);
  const contextEntries = [];
  const triggerEntries = [];
  const supportEntries = [];

  if (params.sourceType === "thread") {
    const rootEntry = await maybeFetchThreadRootEntry(params);
    if (rootEntry) {
      supportEntries.push(rootEntry);
    }
    triggerEntries.push(currentEntry);
    for (const entry of priorEntries) {
      if (entry.entry_id !== rootEntry?.entry_id && entry.entry_id !== currentEntry.entry_id) {
        contextEntries.push(entry);
      }
    }
  } else if (params.sourceType === "comment") {
    const rootEntry = buildCommentRootEntry(params);
    if (rootEntry) {
      supportEntries.push(rootEntry);
    }
    triggerEntries.push(currentEntry);
    for (const entry of priorEntries) {
      if (entry.entry_id !== rootEntry?.entry_id && entry.entry_id !== currentEntry.entry_id) {
        contextEntries.push(entry);
      }
    }
    if (normalizeText(params.replyChainContext)) {
      contextEntries.push(
        buildMessageEntry({
          entryId: `${params.messageId ?? "comment"}_reply_chain`,
          content: params.replyChainContext,
          createTime: params.createTime,
          chatId: params.chatId,
          rootId: params.rootId,
          sourceType: params.sourceType,
          sourceId: params.sourceId,
          role: "reply_chain_context",
        }),
      );
    }
  } else {
    triggerEntries.push(currentEntry);
    contextEntries.push(...priorEntries.filter((entry) => entry.entry_id !== currentEntry.entry_id).slice(-3));
  }

  return {
    currentEntry,
    triggerEntries: dedupeEntries(triggerEntries),
    supportEntries: dedupeEntries(supportEntries),
    coreEntries: dedupeEntries([...supportEntries, ...triggerEntries]),
    contextEntries: dedupeEntries(contextEntries),
  };
}

function dedupeEntries(entries) {
  const seen = new Set();
  const result = [];
  for (const entry of entries) {
    const key = String(entry?.entry_id ?? "");
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(entry);
  }
  return result;
}

function collectVisibleSessionEntries(params) {
  const entriesById = new Map();
  const addEntry = (entry) => {
    if (!entry?.entry_id) {
      return;
    }
    entriesById.set(entry.entry_id, entry);
  };
  for (const record of params.ingestRecords) {
    for (const entry of record.new_entries ?? []) {
      addEntry(entry);
    }
  }
  for (const span of params.evidenceSpans) {
    for (const entry of span.trigger_entries ?? []) {
      addEntry(entry);
    }
    for (const entry of span.support_entries ?? []) {
      addEntry(entry);
    }
    for (const entry of span.context_entries ?? []) {
      addEntry(entry);
    }
  }

  const visibleIds = new Set();
  const sortedIngests = params.ingestRecords
    .slice()
    .sort((a, b) => Number(a.ingest_version ?? 0) - Number(b.ingest_version ?? 0));
  const hotIngests = sortedIngests.slice(-HOT_INGEST_WINDOW);
  const recentNoEventIngests = sortedIngests
    .filter((record) => record.status === INGEST_STATUS.PROCESSED_NO_EVENT)
    .slice(-NO_EVENT_WINDOW);

  for (const span of params.evidenceSpans) {
    for (const entry of span.support_entries ?? []) {
      if (entry.role === "root") {
        visibleIds.add(entry.entry_id);
      }
    }
  }
  for (const record of hotIngests) {
    for (const entry of record.new_entries ?? []) {
      visibleIds.add(entry.entry_id);
    }
  }
  for (const record of sortedIngests) {
    if (
      record.status === INGEST_STATUS.PENDING_EXTRACTION
      || record.status === INGEST_STATUS.QUEUED_FOR_DRAIN
      || record.status === INGEST_STATUS.PENDING_VERIFICATION
      || record.status === INGEST_STATUS.VERIFIED
      || record.status === INGEST_STATUS.NEEDS_REVIEW
      || record.status === INGEST_STATUS.REJECTED
    ) {
      for (const entry of record.new_entries ?? []) {
        visibleIds.add(entry.entry_id);
      }
    }
  }
  for (const record of recentNoEventIngests) {
    for (const entry of record.new_entries ?? []) {
      visibleIds.add(entry.entry_id);
    }
  }
  for (const event of [...params.candidateEvents, ...params.sessionEvents]) {
    if (event?.core_entry_id) {
      visibleIds.add(event.core_entry_id);
    }
    for (const quote of event?.context_quotes ?? []) {
      if (quote?.entry_id) {
        visibleIds.add(quote.entry_id);
      }
    }
  }

  const visibleEntries = [];
  for (const record of sortedIngests) {
    for (const entry of record.new_entries ?? []) {
      if (visibleIds.has(entry.entry_id)) {
        visibleEntries.push(entriesById.get(entry.entry_id) ?? entry);
      }
    }
  }
  for (const span of params.evidenceSpans) {
    for (const entry of span.support_entries ?? []) {
      if (visibleIds.has(entry.entry_id)) {
        visibleEntries.push(entriesById.get(entry.entry_id) ?? entry);
      }
    }
  }

  return {
    visibleEntries: dedupeEntries(visibleEntries),
    rawIngestCount: sortedIngests.length,
    visibleIngestCount: uniqueStrings(
      sortedIngests
        .filter((record) => (record.new_entries ?? []).some((entry) => visibleIds.has(entry.entry_id)))
        .map((record) => record.ingest_id),
    ).length,
    retainedEntryCount: visibleIds.size,
  };
}

function renderSessionMarkdown(params) {
  const visible = collectVisibleSessionEntries(params);
  const body = visible.visibleEntries.length === 0
    ? "无"
    : visible.visibleEntries
        .map((entry) => {
          const sender = entry.sender_name ?? entry.sender_id ?? "unknown";
          const time = entry.create_time ?? "unknown";
          return `<a id="${entry.entry_id}"></a>\n### ${entry.entry_id}\n- sender: ${sender}\n- time: ${time}\n- role: ${entry.role ?? "message"}\n\n${entry.text}`;
        })
        .join("\n\n");
  return [
    "# Source Session",
    "",
    `- task_id: ${params.task.taskId}`,
    `- task_key: ${params.task.taskKey}`,
    `- source_session_id: ${params.sourceSessionId}`,
    `- latest_ingest_version: ${params.latestIngestVersion}`,
    `- source_scope: ${params.sourceScope}`,
    `- source_type: ${params.sourceType}`,
    `- raw_ingest_count: ${visible.rawIngestCount}`,
    `- visible_ingest_count: ${visible.visibleIngestCount}`,
    `- retained_entry_count: ${visible.retainedEntryCount}`,
    "",
    "## Working View Entries",
    "",
    body,
  ].join("\n");
}

function buildSessionMetadata(params, manifest, ingestRecords, viewStats) {
  const first = ingestRecords[0];
  const last = ingestRecords[ingestRecords.length - 1];
  const participants = new Set();
  for (const record of ingestRecords) {
    for (const entry of record.new_entries ?? []) {
      const participant = entry.sender_name ?? entry.sender_id;
      if (participant) {
        participants.add(participant);
      }
    }
  }
  return {
    task_id: params.task.taskId,
    task_key: params.task.taskKey,
    source_session_id: params.sourceSessionId,
    source_scope: params.sourceScope,
    source_type: params.sourceType,
    source_id: params.sourceId,
    chat_id: params.chatId ?? null,
    thread_id: params.threadId ?? null,
    root_id: params.rootId ?? null,
    time_range: {
      start: first?.created_at ?? null,
      end: last?.updated_at ?? null,
    },
    participants: [...participants],
    source_locator: params.sourceLocator ?? null,
    binding_mode: params.bindingMode ?? null,
    created_at: manifest?.created_at ?? new Date().toISOString(),
    updated_at: new Date().toISOString(),
    latest_ingest_version: params.latestIngestVersion,
    raw_ingest_count: viewStats.rawIngestCount,
    visible_ingest_count: viewStats.visibleIngestCount,
    compacted_at: new Date().toISOString(),
    retained_entry_count: viewStats.retainedEntryCount,
    last_drain_reason: params.lastDrainReason ?? manifest?.last_drain_reason ?? null,
    last_drain_batch_id: params.lastDrainBatchId ?? manifest?.last_drain_batch_id ?? null,
    last_drain_at: params.lastDrainAt ?? manifest?.last_drain_at ?? null,
    last_drain_source_ingest_ids: params.lastDrainSourceIngestIds ?? manifest?.last_drain_source_ingest_ids ?? [],
  };
}

function buildIngestRecord(params) {
  const now = new Date().toISOString();
  return {
    ingest_id: `${params.sourceSessionId}::${params.ingestVersion}`,
    task_id: params.task.taskId,
    source_session_id: params.sourceSessionId,
    ingest_version: params.ingestVersion,
    source_scope: params.sourceScope,
    source_type: params.sourceType,
    source_id: params.sourceId,
    chat_id: params.chatId ?? null,
    thread_id: params.threadId ?? null,
    root_id: params.rootId ?? null,
    status: INGEST_STATUS.PENDING_EXTRACTION,
    created_at: now,
    updated_at: now,
    new_entries: params.newEntries,
    trigger_entry_ids: params.triggerEntries.map((entry) => entry.entry_id),
    support_entry_ids: params.supportEntries.map((entry) => entry.entry_id),
    core_entry_ids: params.coreEntries.map((entry) => entry.entry_id),
    context_entry_ids: params.contextEntries.map((entry) => entry.entry_id),
    source_locator: params.sourceLocator ?? null,
    signal_strength: Number(params.signalStrength ?? 0),
    dirty_reason: uniqueStrings(params.dirtyReasons ?? []),
    needs_llm_extraction: Boolean(params.needsLlmExtraction),
    drain_batch_id: null,
    drain_reason: null,
    covered_by_batch_at: null,
  };
}

function buildEvidenceSpan(params) {
  return {
    evidence_span_id: `span_${crypto.createHash("sha1").update(params.ingestId).digest("hex").slice(0, 16)}`,
    span_kind: params.spanKind ?? "ingest",
    task_id: params.taskId,
    source_session_id: params.sourceSessionId,
    ingest_id: params.ingestId,
    ingest_version: params.ingestVersion,
    source_scope: params.sourceScope,
    drain_batch_id: params.drainBatchId ?? null,
    drain_reason: params.drainReason ?? null,
    source_ingest_ids: params.sourceIngestIds ?? [params.ingestId],
    trigger_entries: params.triggerEntries,
    support_entries: params.supportEntries,
    core_entries: params.coreEntries,
    context_entries: params.contextEntries,
  };
}

function refreshSessionFiles(params) {
  const files = resolveFilePaths(params.sessionDir);
  ensureJsonlFile(files.candidateEvents);
  ensureJsonlFile(files.sessionEvents);
  ensureJsonlFile(files.verificationJobs);
  const manifest = readSessionManifest(params.sessionDir);
  const ingestRecords = readJsonl(files.pendingIngests);
  const evidenceSpans = readJsonl(files.evidenceSpans);
  const candidateEvents = readJsonl(files.candidateEvents);
  const sessionEvents = readJsonl(files.sessionEvents);
  const viewStats = collectVisibleSessionEntries({
    ingestRecords,
    evidenceSpans,
    candidateEvents,
    sessionEvents,
  });
  fs.writeFileSync(
    files.metadata,
    YAML.stringify(buildSessionMetadata({
      task: params.task,
      sourceSessionId: params.sourceSessionId,
      sourceScope: params.sourceScope,
      sourceType: params.sourceType,
      sourceId: params.sourceId,
      chatId: params.chatId,
      threadId: params.threadId,
      rootId: params.rootId,
      sourceLocator: params.sourceLocator,
      bindingMode: params.bindingMode,
      latestIngestVersion: manifest?.latest_ingest_version ?? 0,
      lastDrainReason: params.lastDrainReason ?? null,
      lastDrainBatchId: params.lastDrainBatchId ?? null,
      lastDrainAt: params.lastDrainAt ?? null,
      lastDrainSourceIngestIds: params.lastDrainSourceIngestIds ?? [],
    }, manifest, ingestRecords, viewStats)),
    "utf8",
  );
  fs.writeFileSync(
    files.sessionMarkdown,
    renderSessionMarkdown({
      task: params.task,
      sourceSessionId: params.sourceSessionId,
      latestIngestVersion: manifest?.latest_ingest_version ?? 0,
      sourceScope: params.sourceScope,
      sourceType: params.sourceType,
      ingestRecords,
      evidenceSpans,
      candidateEvents,
      sessionEvents,
    }),
    "utf8",
  );
}

function computeCandidateProcessingStatus(candidate) {
  if (candidate.programmatic_validation?.verdict === "rejected") {
    return INGEST_STATUS.REJECTED;
  }
  if (candidate.programmatic_validation?.verdict === "needs_review") {
    return INGEST_STATUS.NEEDS_REVIEW;
  }
  return INGEST_STATUS.PENDING_VERIFICATION;
}

function computeIngestStatusFromCandidates(candidates) {
  if (!Array.isArray(candidates) || candidates.length === 0) {
    return INGEST_STATUS.PROCESSED_NO_EVENT;
  }
  const statuses = candidates.map((candidate) => candidate.processing_status ?? candidate.verification?.verdict);
  if (statuses.includes(INGEST_STATUS.PENDING_VERIFICATION) || statuses.includes("queued_verification")) {
    return INGEST_STATUS.PENDING_VERIFICATION;
  }
  if (statuses.includes(INGEST_STATUS.VERIFIED) || statuses.includes("verified")) {
    return INGEST_STATUS.VERIFIED;
  }
  if (statuses.includes(INGEST_STATUS.NEEDS_REVIEW) || statuses.includes("needs_review")) {
    return INGEST_STATUS.NEEDS_REVIEW;
  }
  return INGEST_STATUS.REJECTED;
}

function collectRelatedCandidatesForIngests(candidates, ingestIds) {
  const ingestIdSet = new Set(ingestIds);
  return candidates.filter((candidate) => {
    const sourceIngestIds = Array.isArray(candidate?.source_ingest_ids) ? candidate.source_ingest_ids : [];
    return sourceIngestIds.some((ingestId) => ingestIdSet.has(ingestId));
  });
}

function updateStatusesForIngestIds(ingestRecords, candidateRecords, ingestIds, statusOverride = null) {
  const relatedCandidates = collectRelatedCandidatesForIngests(candidateRecords, ingestIds);
  const nextStatus = statusOverride ?? computeIngestStatusFromCandidates(relatedCandidates);
  const now = new Date().toISOString();
  for (const ingestRecord of ingestRecords) {
    if (!ingestIds.includes(ingestRecord?.ingest_id)) {
      continue;
    }
    ingestRecord.status = nextStatus;
    ingestRecord.updated_at = now;
  }
}

function resolveBatchEvidenceSpan(evidenceSpans, job) {
  if (job.drain_batch_id) {
    return evidenceSpans.find((entry) => entry?.drain_batch_id === job.drain_batch_id && entry?.span_kind === "drain_batch");
  }
  return evidenceSpans.find((entry) => entry?.ingest_id === job.ingest_id);
}

function buildBatchEnvelope(params) {
  const coreEntries = [];
  const supportEntries = [];
  const contextEntries = [];
  for (const span of params.spans) {
    coreEntries.push(...(span.trigger_entries ?? span.core_entries ?? []));
    supportEntries.push(...(span.support_entries ?? []));
    contextEntries.push(...(span.context_entries ?? []));
  }
  const dedupedCore = dedupeEntries(coreEntries);
  const coreIds = new Set(dedupedCore.map((entry) => entry.entry_id));
  const dedupedSupport = dedupeEntries(
    supportEntries.filter((entry) => entry?.entry_id && !coreIds.has(entry.entry_id)),
  );
  const supportIds = new Set(dedupedSupport.map((entry) => entry.entry_id));
  const dedupedContext = dedupeEntries(
    contextEntries.filter((entry) => entry?.entry_id && !coreIds.has(entry.entry_id) && !supportIds.has(entry.entry_id)),
  );
  const latestIngestVersion = Math.max(...params.ingestRecords.map((record) => Number(record.ingest_version ?? 0)));
  const sourceIngestIds = params.ingestRecords.map((record) => record.ingest_id);
  const drainBatchId = createDrainBatchId([
    params.sourceSessionId,
    sourceIngestIds.join("|"),
  ]);
  return {
    drainBatchId,
    sourceIngestIds,
    latestIngestVersion,
    coreEntries: dedupedCore,
    supportEntries: dedupedSupport,
    contextEntries: dedupedContext,
    signalStrength: params.ingestRecords.reduce((sum, record) => sum + Number(record.signal_strength ?? 0), 0),
    dirtyReasons: uniqueStrings(params.ingestRecords.flatMap((record) => record.dirty_reason ?? [])),
  };
}

function splitPendingIngestsIntoBatches(ingestRecords) {
  const batches = [];
  let current = [];
  let currentChars = 0;
  for (const record of ingestRecords) {
    const nextChars = (record.new_entries ?? []).reduce((sum, entry) => sum + String(entry?.text ?? "").length, 0);
    const wouldOverflow = current.length >= DEFAULT_DRAIN_INGEST_LIMIT || currentChars + nextChars > DEFAULT_DRAIN_CHAR_LIMIT;
    if (current.length > 0 && wouldOverflow) {
      batches.push(current);
      current = [];
      currentChars = 0;
    }
    current.push(record);
    currentChars += nextChars;
  }
  if (current.length > 0) {
    batches.push(current);
  }
  return batches;
}

function buildVerifiedEventSignature(event) {
  return [
    event?.task_id ?? event?.task_ref ?? "",
    event?.source_session_id ?? "",
    event?.event_type ?? "",
    event?.core_entry_id ?? "",
    normalizeText(event?.evidence_quote ?? ""),
  ].join("|");
}

function enqueueVerificationJob(files, params) {
  const now = new Date().toISOString();
  const job = {
    job_id: `verify_${crypto.createHash("sha1").update(`${params.sourceSessionId}|${params.ingestVersion}|${params.event.event_id}`).digest("hex").slice(0, 16)}`,
    task_id: params.taskId,
    source_session_id: params.sourceSessionId,
    ingest_id: params.ingestId,
    ingest_version: params.ingestVersion,
    drain_batch_id: params.drainBatchId ?? null,
    drain_reason: params.drainReason ?? null,
    source_ingest_ids: params.sourceIngestIds ?? [params.ingestId],
    candidate_event_id: params.event.event_id,
    status: "queued",
    created_at: now,
    updated_at: now,
    attempts: 0,
  };
  appendJsonlRecord(files.verificationJobs, job);
  return job;
}

async function drainPendingGraphUpdates(params) {
  const drainReason = normalizeDrainReason(params.reason);
  const files = resolveFilePaths(params.sessionDir);
  const ingestRecords = readJsonl(files.pendingIngests);
  const evidenceSpans = readJsonl(files.evidenceSpans);
  const candidateRecords = readJsonl(files.candidateEvents);
  const jobs = readJsonl(files.verificationJobs);
  const metadata = YAML.parse(fs.readFileSync(files.metadata, "utf8"));
  const pending = ingestRecords
    .filter((record) => (
      record?.status === INGEST_STATUS.PENDING_EXTRACTION
      || record?.status === INGEST_STATUS.QUEUED_FOR_DRAIN
    ) && record?.needs_llm_extraction)
    .sort((a, b) => Number(a.ingest_version ?? 0) - Number(b.ingest_version ?? 0));
  if (pending.length === 0) {
    return {
      drainBatches: 0,
      extractedCandidates: 0,
      queuedVerificationJobs: jobs.filter((job) => job.status === "queued").length,
    };
  }

  const batches = splitPendingIngestsIntoBatches(pending);
  let extractedCandidates = 0;
  let queuedVerificationJobs = 0;
  const now = new Date().toISOString();
  let lastDrainBatchId = null;
  let lastDrainSourceIngestIds = [];

  for (const batchIngests of batches) {
    const spanIndex = new Map(
      evidenceSpans
        .filter((span) => span?.span_kind !== "drain_batch")
        .map((span) => [span.ingest_id, span]),
    );
    const batchSpans = batchIngests
      .map((record) => spanIndex.get(record.ingest_id))
      .filter(Boolean);
    if (batchSpans.length === 0) {
      continue;
    }

    const envelope = buildBatchEnvelope({
      sourceSessionId: metadata.source_session_id,
      ingestRecords: batchIngests,
      spans: batchSpans,
    });
    const batchSpan = buildEvidenceSpan({
      taskId: metadata.task_id,
      sourceSessionId: metadata.source_session_id,
      ingestId: batchIngests[batchIngests.length - 1].ingest_id,
      ingestVersion: envelope.latestIngestVersion,
      sourceScope: metadata.source_scope,
      triggerEntries: envelope.coreEntries,
      supportEntries: envelope.supportEntries,
      coreEntries: envelope.coreEntries,
      contextEntries: envelope.contextEntries,
      spanKind: "drain_batch",
      drainBatchId: envelope.drainBatchId,
      drainReason,
      sourceIngestIds: envelope.sourceIngestIds,
    });
    evidenceSpans.push(batchSpan);

    for (const ingestRecord of batchIngests) {
      ingestRecord.status = INGEST_STATUS.QUEUED_FOR_DRAIN;
      ingestRecord.drain_batch_id = envelope.drainBatchId;
      ingestRecord.drain_reason = drainReason;
      ingestRecord.covered_by_batch_at = now;
      ingestRecord.updated_at = now;
    }

    const rawCandidates = await extractCandidateEventsWithLLM({
      task: {
        taskId: metadata.task_id,
        taskKey: metadata.task_key,
      },
      sourceSessionId: metadata.source_session_id,
      ingestVersion: envelope.latestIngestVersion,
      coreEntries: envelope.coreEntries,
      contextEntries: envelope.contextEntries,
      supportEntries: envelope.supportEntries,
      sourceType: metadata.source_type,
      sourceId: metadata.source_id,
      chatId: metadata.chat_id,
      threadId: metadata.thread_id,
      rootId: metadata.root_id,
      sourceLocator: metadata.source_locator ?? null,
    });
    const validatedCandidates = rawCandidates.map((candidate) => ({
      ...validateCandidateEvent(candidate, envelope.coreEntries),
      ingest_id: batchIngests[batchIngests.length - 1].ingest_id,
      task_id: metadata.task_id,
      source_scope: metadata.source_scope,
      drain_batch_id: envelope.drainBatchId,
      source_ingest_ids: envelope.sourceIngestIds,
      processing_status: INGEST_STATUS.PENDING_VERIFICATION,
    }));

    if (validatedCandidates.length === 0) {
      updateStatusesForIngestIds(
        ingestRecords,
        candidateRecords,
        envelope.sourceIngestIds,
        INGEST_STATUS.PROCESSED_NO_EVENT,
      );
      continue;
    }

    extractedCandidates += validatedCandidates.length;
    const candidateStatuses = [];
    for (const candidate of validatedCandidates) {
      const processingStatus = computeCandidateProcessingStatus(candidate);
      candidateStatuses.push(processingStatus);
      if (candidate.programmatic_validation?.verdict !== "ready_for_verification") {
        upsertJsonlRecord(
          files.candidateEvents,
          { ...candidate, processing_status: processingStatus },
          "event_id",
        );
        candidateRecords.push({ ...candidate, processing_status: processingStatus });
        continue;
      }
      const job = enqueueVerificationJob(files, {
        taskId: metadata.task_id,
        sourceSessionId: metadata.source_session_id,
        ingestId: batchIngests[batchIngests.length - 1].ingest_id,
        ingestVersion: envelope.latestIngestVersion,
        drainBatchId: envelope.drainBatchId,
        drainReason,
        sourceIngestIds: envelope.sourceIngestIds,
        event: candidate,
      });
      queuedVerificationJobs += 1;
      upsertJsonlRecord(
        files.candidateEvents,
        {
          ...candidate,
          processing_status: INGEST_STATUS.PENDING_VERIFICATION,
          verification_job_id: job.job_id,
        },
        "event_id",
      );
      candidateRecords.push({
        ...candidate,
        processing_status: INGEST_STATUS.PENDING_VERIFICATION,
        verification_job_id: job.job_id,
      });
    }

    updateStatusesForIngestIds(ingestRecords, candidateRecords, envelope.sourceIngestIds);
    appendTaskActivityLog(
      metadata.task_id,
      "drain_extract",
      `${drainReason}: ${validatedCandidates.length} candidate_events for ${metadata.source_session_id}#${envelope.drainBatchId}`,
    );
    lastDrainBatchId = envelope.drainBatchId;
    lastDrainSourceIngestIds = envelope.sourceIngestIds;
  }

  writeJsonl(files.pendingIngests, ingestRecords);
  writeJsonl(files.evidenceSpans, evidenceSpans);
  refreshSessionFiles({
    sessionDir: params.sessionDir,
    task: {
      taskId: metadata.task_id,
      taskKey: metadata.task_key,
    },
    sourceSessionId: metadata.source_session_id,
    sourceScope: metadata.source_scope,
    sourceType: metadata.source_type,
    sourceId: metadata.source_id,
    chatId: metadata.chat_id,
    threadId: metadata.thread_id,
    rootId: metadata.root_id,
    sourceLocator: metadata.source_locator ?? null,
    bindingMode: metadata.binding_mode ?? null,
    lastDrainReason: drainReason,
    lastDrainBatchId,
    lastDrainAt: now,
    lastDrainSourceIngestIds,
  });

  return {
    drainBatches: batches.length,
    extractedCandidates,
    queuedVerificationJobs,
    reason: drainReason,
  };
}

async function runVerificationJobs(params) {
  await drainPendingGraphUpdates({ sessionDir: params.sessionDir, reason: "verification" });
  const files = resolveFilePaths(params.sessionDir);
  const jobs = readJsonl(files.verificationJobs);
  const candidateRecords = readJsonl(files.candidateEvents);
  const verifiedEvents = readJsonl(files.sessionEvents);
  const ingestRecords = readJsonl(files.pendingIngests);
  const evidenceSpans = readJsonl(files.evidenceSpans);
  let verifiedEventsAdded = false;
  let newlyVerifiedCount = 0;
  let completedCandidateCount = 0;

  let changed = false;
  for (const job of jobs) {
    if (job.status !== "queued") {
      continue;
    }
    const candidateIndex = candidateRecords.findIndex((entry) => entry?.event_id === job.candidate_event_id);
    if (candidateIndex < 0) {
      job.status = "failed";
      job.last_error = "candidate_not_found";
      job.updated_at = new Date().toISOString();
      changed = true;
      continue;
    }
    const span = resolveBatchEvidenceSpan(evidenceSpans, job);
    if (!span) {
      job.status = "failed";
      job.last_error = "evidence_span_not_found";
      job.updated_at = new Date().toISOString();
      changed = true;
      continue;
    }
    job.status = "running";
    job.attempts = Number(job.attempts ?? 0) + 1;
    job.updated_at = new Date().toISOString();
    changed = true;
    try {
      const verified = await verifyCandidateEvent({
        candidateEvent: candidateRecords[candidateIndex],
        coreEntries: span.trigger_entries ?? span.core_entries ?? [],
        contextEntries: span.context_entries ?? [],
        supportEntries: span.support_entries ?? [],
      });
      candidateRecords[candidateIndex] = {
        ...verified,
        drain_batch_id: job.drain_batch_id ?? candidateRecords[candidateIndex]?.drain_batch_id ?? null,
        source_ingest_ids: job.source_ingest_ids ?? candidateRecords[candidateIndex]?.source_ingest_ids ?? [job.ingest_id],
        processing_status: verified.verification?.verdict === "verified"
          ? INGEST_STATUS.VERIFIED
          : verified.verification?.verdict === "rejected"
            ? INGEST_STATUS.REJECTED
            : INGEST_STATUS.NEEDS_REVIEW,
        verification_job_id: job.job_id,
        verified_at: new Date().toISOString(),
      };
      if (verified.verification?.verdict === "verified") {
        const signature = buildVerifiedEventSignature(verified);
        const exists = verifiedEvents.some((entry) => buildVerifiedEventSignature(entry) === signature);
        if (!exists) {
          verifiedEvents.push({
            ...verified,
            verification_job_id: job.job_id,
            verified_at: new Date().toISOString(),
          });
          verifiedEventsAdded = true;
          newlyVerifiedCount += 1;
        }
      }
      completedCandidateCount += 1;
      updateStatusesForIngestIds(
        ingestRecords,
        candidateRecords,
        Array.isArray(job.source_ingest_ids) ? job.source_ingest_ids : [job.ingest_id],
      );
      job.status = "completed";
      job.updated_at = new Date().toISOString();
      job.last_error = null;
    } catch (error) {
      job.status = "failed";
      job.updated_at = new Date().toISOString();
      job.last_error = String(error?.message ?? error);
    }
  }

  if (changed) {
    writeJsonl(files.verificationJobs, jobs);
    writeJsonl(files.candidateEvents, candidateRecords);
    writeJsonl(files.sessionEvents, verifiedEvents);
    writeJsonl(files.pendingIngests, ingestRecords);
    const metadata = YAML.parse(fs.readFileSync(files.metadata, "utf8"));
    refreshSessionFiles({
      sessionDir: params.sessionDir,
      task: {
        taskId: metadata.task_id,
        taskKey: metadata.task_key,
      },
      sourceSessionId: metadata.source_session_id,
      sourceScope: metadata.source_scope,
      sourceType: metadata.source_type,
      sourceId: metadata.source_id,
      chatId: metadata.chat_id,
      threadId: metadata.thread_id,
      rootId: metadata.root_id,
      sourceLocator: metadata.source_locator ?? null,
      bindingMode: metadata.binding_mode ?? null,
    });
    if (verifiedEventsAdded) {
      appendTaskActivityLog(
        metadata.task_id,
        "session_event_write",
        `${newlyVerifiedCount} verified session_events for ${metadata.source_session_id}`,
      );
      try {
        // Lazy load to keep the stage-3 wiki projector off the hot path until
        // a verified event actually lands.
        // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree on purpose
        const { updateTaskWikiFromVerifiedEvents } = require("../task-wiki/projector.js");
        await updateTaskWikiFromVerifiedEvents({
          sessionDir: params.sessionDir,
        });
      } catch {
        // Do not block Layer 2 verification on Layer 3 projection failures.
      }
    }
    if (completedCandidateCount > 0) {
      appendTaskActivityLog(
        metadata.task_id,
        "verify",
        `${completedCandidateCount} candidates processed for ${metadata.source_session_id}`,
      );
    }
  }

  return {
    queuedJobs: jobs.filter((job) => job.status === "queued").length,
    completedJobs: jobs.filter((job) => job.status === "completed").length,
    verifiedEvents: verifiedEvents.length,
  };
}

async function appendToSourceSession(params) {
  const taskId = params.taskBinding.task.taskId;
  const sourceScope = params.taskBinding.sourceScope;
  const sourceSessionId = resolveSourceSessionId(taskId, sourceScope);
  const sessionDir = resolveSourceSessionDir(taskId, sourceSessionId);
  ensureDir(sessionDir);

  const ingestVersion = nextIngestVersion(sessionDir);
  const ingestId = `${sourceSessionId}::${ingestVersion}`;
  const manifest = readSessionManifest(sessionDir);

  const built = await buildCoreAndContext({
    ...params,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
  }, sessionDir, ingestId);
  const files = resolveFilePaths(sessionDir);
  const ingestRecord = buildIngestRecord({
    task: params.taskBinding.task,
    sourceSessionId,
    ingestVersion,
    sourceScope,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    chatId: params.chatId,
    threadId: params.threadId,
    rootId: params.rootId,
    triggerEntries: built.triggerEntries,
    supportEntries: built.supportEntries,
    coreEntries: built.coreEntries,
    contextEntries: built.contextEntries,
    newEntries: built.triggerEntries,
    sourceLocator: params.sourceLocator,
  });
  appendJsonlRecord(files.pendingIngests, ingestRecord);
  const nextManifest = {
    task_id: taskId,
    task_key: params.taskBinding.task.taskKey,
    source_session_id: sourceSessionId,
    source_scope: sourceScope,
    source_type: params.sourceType,
    source_id: params.sourceId,
    latest_ingest_version: ingestVersion,
    created_at: manifest?.created_at ?? new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  writeSessionManifest(sessionDir, nextManifest);

  const evidenceSpan = buildEvidenceSpan({
    taskId,
    sourceSessionId,
    ingestId,
    ingestVersion,
    sourceScope,
    triggerEntries: built.triggerEntries,
    supportEntries: built.supportEntries,
    coreEntries: built.coreEntries,
    contextEntries: built.contextEntries,
  });
  appendJsonlRecord(files.evidenceSpans, evidenceSpan);

  refreshSessionFiles({
    sessionDir,
    task: params.taskBinding.task,
    sourceSessionId,
    sourceScope,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    chatId: params.chatId,
    threadId: params.threadId,
    rootId: params.rootId,
    sourceLocator: params.sourceLocator,
    bindingMode: params.taskBinding.reason,
  });

  return {
    taskId,
    sourceScope,
    sourceSessionId,
    sessionDir,
    ingestId,
    ingestVersion,
    triggerEntries: built.triggerEntries,
    supportEntries: built.supportEntries,
    coreEntries: built.coreEntries,
    contextEntries: built.contextEntries,
    evidenceSpan,
    files,
  };
}

async function maybeIngestTaskSourceSession(params) {
  if (!params.taskBinding?.task?.taskId) {
    return { skipped: true, reason: "unbound_task" };
  }
  const content = normalizeText(params.content);
  if (!content) {
    return { skipped: true, reason: "empty_content" };
  }

  const appended = await appendToSourceSession(params);
  appendTaskActivityLog(
    appended.taskId,
    "ingest",
    `${appended.sourceSessionId}#${appended.ingestVersion}`,
  );
  const signal = scoreSignal(params.content);
  const ingestRecords = readJsonl(appended.files.pendingIngests);
  const ingestRecord = ingestRecords.find((entry) => entry?.ingest_id === appended.ingestId);
  if (ingestRecord) {
    ingestRecord.signal_strength = signal.signalStrength;
    ingestRecord.dirty_reason = signal.dirtyReasons;
    ingestRecord.needs_llm_extraction = signal.needsLlmExtraction;
    ingestRecord.status = signal.needsLlmExtraction
      ? INGEST_STATUS.PENDING_EXTRACTION
      : INGEST_STATUS.PROCESSED_NO_EVENT;
    ingestRecord.updated_at = new Date().toISOString();
    writeJsonl(appended.files.pendingIngests, ingestRecords);
  }

  refreshSessionFiles({
    sessionDir: appended.sessionDir,
    task: params.taskBinding.task,
    sourceSessionId: appended.sourceSessionId,
    sourceScope: appended.sourceScope,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    chatId: params.chatId,
    threadId: params.threadId,
    rootId: params.rootId,
    sourceLocator: params.sourceLocator,
    bindingMode: params.taskBinding.reason,
  });
  appendTaskActivityLog(
    appended.taskId,
    "signal_detect",
    `${signal.needsLlmExtraction ? "dirty" : "no_event"}:${signal.dirtyReasons.join(",") || "none"} for ${appended.sourceSessionId}#${appended.ingestVersion}`,
  );

  return {
    skipped: false,
    taskId: appended.taskId,
    sourceSessionId: appended.sourceSessionId,
    ingestId: appended.ingestId,
    ingestVersion: appended.ingestVersion,
    sessionDir: appended.sessionDir,
    candidateEventCount: 0,
    verificationJobsQueued: 0,
    coreEntryCount: appended.coreEntries.length,
    contextEntryCount: appended.contextEntries.length,
    drainRecommended: signal.needsLlmExtraction,
  };
}

module.exports = {
  appendToSourceSession,
  buildEvidenceSpanForIngest: buildEvidenceSpan,
  drainPendingGraphUpdates,
  enqueueVerificationJob,
  maybeIngestTaskSourceSession,
  resolveSourceSessionId,
  runVerificationJobs,
};
