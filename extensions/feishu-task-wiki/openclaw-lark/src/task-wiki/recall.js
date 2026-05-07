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
    extractionMode: "immediate",
    taskIndexState: readJsonFile(taskPaths.indexState, null),
    taskWikiState: readJsonFile(taskPaths.taskWikiState, null),
    sessions,
  };
}

async function prepareSessionForCompaction(params) {
  if (!params.sessionDir) {
    throw new Error("prepareSessionForCompaction requires sessionDir");
  }
  return {
    sessionDir: params.sessionDir,
    extractionMode: "immediate",
    readyForCompaction: true,
  };
}

module.exports = {
  prepareSessionForCompaction,
  recallTaskWiki,
};
