"use strict";

const fs = require("node:fs");
const path = require("node:path");
const YAML = require("yaml");
const {
  readJsonl,
  writeJsonl,
  ensureDir,
  getSessionWikiPaths,
  getTaskRootPaths,
  findSessionDirs,
  updateForgettingState,
  appendTaskLog,
} = require("./shared.js");

function appendLedgerRecord(filePath, record) {
  const records = readJsonl(filePath);
  records.push(record);
  writeJsonl(filePath, records);
}

function findSessionDirBySourceSessionId(taskRootDir, sourceSessionId) {
  for (const sessionDir of findSessionDirs(taskRootDir)) {
    let metadata = null;
    try {
      metadata = YAML.parse(fs.readFileSync(getSessionWikiPaths(sessionDir).metadata, "utf8"));
    } catch {
      metadata = null;
    }
    if (metadata?.source_session_id === sourceSessionId) {
      return sessionDir;
    }
  }
  return null;
}

function findSessionDirsContainingEventIds(taskRootDir, eventIds) {
  const targetIds = new Set(eventIds.map((value) => String(value)));
  const sessionDirs = [];
  for (const sessionDir of findSessionDirs(taskRootDir)) {
    const events = readJsonl(getSessionWikiPaths(sessionDir).sessionEvents);
    if (events.some((event) => targetIds.has(String(event?.event_id)))) {
      sessionDirs.push(sessionDir);
    }
  }
  return sessionDirs;
}

async function reprojectAffectedSessions(taskRootDir, sessionDirs) {
  const { projectSessionWiki, projectTaskIndex, projectTaskWiki } = require("./projector.js");
  const touched = [];
  for (const sessionDir of sessionDirs) {
    const projected = await projectSessionWiki({ sessionDir });
    await projectTaskIndex({
      taskRootDir,
      sessionState: projected.sessionState,
    });
    await projectTaskWiki({
      taskRootDir,
      sessionState: projected.sessionState,
    });
    touched.push(projected.sessionState.relative_page_path);
  }
  const { runTaskWikiLint } = require("./lint.js");
  await runTaskWikiLint({ taskRootDir, appendLog: true });
  return touched;
}

async function revokeSourceSession(params) {
  const taskPaths = getTaskRootPaths(params.taskRootDir);
  ensureDir(taskPaths.forgettingDir);
  appendLedgerRecord(taskPaths.sourceRevocations, {
    source_session_id: params.sourceSessionId,
    reason: params.reason ?? "manual_revoke",
    revoked_at: new Date().toISOString(),
  });
  updateForgettingState(params.taskRootDir);
  const sessionDir = findSessionDirBySourceSessionId(params.taskRootDir, params.sourceSessionId);
  if (!sessionDir) {
    appendTaskLog(params.taskRootDir, "forget", `missing session ${params.sourceSessionId}`);
    return {
      sourceSessionId: params.sourceSessionId,
      updatedPages: [],
    };
  }
  const updatedPages = await reprojectAffectedSessions(params.taskRootDir, [sessionDir]);
  appendTaskLog(params.taskRootDir, "forget", `revoked session ${params.sourceSessionId}`);
  return {
    sourceSessionId: params.sourceSessionId,
    updatedPages,
  };
}

async function invalidateSessionEvent(params) {
  const taskPaths = getTaskRootPaths(params.taskRootDir);
  ensureDir(taskPaths.forgettingDir);
  appendLedgerRecord(taskPaths.eventInvalidations, {
    event_id: params.eventId,
    reason: params.reason ?? "manual_invalidation",
    invalidated_at: new Date().toISOString(),
  });
  updateForgettingState(params.taskRootDir);
  const sessionDirs = findSessionDirsContainingEventIds(params.taskRootDir, [params.eventId]);
  const updatedPages = await reprojectAffectedSessions(params.taskRootDir, sessionDirs);
  appendTaskLog(params.taskRootDir, "invalidate", params.eventId);
  return {
    eventId: params.eventId,
    updatedPages,
  };
}

async function supersedeSessionEvents(params) {
  const taskPaths = getTaskRootPaths(params.taskRootDir);
  ensureDir(taskPaths.forgettingDir);
  appendLedgerRecord(taskPaths.eventSupersessions, {
    superseding_event_id: params.supersedingEventId,
    superseded_event_ids: params.supersededEventIds,
    reason: params.reason ?? "manual_supersession",
    superseded_at: new Date().toISOString(),
  });
  updateForgettingState(params.taskRootDir);
  const sessionDirs = findSessionDirsContainingEventIds(
    params.taskRootDir,
    [params.supersedingEventId, ...params.supersededEventIds],
  );
  const updatedPages = await reprojectAffectedSessions(params.taskRootDir, sessionDirs);
  appendTaskLog(
    params.taskRootDir,
    "supersede",
    `${params.supersedingEventId} -> ${params.supersededEventIds.join(",")}`,
  );
  return {
    supersedingEventId: params.supersedingEventId,
    supersededEventIds: params.supersededEventIds,
    updatedPages,
  };
}

module.exports = {
  revokeSourceSession,
  invalidateSessionEvent,
  supersedeSessionEvents,
};
