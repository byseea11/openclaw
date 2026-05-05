"use strict";

const fs = require("node:fs");
const path = require("node:path");

function normalizeText(input) {
  return String(input ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeKey(input) {
  return normalizeText(input).toLowerCase();
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

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), "utf8");
}

function writeJsonl(filePath, values) {
  const body = values.map((value) => `${JSON.stringify(value)}\n`).join("");
  fs.writeFileSync(filePath, body, "utf8");
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function sortByEventTimeDescending(items) {
  return items.slice().sort((left, right) => {
    const leftTime = Date.parse(left?.event_time ?? "") || 0;
    const rightTime = Date.parse(right?.event_time ?? "") || 0;
    return rightTime - leftTime;
  });
}

function getSessionWikiPaths(sessionDir) {
  return {
    sessionEvents: path.join(sessionDir, "session_events.jsonl"),
    sessionMarkdown: path.join(sessionDir, "session.md"),
    metadata: path.join(sessionDir, "metadata.yaml"),
    sessionWikiMarkdown: path.join(sessionDir, "session_wiki.md"),
    sessionWikiState: path.join(sessionDir, "session_wiki_state.json"),
    pendingIngests: path.join(sessionDir, "pending_ingests.jsonl"),
  };
}

function getTaskRootFromSessionDir(sessionDir) {
  return path.dirname(path.dirname(sessionDir));
}

function getTaskRootPaths(taskRootDir) {
  const forgettingDir = path.join(taskRootDir, "forgetting");
  const lintDir = path.join(taskRootDir, "lint");
  return {
    taskYaml: path.join(taskRootDir, "task.yaml"),
    indexMarkdown: path.join(taskRootDir, "index.md"),
    indexState: path.join(taskRootDir, "task_index_state.json"),
    taskWikiMarkdown: path.join(taskRootDir, "task_wiki.md"),
    taskWikiState: path.join(taskRootDir, "task_wiki_state.json"),
    logMarkdown: path.join(taskRootDir, "log.md"),
    forgettingDir,
    sourceRevocations: path.join(forgettingDir, "source_revocations.jsonl"),
    eventInvalidations: path.join(forgettingDir, "event_invalidations.jsonl"),
    eventSupersessions: path.join(forgettingDir, "event_supersessions.jsonl"),
    forgettingState: path.join(forgettingDir, "forgetting_state.json"),
    lintDir,
    lintState: path.join(lintDir, "lint_state.json"),
    openConflicts: path.join(lintDir, "open_conflicts.md"),
    staleClaims: path.join(lintDir, "stale_claims.md"),
    orphanEvents: path.join(lintDir, "orphan_events.md"),
    unresolvedObjections: path.join(lintDir, "unresolved_objections.md"),
    overdueCommitments: path.join(lintDir, "overdue_commitments.md"),
  };
}

function findSessionDirs(taskRootDir) {
  const sessionsDir = path.join(taskRootDir, "sessions");
  try {
    return fs.readdirSync(sessionsDir).map((entry) => path.join(sessionsDir, entry));
  } catch {
    return [];
  }
}

function relativeSessionWikiPath(sessionDir) {
  return `sessions/${path.basename(sessionDir)}/session_wiki.md`;
}

function readLifecycleOverlay(taskRootDir) {
  const paths = getTaskRootPaths(taskRootDir);
  const sourceRevocations = readJsonl(paths.sourceRevocations);
  const eventInvalidations = readJsonl(paths.eventInvalidations);
  const eventSupersessions = readJsonl(paths.eventSupersessions);
  const revokedSourceMap = new Map();
  const invalidatedEventMap = new Map();
  const supersededEventMap = new Map();
  for (const record of sourceRevocations) {
    if (!record?.source_session_id) {
      continue;
    }
    revokedSourceMap.set(String(record.source_session_id), record);
  }
  for (const record of eventInvalidations) {
    if (!record?.event_id) {
      continue;
    }
    invalidatedEventMap.set(String(record.event_id), record);
  }
  for (const record of eventSupersessions) {
    for (const eventId of record?.superseded_event_ids ?? []) {
      supersededEventMap.set(String(eventId), record);
    }
  }
  return {
    sourceRevocations,
    eventInvalidations,
    eventSupersessions,
    revokedSourceMap,
    invalidatedEventMap,
    supersededEventMap,
  };
}

function resolveEventLifecycle(event, overlay) {
  const sourceRevocation = overlay.revokedSourceMap.get(String(event?.source_session_id ?? ""));
  if (sourceRevocation) {
    return {
      lifecycle_status: "invalid",
      lifecycle_reason: "source_revoked",
      revoked_at: sourceRevocation.revoked_at ?? null,
    };
  }
  const invalidation = overlay.invalidatedEventMap.get(String(event?.event_id ?? ""));
  if (invalidation) {
    return {
      lifecycle_status: "invalid",
      lifecycle_reason: "invalidated",
      invalidated_at: invalidation.invalidated_at ?? null,
    };
  }
  const supersession = overlay.supersededEventMap.get(String(event?.event_id ?? ""));
  if (supersession) {
    return {
      lifecycle_status: "historical",
      lifecycle_reason: "superseded",
      superseded_at: supersession.superseded_at ?? null,
      superseding_event_id: supersession.superseding_event_id ?? null,
    };
  }
  return {
    lifecycle_status: "active",
    lifecycle_reason: null,
  };
}

function updateForgettingState(taskRootDir) {
  const paths = getTaskRootPaths(taskRootDir);
  ensureDir(paths.forgettingDir);
  const overlay = readLifecycleOverlay(taskRootDir);
  const state = {
    version: 1,
    source_revocation_count: overlay.sourceRevocations.length,
    event_invalidation_count: overlay.eventInvalidations.length,
    event_supersession_count: overlay.eventSupersessions.length,
    updated_at: new Date().toISOString(),
  };
  writeJson(paths.forgettingState, state);
  return state;
}

function appendTaskLog(taskRootDir, kind, detail) {
  const paths = getTaskRootPaths(taskRootDir);
  const timestamp = new Date().toISOString().slice(0, 10);
  const line = `## [${timestamp}] ${kind} | ${detail}\n`;
  fs.appendFileSync(paths.logMarkdown, line, "utf8");
}

module.exports = {
  normalizeText,
  normalizeKey,
  readJsonFile,
  readJsonl,
  writeJson,
  writeJsonl,
  ensureDir,
  sortByEventTimeDescending,
  getSessionWikiPaths,
  getTaskRootFromSessionDir,
  getTaskRootPaths,
  findSessionDirs,
  relativeSessionWikiPath,
  readLifecycleOverlay,
  resolveEventLifecycle,
  updateForgettingState,
  appendTaskLog,
};
