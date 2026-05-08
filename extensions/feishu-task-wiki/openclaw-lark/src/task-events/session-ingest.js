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

const RUNNING_VERIFIER_JOBS = new Set();
const HOT_INGEST_WINDOW = 20;
const NO_EVENT_WINDOW = 10;
const INGEST_STATUS = {
  PENDING_EXTRACTION: "pending_extraction",
  PENDING_VERIFICATION: "pending_verification",
  VERIFIED: "verified",
  NEEDS_REVIEW: "needs_review",
  REJECTED: "rejected",
  PROCESSED_NO_EVENT: "processed_no_event",
};

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
  };
}

function buildEvidenceSpan(params) {
  return {
    evidence_span_id: `span_${crypto.createHash("sha1").update(params.ingestId).digest("hex").slice(0, 16)}`,
    task_id: params.taskId,
    source_session_id: params.sourceSessionId,
    ingest_id: params.ingestId,
    ingest_version: params.ingestVersion,
    source_scope: params.sourceScope,
    trigger_entries: params.triggerEntries,
    support_entries: params.supportEntries,
    core_entries: params.coreEntries,
    context_entries: params.contextEntries,
  };
}

function refreshSessionFiles(params) {
  const files = resolveFilePaths(params.sessionDir);
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
    candidate_event_id: params.event.event_id,
    status: "queued",
    created_at: now,
    updated_at: now,
    attempts: 0,
  };
  appendJsonlRecord(files.verificationJobs, job);
  return job;
}

function scheduleVerificationRun(params) {
  if (process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER === "1") {
    return;
  }
  const sessionKey = params.sessionDir;
  if (RUNNING_VERIFIER_JOBS.has(sessionKey)) {
    return;
  }
  RUNNING_VERIFIER_JOBS.add(sessionKey);
  const timer = setTimeout(async () => {
    try {
      await runVerificationJobs(params);
    } finally {
      RUNNING_VERIFIER_JOBS.delete(sessionKey);
    }
  }, 0);
  if (typeof timer.unref === "function") {
    timer.unref();
  }
}

async function runVerificationJobs(params) {
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
    const span = evidenceSpans.find((entry) => entry?.ingest_id === job.ingest_id);
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
      const ingestRecord = ingestRecords.find((entry) => entry?.ingest_id === job.ingest_id);
      if (ingestRecord) {
        const relatedCandidates = candidateRecords.filter((entry) => entry?.ingest_id === job.ingest_id);
        ingestRecord.status = computeIngestStatusFromCandidates(relatedCandidates);
        ingestRecord.updated_at = new Date().toISOString();
      }
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

async function extractCandidateEventsForIngest(params) {
  const candidates = await extractCandidateEventsWithLLM({
    task: params.taskBinding.task,
    sourceSessionId: params.sourceSessionId,
    ingestVersion: params.ingestVersion,
    coreEntries: params.triggerEntries,
    contextEntries: params.contextEntries,
    supportEntries: params.supportEntries,
    sourceType: params.sourceType,
    sourceId: params.sourceId,
    chatId: params.chatId,
    threadId: params.threadId,
    rootId: params.rootId,
    sourceLocator: params.sourceLocator,
  });
  const validated = candidates.map((candidate) => ({
    ...validateCandidateEvent(candidate, params.triggerEntries),
    ingest_id: params.ingestId,
    task_id: params.taskBinding.task.taskId,
    source_scope: params.taskBinding.sourceScope,
    processing_status: INGEST_STATUS.PENDING_VERIFICATION,
  }));
  for (const candidate of validated) {
    upsertJsonlRecord(params.files.candidateEvents, candidate, "event_id");
  }
  return validated;
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
  const validatedCandidates = await extractCandidateEventsForIngest({
    ...params,
    ...appended,
    files: appended.files,
  });
  appendTaskActivityLog(
    appended.taskId,
    "extract",
    `${validatedCandidates.length} candidate_events for ${appended.sourceSessionId}#${appended.ingestVersion}`,
  );

  let verificationJobsQueued = 0;
  const candidateStatuses = [];
  for (const candidate of validatedCandidates) {
    const processingStatus = computeCandidateProcessingStatus(candidate);
    if (candidate.programmatic_validation?.verdict !== "ready_for_verification") {
      candidateStatuses.push(processingStatus);
      upsertJsonlRecord(appended.files.candidateEvents, { ...candidate, processing_status: processingStatus }, "event_id");
      continue;
    }
    const job = enqueueVerificationJob(appended.files, {
      taskId: params.taskBinding.task.taskId,
      sourceSessionId: appended.sourceSessionId,
      ingestId: appended.ingestId,
      ingestVersion: appended.ingestVersion,
      event: candidate,
    });
    verificationJobsQueued += 1;
    candidateStatuses.push(INGEST_STATUS.PENDING_VERIFICATION);
    upsertJsonlRecord(
      appended.files.candidateEvents,
      { ...candidate, processing_status: INGEST_STATUS.PENDING_VERIFICATION, verification_job_id: job.job_id },
      "event_id",
    );
  }

  const ingestRecords = readJsonl(appended.files.pendingIngests);
  const ingestRecord = ingestRecords.find((entry) => entry?.ingest_id === appended.ingestId);
  if (ingestRecord) {
    ingestRecord.status = computeIngestStatusFromCandidates(
      candidateStatuses.map((status) => ({ processing_status: status })),
    );
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

  if (verificationJobsQueued > 0) {
    scheduleVerificationRun({
      sessionDir: appended.sessionDir,
    });
  }

  return {
    skipped: false,
    taskId: appended.taskId,
    sourceSessionId: appended.sourceSessionId,
    ingestId: appended.ingestId,
    ingestVersion: appended.ingestVersion,
    sessionDir: appended.sessionDir,
    candidateEventCount: validatedCandidates.length,
    verificationJobsQueued,
    coreEntryCount: appended.coreEntries.length,
    contextEntryCount: appended.contextEntries.length,
  };
}

module.exports = {
  appendToSourceSession,
  buildEvidenceSpanForIngest: buildEvidenceSpan,
  enqueueVerificationJob,
  maybeIngestTaskSourceSession,
  resolveSourceSessionId,
  runVerificationJobs,
};
