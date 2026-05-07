#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const defaultDatasetRoot = "amem_docs/ds/feishu_im_dataset_v3";
const baselineMode = "openclaw_real_replay";
const semanticGoldModes = new Set(["auto", "llm", "rule", "off"]);

function parseArgs(argv) {
  const args = {
    datasetRoot: defaultDatasetRoot,
    caseDir: "",
    stateDir: "",
    semanticGold: "auto",
    requireLlm: false,
    json: false,
    quiet: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--case-dir") {
      args.caseDir = argv[++index] ?? "";
    } else if (item === "--dataset-root") {
      args.datasetRoot = argv[++index] ?? "";
    } else if (item === "--state-dir") {
      args.stateDir = argv[++index] ?? "";
    } else if (item === "--semantic-gold") {
      args.semanticGold = argv[++index] ?? "auto";
    } else if (item === "--require-llm") {
      args.requireLlm = true;
    } else if (item === "--json") {
      args.json = true;
    } else if (item === "--quiet") {
      args.quiet = true;
    } else if (item === "-h" || item === "--help" || item === "help") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`未知参数：${item}`);
    }
  }
  if (!semanticGoldModes.has(args.semanticGold)) {
    throw new Error(`--semantic-gold 只能是 ${Array.from(semanticGoldModes).join("|")}`);
  }
  return args;
}

