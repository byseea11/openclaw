"use strict";

const fs = require("node:fs");
const path = require("node:path");

const { maybeIngestTaskSourceSession, drainPendingGraphUpdates, runVerificationJobs } = require(
  "../extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js",
);
const { updateTaskWikiFromVerifiedEvents } = require(
  "../extensions/feishu-task-wiki/openclaw-lark/src/task-wiki/projector.js",
);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readJsonl(filePath) {
  const raw = fs.readFileSync(filePath, "utf8").trim();
  if (!raw) {
    return [];
  }
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function writeJsonl(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const text = rows.map((row) => `${JSON.stringify(row)}\n`).join("");
  fs.writeFileSync(filePath, text, "utf8");
}

function normalizeSourceScope(row) {
  const sourceRef = String(row.source_ref || "").trim();
  if (sourceRef.startsWith("chat:") || sourceRef.startsWith("thread:") || sourceRef.startsWith("doc:")) {
    return sourceRef;
  }
  if (row.source_type === "thread") {
    return `thread:${sourceRef || row.session_id}`;
  }
  if (row.source_type === "chat") {
    return `chat:${sourceRef || row.chat_ref}`;
  }
  return `${row.source_type}:${sourceRef || row.session_id}`;
}

async function main() {
  const caseDir = process.argv[2];
  if (!caseDir) {
    throw new Error("usage: node runtime_replay_v3.cjs <case_dir>");
  }
  const caseSpec = readJson(path.join(caseDir, "case_spec.json"));
  const ingressRows = readJsonl(path.join(caseDir, "data", "openclaw_message_ingress.jsonl"));
  const collectedRows = readJsonl(path.join(caseDir, "data", "collected_messages.jsonl"));
  const runtimeStateDir = path.join(caseDir, ".runtime_state");
  fs.rmSync(runtimeStateDir, { recursive: true, force: true });
  fs.mkdirSync(runtimeStateDir, { recursive: true });
  process.env.OPENCLAW_STATE_DIR = runtimeStateDir;
  process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER = "1";

  const collectedByMessageId = new Map(collectedRows.map((row) => [String(row.message_id), row]));
  const taskBindingBase = {
    task: {
      taskId: `task:${caseSpec.task_id}`,
      taskKey: caseSpec.task_id,
    },
    reason: "benchmark_replay",
    taskQueueKey: `benchmark:${caseSpec.case_id}`,
    taskSessionKey: `benchmark:${caseSpec.case_id}`,
  };

  const sessionDirs = new Set();
  for (const ingress of ingressRows) {
    const collected = collectedByMessageId.get(String(ingress.message_id)) || {};
    const sourceScope = normalizeSourceScope(collected);
    const ingestResult = await maybeIngestTaskSourceSession({
      accountId: "default",
      taskBinding: {
        ...taskBindingBase,
        sourceScope,
      },
      sourceType: collected.source_type || "chat",
      sourceId: collected.source_ref || ingress.source_session_ref,
      chatId: collected.chat_ref || null,
      threadId: collected.source_type === "thread" ? collected.session_id || collected.source_ref : null,
      rootId: collected.source_type === "thread" ? collected.message_id : null,
      messageId: collected.message_id || ingress.message_id,
      senderId:
        (collected.actual_sender && collected.actual_sender.open_id)
        || (collected.simulated_speaker && collected.simulated_speaker.open_id)
        || collected.normalized_actor_id
        || ingress.normalized_actor_id,
      senderName:
        (collected.simulated_speaker && collected.simulated_speaker.name)
        || collected.speaker_ref
        || ingress.normalized_actor_id,
      content: collected.content_text || ingress.content_text,
      createTime: `2026-05-06T00:${String(collected.sequence_no || 0).padStart(2, "0")}:00.000Z`,
    });
    if (!ingestResult.skipped && ingestResult.sessionDir) {
      sessionDirs.add(String(ingestResult.sessionDir));
    }
  }

  const candidateEvents = [];
  const sessionEvents = [];
  const sessionStates = [];
  let taskIndexState = {};
  let taskWikiState = {};

  for (const sessionDir of sessionDirs) {
    await drainPendingGraphUpdates({ sessionDir, reason: "replay_runtime" });
    await runVerificationJobs({ sessionDir });
    await drainPendingGraphUpdates({ sessionDir, reason: "projector" });
    const projectorResult = await updateTaskWikiFromVerifiedEvents({ sessionDir });
    sessionStates.push(projectorResult.sessionState);
    taskIndexState = projectorResult.indexState;
    taskWikiState = projectorResult.taskWikiState;
    const candidatePath = path.join(sessionDir, "candidate_events.jsonl");
    const verifiedPath = path.join(sessionDir, "session_events.jsonl");
    if (fs.existsSync(candidatePath)) {
      candidateEvents.push(...readJsonl(candidatePath));
    }
    if (fs.existsSync(verifiedPath)) {
      sessionEvents.push(...readJsonl(verifiedPath));
    }
  }

  writeJsonl(path.join(caseDir, "predictions", "candidate_events.jsonl"), candidateEvents);
  writeJsonl(path.join(caseDir, "predictions", "session_events.jsonl"), sessionEvents);
  writeJson(path.join(caseDir, "predictions", "session_wiki_state.json"), {
    case_id: caseSpec.case_id,
    sessions: sessionStates,
  });
  writeJson(path.join(caseDir, "predictions", "task_index_state.json"), taskIndexState);
  writeJson(path.join(caseDir, "predictions", "task_wiki_state.json"), taskWikiState);
  writeJson(path.join(caseDir, "predictions", "runtime_summary.json"), {
    case_id: caseSpec.case_id,
    session_count: sessionStates.length,
    candidate_event_count: candidateEvents.length,
    session_event_count: sessionEvents.length,
  });
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
