"use strict";

const {
  findSessionDirs,
  getSessionWikiPaths,
  getTaskRootFromSessionDir,
  getTaskRootPaths,
  readJsonFile,
  readJsonl,
} = require("./shared.js");

async function recallTaskWiki(params) {
  const taskRootDir = params.taskRootDir ?? (params.sessionDir ? getTaskRootFromSessionDir(params.sessionDir) : null);
  if (!taskRootDir && !params.sessionDir) {
    throw new Error("recallTaskWiki requires taskRootDir or sessionDir");
  }
  // Lazy load to avoid making task-wiki state reads depend on layer-2 runtime until
  // recall is actually requested.
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree on purpose
  const { ensureTaskWikiFresh } = require("../task-events/session-ingest.js");
  const freshness = await ensureTaskWikiFresh({
    taskRootDir: params.sessionDir ? undefined : taskRootDir,
    sessionDir: params.sessionDir ?? undefined,
    reason: "recall",
    projectAfterDrain: true,
  });

  const resolvedTaskRoot = taskRootDir ?? getTaskRootFromSessionDir(params.sessionDir);
  const taskPaths = getTaskRootPaths(resolvedTaskRoot);
  const targetSessionDirs = params.sessionDir ? [params.sessionDir] : findSessionDirs(resolvedTaskRoot);
  const sessions = targetSessionDirs.map((sessionDir) => {
    const sessionPaths = getSessionWikiPaths(sessionDir);
    return {
      sessionDir,
      sessionWikiState: readJsonFile(sessionPaths.sessionWikiState, null),
      sessionEvents: params.includeSessionEvents === false ? undefined : readJsonl(sessionPaths.sessionEvents),
    };
  });

  return {
    taskRootDir: resolvedTaskRoot,
    freshness,
    taskIndexState: readJsonFile(taskPaths.indexState, null),
    taskWikiState: readJsonFile(taskPaths.taskWikiState, null),
    sessions,
  };
}

async function prepareSessionForCompaction(params) {
  if (!params.sessionDir) {
    throw new Error("prepareSessionForCompaction requires sessionDir");
  }
  return await require("../task-events/session-ingest.js").ensureTaskWikiFresh({
    sessionDir: params.sessionDir,
    reason: "pre_compaction",
    projectAfterDrain: true,
  });
}

module.exports = {
  prepareSessionForCompaction,
  recallTaskWiki,
};