function printHelp() {
  console.log(`用法：
  node feishu_task_wiki_benchmark_builder/runtime/openclaw_baseline_eval.mjs [options]

说明：
  - 这个脚本是 Phase 3 的底层 OpenClaw baseline 调试入口。
  - 日常 Phase 3 请使用：amem_docs/scripts/03-feishu-task-wiki-phase3-eval.sh
  - 本脚本只评估原始 OpenClaw，不调用 Task Wiki 三层实现。
  - 默认使用 openclaw_real_replay：先检查已启动的 OpenClaw Gateway，再按 sender_open_id + source session 写入多个 Gateway agent session，并用 query session 回答 benchmark query。
  - 不再隐式使用近似 baseline；如果真实 OpenClaw replay 入口不可用，脚本直接失败。
  - 测试或专用 harness 可通过 OPENCLAW_BENCHMARK_REPLAY_COMMAND 注入 benchmark-only replay command。
  - 如需指定 CLI，可设置 OPENCLAW_BENCHMARK_OPENCLAW_COMMAND；默认使用 PATH 中的 openclaw。

参数：
  --case-dir <path>
      显式指定 case 目录。若省略，读取 dataset root 的 active_case.json。

  --dataset-root <path>
      dataset root。默认：${defaultDatasetRoot}

  --state-dir <path>
      baseline 调试状态目录。默认：<case_dir>/runtime/openclaw_baseline_state

  --semantic-gold <mode>
      auto | llm | rule | off，默认 auto。

  --require-llm
      若 semantic gold 需要 LLM 但环境缺配置，则失败而不是回退。

  --json
      只输出一行 JSON summary。

  --quiet
      只输出最终 JSON 路径。

输出：
  <case_dir>/runtime/openclaw_baseline/answers.json
  <case_dir>/runtime/openclaw_baseline/evidence_traces.json
  <case_dir>/runtime/openclaw_baseline/replay_metadata.json
  <case_dir>/reports/openclaw_baseline_eval.json

示例：
  node feishu_task_wiki_benchmark_builder/runtime/openclaw_baseline_eval.mjs --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/<case_id>
  node feishu_task_wiki_benchmark_builder/runtime/openclaw_baseline_eval.mjs --case-dir <case_dir> --semantic-gold rule --json

前置条件：
  openclaw gateway status
  openclaw gateway call health
`);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readJsonl(filePath) {
  if (!fs.existsSync(filePath)) {
    return [];
  }
  return fs
    .readFileSync(filePath, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function writeJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function truncateText(value, limit = 12000) {
  const text = String(value || "");
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit)}\n...[truncated ${text.length - limit} chars]`;
}

function resolveInputPath(value) {
  return path.isAbsolute(value) ? value : path.resolve(repoRoot, value);
}

function relativePath(filePath) {
  return path.relative(repoRoot, filePath);
}

function resolveCaseDir(args) {
  if (args.caseDir) {
    return resolveInputPath(args.caseDir);
  }
  const activeCasePath = path.join(resolveInputPath(args.datasetRoot), "active_case.json");
  const activeCase = readJson(activeCasePath);
  return resolveInputPath(activeCase.case_dir);
}

function requiredGoldFiles(caseDir) {
  return [
    path.join(caseDir, "gold", "annotation_gold.jsonl"),
    path.join(caseDir, "gold", "task_wiki_semantic_gold.json"),
    path.join(caseDir, "gold", "query_benchmark.json"),
  ];
}

function missingGoldFiles(caseDir) {
  return requiredGoldFiles(caseDir).filter((filePath) => !fs.existsSync(filePath));
}

function runPhase2Stage({ caseDir, stage, semanticGold, requireLlm }) {
  const command = [
    "-m",
    "feishu_task_wiki_benchmark_builder.cli",
    "phase2-step",
    "--stage",
    stage,
    "--case-dir",
    caseDir,
  ];
  if (stage === "semantic-gold") {
    command.push("--semantic-gold", semanticGold);
    if (requireLlm) {
      command.push("--require-llm");
    }
  }
  const result = spawnSync("python3", command, {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    const detail = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
    throw new Error(`Phase2 ${stage} 生成失败：${detail}`);
  }
  return result.stdout.trim();
}

function ensurePhase2Gold({ caseDir, semanticGold, requireLlm }) {
  const before = missingGoldFiles(caseDir).map(relativePath);
  const generatedStages = [];
  if (before.length === 0) {
    return { generated: false, missing_before: [], generated_stages: [] };
  }

  const stages = [
    ["annotation-gold", path.join(caseDir, "gold", "annotation_gold.jsonl")],
    ["semantic-gold", path.join(caseDir, "gold", "task_wiki_semantic_gold.json")],
    ["query-benchmark", path.join(caseDir, "gold", "query_benchmark.json")],
  ];
  for (const [stage, filePath] of stages) {
    if (!fs.existsSync(filePath)) {
      runPhase2Stage({ caseDir, stage, semanticGold, requireLlm });
      generatedStages.push(stage);
    }
  }

  const after = missingGoldFiles(caseDir).map(relativePath);
  if (after.length > 0) {
    throw new Error(`Phase2 gold 仍缺失：${after.join(", ")}`);
  }
  return { generated: true, missing_before: before, generated_stages: generatedStages };
}

function extractMessageText(row) {
  const content = row?.message?.content;
  if (typeof content === "string") {
    try {
      const parsed = JSON.parse(content);
      if (typeof parsed.text === "string") {
        return parsed.text;
      }
    } catch {
      return content;
    }
  }
  if (typeof row?.message_text === "string") {
    return row.message_text;
  }
  return "";
}

function collectedText(row) {
  return String(row?.observed_text_without_prefix || row?.message_text || row?.content_text || "");
}

function normalizeText(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim();
}

function createObservedRows({ ingressRows, collectedRows }) {
  const collectedById = new Map();
  for (const row of collectedRows) {
    if (row?.message_id) {
      collectedById.set(row.message_id, row);
    }
  }
  return ingressRows
    .map((row, index) => {
      const message = row?.message || {};
      const messageId = String(message.message_id || row?.message_id || "");
      const collected = collectedById.get(messageId) || {};
      const text = normalizeText(collectedText(collected) || extractMessageText(row));
      const createdAt = Number(message.create_time || row?.create_time || index);
      const sender = row?.sender && typeof row.sender === "object" ? row.sender : {};
      const senderId =
        sender?.sender_id && typeof sender.sender_id === "object" ? sender.sender_id : {};
      const simulated =
        collected?.simulated_speaker && typeof collected.simulated_speaker === "object"
          ? collected.simulated_speaker
          : {};
      const senderOpenId = String(
        senderId.open_id || simulated.open_id || collected.normalized_actor_id || "ou_sim_unknown",
      );
      const senderName = String(
        sender.sender_name || simulated.name || collected?.prefix_speaker_hint?.name || "",
      );
      return {
        index,
        message_id: messageId,
        create_time: Number.isFinite(createdAt) ? createdAt : index,
        chat_id: String(message.chat_id || ""),
        thread_id: String(message.thread_id || ""),
        root_id: String(message.root_id || ""),
        session_id: String(collected.session_id || row?.benchmark_trace?.source_ref || ""),
        source_type: String(collected.source_type || row?.benchmark_trace?.source_type || ""),
        sender: senderName,
        sender_open_id: senderOpenId,
        text,
        annotation_target: Boolean(
          collected.annotation_target || row?.benchmark_trace?.annotation_target,
        ),
        event_bearing: Boolean(collected.event_bearing || row?.benchmark_trace?.event_bearing),
        official_file_ref: String(collected.official_file_ref || ""),
        private_info_ref: String(collected.private_info_ref || ""),
        task_relevance_boundary: String(collected.task_relevance_boundary || ""),
        turn_kind: String(collected.turn_kind || ""),
      };
    })
    .toSorted((left, right) => left.create_time - right.create_time || left.index - right.index);
}

function buildQueryPrompt({ caseContext, query, allowedMessageIds }) {
  return [
    "你正在以原始 OpenClaw 助手身份回答 benchmark query。",
    "只能依据当前 workspace memory 中的 observed transcript 回答。",
    "不要使用 Task Wiki 的三层 event/wiki/gold artifact。",
    "请输出一个 JSON object，不要输出 Markdown。",
    "",
    "JSON schema:",
    '{"answer":"...","supporting_message_ids":["om_..."],"confidence":0.0}',
    "",
    "证据要求：",
    "- supporting_message_ids 只能来自下面的 allowed message ids。",
    "- 如果你不能从原始记忆中找到证据，supporting_message_ids 返回空数组。",
    "- 不要编造 message_id。",
    "",
    `Case: ${caseContext.case_id}`,
    `Task: ${caseContext.task_id}`,
    `Allowed message ids: ${allowedMessageIds.join(", ")}`,
    "",
    `Query: ${query.query}`,
    query.expected_good_behavior
      ? `Expected behavior hint for scoring, not evidence: ${query.expected_good_behavior}`
      : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildTranscriptIngestPrompt({ caseContext, observedRows }) {
  const transcript = observedRows
    .map((row) => {
      return [
        `message_id=${row.message_id}`,
        `sender_open_id=${row.sender_open_id || "unknown"}`,
        `sender=${row.sender || "unknown"}`,
        `session=${row.session_id || "unknown"}`,
        `chat_id=${row.chat_id || "unknown"}`,
        `thread_id=${row.thread_id || ""}`,
        `time=${row.create_time}`,
        `text=${row.text}`,
      ].join(" | ");
    })
    .join("\n");
  return [
    "你是原始 OpenClaw 记忆系统。下面是一批 benchmark observed transcript。",
    "请把它们作为当前 OpenClaw session 的记忆上下文保存，后续 query 只能依据这些消息回答。",
    "必须保留 message_id、sender_open_id、source session 与原文的对应关系；不要使用 Task Wiki 的 event/wiki/gold artifact。",
    "",
    `Case: ${caseContext.case_id}`,
    `Task: ${caseContext.task_id}`,
    `Family: ${caseContext.family_id}`,
    "",
    "Observed transcript:",
    transcript,
    "",
    '回复一个简短 JSON：{"status":"ingested"}',
  ].join("\n");
}

function buildQueryContextPrompt({ caseContext, observedRows, sessionKeysByMessageId }) {
  const transcript = observedRows
    .map((row) => {
      return [
        `message_id=${row.message_id}`,
        `openclaw_session_key=${sessionKeysByMessageId.get(row.message_id) || ""}`,
        `sender_open_id=${row.sender_open_id || "unknown"}`,
        `sender=${row.sender || "unknown"}`,
        `source_session=${row.session_id || "unknown"}`,
        `chat_id=${row.chat_id || "unknown"}`,
        `thread_id=${row.thread_id || ""}`,
        `time=${row.create_time}`,
        `text=${row.text}`,
      ].join(" | ");
    })
    .join("\n");
  return [
    "你是原始 OpenClaw 的 benchmark query session。",
    "下面是已经按 sender_open_id + source session 写入多个 OpenClaw session 的 transcript index。",
    "回答后续 query 时必须保留多用户身份边界：不要把不同 sender_open_id 的信息当成同一个用户的私有记忆。",
    "如果引用证据，只能引用 message_id；不要编造 message_id。",
    "",
    `Case: ${caseContext.case_id}`,
    `Task: ${caseContext.task_id}`,
    `Family: ${caseContext.family_id}`,
    "",
    "OpenClaw session trace index:",
    transcript,
    "",
    '回复一个简短 JSON：{"status":"indexed"}',
  ].join("\n");
}

function sessionToken(value) {
  const normalized = String(value || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "")
    .slice(0, 80);
  return normalized || "unknown";
}

function sourceScopeForRow(row) {
  return row.thread_id || row.chat_id || row.session_id || "unknown-source";
}

function openClawSenderSessionKey({ caseContext, row }) {
  const caseToken = sessionToken(caseContext.case_id);
  const sourceToken = sessionToken(sourceScopeForRow(row));
  const senderToken = sessionToken(row.sender_open_id || "unknown-sender");
  return `agent:main:feishu-benchmark:${caseToken}:source:${sourceToken}:sender:${senderToken}`;
}

function openClawQuerySessionKey(caseContext) {
  return `agent:main:feishu-benchmark:${sessionToken(caseContext.case_id)}:query:evaluator`;
}

function groupRowsByOpenClawSession({ caseContext, observedRows }) {
  const groups = new Map();
  const sessionKeysByMessageId = new Map();
  for (const row of observedRows) {
    const sessionKey = openClawSenderSessionKey({ caseContext, row });
    sessionKeysByMessageId.set(row.message_id, sessionKey);
    const group = groups.get(sessionKey) || [];
    group.push(row);
    groups.set(sessionKey, group);
  }
  return { groups, sessionKeysByMessageId };
}

function parseJsonFromText(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    const first = trimmed.indexOf("{");
    const last = trimmed.lastIndexOf("}");
    if (first >= 0 && last > first) {
      try {
        return JSON.parse(trimmed.slice(first, last + 1));
      } catch {
        return null;
      }
    }
  }
  return null;
}

function commandParts() {
  return (process.env.OPENCLAW_BENCHMARK_OPENCLAW_COMMAND || "openclaw").trim().split(/\s+/);
}

function runOpenClawGatewayCall({ method, params, timeout = 600_000, expectFinal = false }) {
  const args = [
    ...commandParts(),
    "gateway",
    "call",
    method,
    "--params",
    JSON.stringify(params),
    "--timeout",
    String(timeout),
    "--json",
  ];
  if (expectFinal) {
    args.push("--expect-final");
  }
  const [bin, ...binArgs] = args;
  const result = spawnSync(bin, binArgs, {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf8",
    timeout,
  });
  return {
    args,
    command: args.join(" "),
    returncode: result.status,
    stdout: result.stdout,
    stderr: result.stderr,
    payload: parseJsonFromText(result.stdout),
  };
}

function preflightOpenClawGateway() {
  const call = runOpenClawGatewayCall({ method: "health", params: {}, timeout: 60_000 });
  if (call.returncode !== 0) {
    throw new Error(
      [
        "真实 OpenClaw baseline 需要已启动且可访问的 Gateway。",
        "请先运行 openclaw gateway status 或 openclaw gateway call health。",
        `health command=${call.command}`,
        `stderr=${call.stderr || ""}`,
        `stdout=${call.stdout || ""}`,
      ].join("\n"),
    );
  }
  return call;
}

function extractGatewayReplyText(payload, stdout) {
  const result = payload?.result && typeof payload.result === "object" ? payload.result : payload;
  const finalVisibleText = firstStringAtKeys(payload, [
    "finalAssistantVisibleText",
    "visibleText",
    "assistantVisibleText",
  ]);
  if (finalVisibleText) {
    return finalVisibleText;
  }
  const payloads = Array.isArray(result?.payloads) ? result.payloads : [];
  const joined = payloads
    .map((item) => item?.text)
    .filter((text) => typeof text === "string" && text.trim())
    .join("\n");
  if (joined) {
    return joined;
  }
  return (
    firstStringAtKeys(payload, ["answer", "message", "text", "content", "reply", "output"]) ||
    normalizeText(stdout)
  );
}

function firstStringAtKeys(value, keys) {
  if (!value || typeof value !== "object") {
    return "";
  }
  for (const key of keys) {
    if (typeof value[key] === "string" && value[key].trim()) {
      return value[key].trim();
    }
  }
  for (const nested of Object.values(value)) {
    if (nested && typeof nested === "object") {
      const found = firstStringAtKeys(nested, keys);
      if (found) {
        return found;
      }
    }
  }
  return "";
}

function extractIdsFromText(text, allowedIds) {
  const output = new Set();
  for (const id of allowedIds) {
    if (id && String(text).includes(id)) {
      output.add(id);
    }
  }
  return Array.from(output);
}

function normalizeReplayAnswer({ raw, query, allowedIds, stdout }) {
  const payload = raw && typeof raw === "object" ? raw : parseJsonFromText(stdout);
  const answer =
    firstStringAtKeys(payload, ["answer", "message", "text", "content", "reply", "output"]) ||
    normalizeText(stdout);
  const acceptedOnly = isAcceptedOnlyGatewayResponse({ payload, answer });
  const rawIds = Array.isArray(payload?.supporting_message_ids)
    ? payload.supporting_message_ids
    : Array.isArray(payload?.evidence_message_ids)
      ? payload.evidence_message_ids
      : [];
  const supportingIds = rawIds
    .map((id) => String(id || "").trim())
    .filter((id) => allowedIds.includes(id));
  for (const id of extractIdsFromText(answer, allowedIds)) {
    if (!supportingIds.includes(id)) {
      supportingIds.push(id);
    }
  }
  const supportSet = new Set(query.supporting_message_ids || []);
  const evidenceTraceOk = supportingIds.some((id) => supportSet.has(id));
  return {
    query_id: query.query_id,
    query: query.query,
    expected_good_behavior: query.expected_good_behavior,
    answer: acceptedOnly ? "" : answer,
    supporting_message_ids: supportingIds,
    support_quotes: [],
    raw_openclaw_output: payload ?? stdout,
    no_final_answer: acceptedOnly,
    judge_result: {
      success: Boolean(!acceptedOnly && answer && evidenceTraceOk),
      evidence_trace_ok: evidenceTraceOk,
      current_state_ok: Boolean(!acceptedOnly && answer),
      private_info_leaked: false,
      official_fact_ok: evidenceTraceOk,
      reasons: [
        ...(acceptedOnly
          ? ["真实 OpenClaw gateway 只返回 accepted/runId，未返回 final answer"]
          : []),
        evidenceTraceOk
          ? "原始 OpenClaw 输出引用了 query gold observed message_id"
          : "原始 OpenClaw 输出未引用 query gold observed message_id",
      ],
    },
  };
}

function isAcceptedOnlyGatewayResponse({ payload, answer }) {
  const text = normalizeText(answer);
  if (!payload || typeof payload !== "object") {
    return /"status"\s*:\s*"accepted"/u.test(text) && /"runId"\s*:/u.test(text);
  }
  if (payload.status === "accepted" && payload.runId) {
    return true;
  }
  if (payload.result?.status === "accepted" && payload.result?.runId) {
    return true;
  }
  return /"status"\s*:\s*"accepted"/u.test(text) && /"runId"\s*:/u.test(text);
}

function runInjectedReplayCommand({ replayInput }) {
  const command = process.env.OPENCLAW_BENCHMARK_REPLAY_COMMAND;
  if (!command) {
    return null;
  }
  const result = spawnSync(command, {
    cwd: repoRoot,
    env: process.env,
    input: JSON.stringify(replayInput),
    encoding: "utf8",
    shell: true,
  });
  if (result.status !== 0) {
    throw new Error(
      `OPENCLAW_BENCHMARK_REPLAY_COMMAND 执行失败：${result.stderr || result.stdout}`,
    );
  }
  const payload = parseJsonFromText(result.stdout);
  if (!payload || !Array.isArray(payload.answers)) {
    throw new Error("OPENCLAW_BENCHMARK_REPLAY_COMMAND 必须返回包含 answers[] 的 JSON object");
  }
  return payload;
}

function runOpenClawAgentReplay({ caseContext, queryBenchmark, observedRows, stateDir }) {
  const allowedIds = observedRows.map((row) => row.message_id).filter(Boolean);
  fs.mkdirSync(stateDir, { recursive: true });
  const { groups, sessionKeysByMessageId } = groupRowsByOpenClawSession({
    caseContext,
    observedRows,
  });
  const querySessionKey = openClawQuerySessionKey(caseContext);
  const healthCall = preflightOpenClawGateway();
  const commandPreview = `${commandParts().join(" ")} gateway call agent --params <json> --json`;
  const answers = [];
  const rawRuns = [
    {
      phase: "gateway_health",
      command: healthCall.command,
      returncode: healthCall.returncode,
      stdout: healthCall.stdout,
      stderr: healthCall.stderr,
    },
  ];
  for (const [sessionKey, rows] of groups.entries()) {
    const ingestParams = {
      message: buildTranscriptIngestPrompt({ caseContext, observedRows: rows }),
      sessionKey,
      idempotencyKey: `phase3-${caseContext.case_id}-ingest-${sessionToken(sessionKey)}`,
      deliver: false,
      timeout: 600,
      inputProvenance: {
        kind: "inter_session",
        sourceSessionKey: sessionKey,
        sourceChannel: "feishu-benchmark",
      },
    };
    const ingestCall = runOpenClawGatewayCall({
      method: "agent",
      params: ingestParams,
      expectFinal: true,
    });
    rawRuns.push({
      phase: "ingest_sender_session",
      session_key: sessionKey,
      message_count: rows.length,
      command: commandPreview,
      returncode: ingestCall.returncode,
      stdout: ingestCall.stdout,
      stderr: ingestCall.stderr,
    });
    if (ingestCall.returncode !== 0) {
      const error = new Error(
        `真实 OpenClaw gateway sender session ingest 失败 session_key=${sessionKey}: ${ingestCall.stderr || ingestCall.stdout}`,
      );
      error.replay_failure = {
        phase: "ingest_sender_session",
        command: commandPreview,
        returncode: ingestCall.returncode,
        stdout: truncateText(ingestCall.stdout),
        stderr: truncateText(ingestCall.stderr),
        gateway_state: {
          query_session_key: querySessionKey,
          failed_session_key: sessionKey,
          sender_session_count: groups.size,
          state_dir: relativePath(stateDir),
        },
        raw_runs: rawRuns.map((run) => ({
          ...run,
          stdout: truncateText(run.stdout),
          stderr: truncateText(run.stderr),
        })),
      };
      throw error;
    }
  }
  const queryContextCall = runOpenClawGatewayCall({
    method: "agent",
    params: {
      message: buildQueryContextPrompt({ caseContext, observedRows, sessionKeysByMessageId }),
      sessionKey: querySessionKey,
      idempotencyKey: `phase3-${caseContext.case_id}-query-index`,
      deliver: false,
      timeout: 600,
      inputProvenance: {
        kind: "inter_session",
        sourceSessionKey: querySessionKey,
        sourceChannel: "feishu-benchmark",
      },
    },
    expectFinal: true,
  });
  rawRuns.push({
    phase: "ingest_query_index",
    session_key: querySessionKey,
    command: commandPreview,
    returncode: queryContextCall.returncode,
    stdout: queryContextCall.stdout,
    stderr: queryContextCall.stderr,
  });
  if (queryContextCall.returncode !== 0) {
    const error = new Error(
      `真实 OpenClaw gateway query index ingest 失败：${queryContextCall.stderr || queryContextCall.stdout}`,
    );
    error.replay_failure = {
      phase: "ingest_query_index",
      command: commandPreview,
      returncode: queryContextCall.returncode,
      stdout: truncateText(queryContextCall.stdout),
      stderr: truncateText(queryContextCall.stderr),
      gateway_state: {
        query_session_key: querySessionKey,
        sender_session_count: groups.size,
        state_dir: relativePath(stateDir),
      },
      raw_runs: rawRuns.map((run) => ({
        ...run,
        stdout: truncateText(run.stdout),
        stderr: truncateText(run.stderr),
      })),
    };
    throw error;
  }
  for (const query of queryBenchmark.queries) {
    const prompt = buildQueryPrompt({ caseContext, query, allowedMessageIds: allowedIds });
    const queryCall = runOpenClawGatewayCall({
      method: "agent",
      params: {
        message: prompt,
        sessionKey: querySessionKey,
        idempotencyKey: `phase3-${caseContext.case_id}-${query.query_id}`,
        deliver: false,
        timeout: 600,
      },
      expectFinal: true,
    });
    rawRuns.push({
      query_id: query.query_id,
      command: commandPreview,
      returncode: queryCall.returncode,
      stdout: queryCall.stdout,
      stderr: queryCall.stderr,
    });
    if (queryCall.returncode !== 0) {
      const error = new Error(
        `真实 OpenClaw gateway query 失败 query_id=${query.query_id}: ${queryCall.stderr || queryCall.stdout}`,
      );
      error.replay_failure = {
        query_id: query.query_id,
        command: commandPreview,
        returncode: queryCall.returncode,
        stdout: truncateText(queryCall.stdout),
        stderr: truncateText(queryCall.stderr),
        gateway_state: {
          query_session_key: querySessionKey,
          sender_session_count: groups.size,
          state_dir: relativePath(stateDir),
        },
        raw_runs: rawRuns.map((run) => ({
          ...run,
          stdout: truncateText(run.stdout),
          stderr: truncateText(run.stderr),
        })),
      };
      throw error;
    }
    const replyText = extractGatewayReplyText(queryCall.payload, queryCall.stdout);
    answers.push(
      normalizeReplayAnswer({
        raw: parseJsonFromText(replyText) || queryCall.payload,
        query,
        allowedIds,
        stdout: replyText || queryCall.stdout,
      }),
    );
  }
  return {
    case_id: caseContext.case_id,
    family_id: caseContext.family_id,
    task_id: caseContext.task_id,
    baseline_mode: baselineMode,
    replay_kind: "gateway_agent_rpc",
    gateway_state: {
      query_session_key: querySessionKey,
      sender_session_count: groups.size,
      sender_session_keys: Array.from(groups.keys()),
      state_dir: relativePath(stateDir),
    },
    ingress_count: observedRows.length,
    query_count: queryBenchmark.queries.length,
    answers,
    raw_runs: rawRuns,
  };
}

function runBaseline({ caseContext, queryBenchmark, observedRows, stateDir }) {
  const replayInput = {
    case_context: caseContext,
    observed_messages: observedRows,
    query_benchmark: queryBenchmark,
    state_dir: stateDir,
  };
  const injected = runInjectedReplayCommand({ replayInput });
  if (injected) {
    const allowedIds = observedRows.map((row) => row.message_id).filter(Boolean);
    const answers = queryBenchmark.queries.map((query) => {
      const rawAnswer = injected.answers.find((answer) => answer.query_id === query.query_id) || {};
      return normalizeReplayAnswer({
        raw: rawAnswer,
        query,
        allowedIds,
        stdout: JSON.stringify(rawAnswer),
      });
    });
    return {
      case_id: caseContext.case_id,
      family_id: caseContext.family_id,
      task_id: caseContext.task_id,
      baseline_mode: injected.baseline_mode || baselineMode,
      replay_kind: "benchmark_replay_command",
      ingress_count: observedRows.length,
      query_count: queryBenchmark.queries.length,
      answers,
      replay_command_used: true,
    };
  }
  return runOpenClawAgentReplay({ caseContext, queryBenchmark, observedRows, stateDir });
}

function safeRate(numerator, denominator) {
  if (!denominator) {
    return 0;
  }
  return Number((numerator / denominator).toFixed(4));
}

function computeMetrics(answers) {
  const total = answers.length;
  return {
    query_success_rate: safeRate(
      answers.filter((answer) => answer.judge_result.success).length,
      total,
    ),
    evidence_output_rate: safeRate(
      answers.filter((answer) => answer.supporting_message_ids.length > 0).length,
      total,
    ),
    evidence_trace_rate: safeRate(
      answers.filter((answer) => answer.judge_result.evidence_trace_ok).length,
      total,
    ),
    current_state_accuracy: safeRate(
      answers.filter((answer) => answer.judge_result.current_state_ok).length,
      total,
    ),
    private_info_leak_rate: safeRate(
      answers.filter((answer) => answer.judge_result.private_info_leaked).length,
      total,
    ),
  };
}

function buildEvidenceTraces({ baselineResult }) {
  return {
    case_id: baselineResult.case_id,
    baseline_mode: baselineResult.baseline_mode,
    traces: baselineResult.answers.map((answer) => ({
      query_id: answer.query_id,
      supporting_message_ids: answer.supporting_message_ids,
      evidence: answer.support_quotes || [],
      judge_result: answer.judge_result,
    })),
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const caseDir = resolveCaseDir(args);
  if (!fs.existsSync(caseDir)) {
    throw new Error(`case 目录不存在：${caseDir}`);
  }
  const stateDir = args.stateDir
    ? resolveInputPath(args.stateDir)
    : path.join(caseDir, "runtime", "openclaw_baseline_state");
  fs.mkdirSync(stateDir, { recursive: true });

  const goldGeneration = ensurePhase2Gold({
    caseDir,
    semanticGold: args.semanticGold,
    requireLlm: args.requireLlm,
  });

  const caseContext = readJson(path.join(caseDir, "input", "case_context.json"));
  const semanticGold = readJson(path.join(caseDir, "gold", "task_wiki_semantic_gold.json"));
  const queryBenchmark = readJson(path.join(caseDir, "gold", "query_benchmark.json"));
  const ingressRows = readJsonl(path.join(caseDir, "data", "openclaw_message_ingress.jsonl"));
  const collectedRows = readJsonl(path.join(caseDir, "data", "collected_messages.jsonl"));
  const observedRows = createObservedRows({ ingressRows, collectedRows });
  if (observedRows.length === 0) {
    throw new Error("data/openclaw_message_ingress.jsonl 没有可回放消息");
  }
  if (!Array.isArray(queryBenchmark.queries) || queryBenchmark.queries.length === 0) {
    throw new Error("gold/query_benchmark.json 没有 queries");
  }

  const runtimeDir = path.join(caseDir, "runtime", "openclaw_baseline");
  const reportsDir = path.join(caseDir, "reports");
  const answersPath = path.join(runtimeDir, "answers.json");
  const tracesPath = path.join(runtimeDir, "evidence_traces.json");
  const replayMetadataPath = path.join(runtimeDir, "replay_metadata.json");
  const baselineReportPath = path.join(reportsDir, "openclaw_baseline_eval.json");
  const failurePath = path.join(runtimeDir, "failure.json");

  let baselineResult;
  try {
    baselineResult = runBaseline({ caseContext, queryBenchmark, observedRows, stateDir });
  } catch (error) {
    const replayFailure = error && typeof error === "object" ? error.replay_failure : null;
    const failurePayload = {
      case_id: caseContext.case_id,
      family_id: caseContext.family_id,
      task_id: caseContext.task_id,
      baseline_mode: baselineMode,
      status: "failed",
      failed_at: new Date().toISOString(),
      error_type: error instanceof Error ? error.name : typeof error,
      error_message: error instanceof Error ? error.message : String(error),
      ingress_count: observedRows.length,
      query_count: queryBenchmark.queries.length,
      state_dir: relativePath(stateDir),
      replay_failure: replayFailure || null,
    };
    writeJson(failurePath, failurePayload);
    writeJson(replayMetadataPath, {
      baseline_mode: baselineMode,
      replay_kind: replayFailure ? "gateway_agent_rpc" : "unknown",
      replay_command_used: Boolean(process.env.OPENCLAW_BENCHMARK_REPLAY_COMMAND),
      gateway_state: replayFailure?.gateway_state || null,
      raw_runs: replayFailure?.raw_runs || [],
      status: "failed",
      failure_path: relativePath(failurePath),
    });
    throw error;
  }
  const metrics = computeMetrics(baselineResult.answers);

  const answersPayload = {
    ...baselineResult,
    generated_at: new Date().toISOString(),
    state_dir: relativePath(stateDir),
    semantic_gold_mode: semanticGold.mode || args.semanticGold,
  };
  const evidenceTraces = buildEvidenceTraces({ baselineResult });
  const replayMetadata = {
    baseline_mode: baselineResult.baseline_mode,
    replay_kind: baselineResult.replay_kind,
    replay_command_used: Boolean(baselineResult.replay_command_used),
    gateway_state: baselineResult.gateway_state || null,
    raw_runs: baselineResult.raw_runs || [],
  };
  const baselineReport = {
    case_id: caseContext.case_id,
    family_id: caseContext.family_id,
    task_id: caseContext.task_id,
    baseline_mode: baselineResult.baseline_mode,
    replay_kind: baselineResult.replay_kind,
    gateway_state: baselineResult.gateway_state || null,
    ingress_count: observedRows.length,
    collected_message_count: collectedRows.length,
    query_count: queryBenchmark.queries.length,
    semantic_gold_mode: semanticGold.mode || args.semanticGold,
    gold_generation: goldGeneration,
    metrics,
    answer_ids: baselineResult.answers.map((answer) => answer.query_id),
    evidence_policy:
      "No evidence is fabricated. If OpenClaw does not output observed message ids, evidence_output_rate remains 0.",
  };
  const paths = {
    answers: relativePath(answersPath),
    traces: relativePath(tracesPath),
    replayMetadata: relativePath(replayMetadataPath),
    baselineReport: relativePath(baselineReportPath),
  };

  if (fs.existsSync(failurePath)) {
    fs.rmSync(failurePath, { force: true });
  }
  writeJson(answersPath, answersPayload);
  writeJson(tracesPath, evidenceTraces);
  writeJson(replayMetadataPath, replayMetadata);
  writeJson(baselineReportPath, baselineReport);

  const summary = {
    status: "completed",
    case_dir: relativePath(caseDir),
    baseline_mode: baselineResult.baseline_mode,
    replay_kind: baselineResult.replay_kind,
    ingress_count: observedRows.length,
    query_count: queryBenchmark.queries.length,
    metrics,
    outputs: paths,
  };
  if (args.json) {
    console.log(JSON.stringify(summary));
  } else if (args.quiet) {
    console.log(`baseline completed: ${paths.baselineReport}`);
  } else {
    console.log(`OpenClaw real baseline completed for ${caseContext.case_id}`);
    console.log(`- ingress: ${observedRows.length}`);
    console.log(`- queries: ${queryBenchmark.queries.length}`);
    console.log(`- baseline json: ${paths.baselineReport}`);
  }
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
