#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");

function parseArgs(argv) {
  const args = {
    datasetRoot: "amem_docs/ds/feishu_im_dataset_v3",
    caseDir: "",
    stateDir: "",
    semanticGold: "auto",
    requireLlm: false,
    json: false,
    quiet: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--case-dir") args.caseDir = argv[++index] ?? "";
    else if (item === "--dataset-root") args.datasetRoot = argv[++index] ?? "";
    else if (item === "--state-dir") args.stateDir = argv[++index] ?? "";
    else if (item === "--semantic-gold") args.semanticGold = argv[++index] ?? "auto";
    else if (item === "--require-llm") args.requireLlm = true;
    else if (item === "--json") args.json = true;
    else if (item === "--quiet") args.quiet = true;
    else if (item === "-h" || item === "--help" || item === "help") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`未知参数：${item}`);
    }
  }
  return args;
}

function printHelp() {
  console.log(`用法：
  amem_docs/scripts/feishu-task-wiki-runtime-eval.sh [options]

说明：
  - 这个脚本用于把 case 的 data/openclaw_message_ingress.jsonl 回放进真实 Task Wiki 三层 runtime。
  - 它评估的是三层运行健康度：Layer 1 任务绑定、Layer 2 事件抽取/验证、Layer 3 Wiki 投影/lint。
  - 它不替代 Phase 2/3 的语义 gold、query benchmark 或最终 value eval。
  - 若未显式传 --case-dir，默认读取 dataset root 下的 active_case.json。

常用参数：
  --case-dir <path>
      显式指定要评估的 case 目录。
      若省略，则默认读取当前 active case。

  --dataset-root <path>
      dataset root。
      默认：amem_docs/ds/feishu_im_dataset_v3

  --state-dir <path>
      指定本次 replay 使用的 OpenClaw state 目录。
      默认：<case_dir>/runtime/task_wiki_state
      每次运行会清理并重建这个目录。

  --semantic-gold <mode>
      可选：auto | llm | rule | off。
      仅记录到 summary，用于和 Phase 2 口径对齐；本脚本不做 semantic benchmark scoring。

  --require-llm
      当 semantic gold mode 要求 LLM 但环境没有模型配置时直接失败。

  --json
      只输出一行机器可读 JSON summary。

  --quiet
      只输出最终 status、health_score 和 markdown report 路径。

输出：
  <case_dir>/runtime/task_wiki_replay/summary.json
      本次 runtime eval 总结。

  <case_dir>/runtime/task_wiki_replay/layer_metrics.json
      三层健康指标明细。

  <case_dir>/runtime/task_wiki_replay/task_wiki_runtime_predictions.json
      verification、lint、task wiki runtime trace。

  <case_dir>/reports/task_wiki_runtime_eval.md
      面向人工阅读的评估报告。

三层指标：
  Layer 1：Task Binding
      status / score / binding_total / binding_bound / binding_rate / target_task_binding_rate / skipped_count

  Layer 2：Event Extraction + Verification
      status / score / ingested_count / candidate_event_count / verified_event_count / verification_rate / session_count / sessions_with_events

  Layer 3：Wiki Projection + Lint
      status / score / task_root_count / projected_task_count / projection_status / lint_blocking_count / lint_warning_count

  Overall：
      status / health_score / blocking_failures / warnings

分数计算：
  - Layer 1 score = target_task_binding_rate * 100。
  - Layer 2 score = verification_rate * 100。
  - Layer 3 score = projection 通过得 100 分；blocking lint 每项扣 5 分，最多扣 20 分。
  - health_score = Layer1 * 35% + Layer2 * 35% + Layer3 * 30%。

通过标准：
  - Layer 1 至少能绑定目标 task。
  - Layer 2 至少产生 verified events。
  - Layer 3 至少生成 task wiki projection。
  - lint 不存在 blocking findings。

退出码：
  0  runtime eval 通过。
  1  输入、配置或 runtime 执行错误。
  2  runtime 跑完，但三层健康门槛需要复查。

示例：
  amem_docs/scripts/feishu-task-wiki-runtime-eval.sh
  amem_docs/scripts/feishu-task-wiki-runtime-eval.sh --quiet
  amem_docs/scripts/feishu-task-wiki-runtime-eval.sh --json
  amem_docs/scripts/feishu-task-wiki-runtime-eval.sh --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/<case_id>
  amem_docs/scripts/feishu-task-wiki-runtime-eval.sh --case-dir <case_dir> --state-dir /tmp/task-wiki-runtime-state
`);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readJsonl(filePath) {
  if (!fs.existsSync(filePath)) return [];
  return fs.readFileSync(filePath, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function writeJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function writeText(filePath, text) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, text, "utf8");
}

function resolveCaseDir(args) {
  if (args.caseDir) return path.resolve(repoRoot, args.caseDir);
  const activeCase = readJson(path.resolve(repoRoot, args.datasetRoot, "active_case.json"));
  return path.resolve(repoRoot, activeCase.case_dir);
}

function extractMessageText(row) {
  const content = row?.message?.content;
  if (typeof content !== "string") return "";
  try {
    const parsed = JSON.parse(content);
    return typeof parsed.text === "string" ? parsed.text : content;
  } catch {
    return content;
  }
}

function sourceTypeFor(row) {
  const traceType = row?.benchmark_trace?.source_type;
  if (traceType === "thread" || traceType === "comment" || traceType === "doc" || traceType === "chat") {
    return traceType;
  }
  return row?.message?.thread_id ? "thread" : "chat";
}

function sourceIdFor(row, sourceType) {
  const sourceRef = row?.benchmark_trace?.source_ref;
  if (typeof sourceRef === "string" && sourceRef.trim()) return sourceRef;
  if (sourceType === "thread") return `thread:${row?.message?.thread_id || row?.message?.root_id || row?.message?.message_id}`;
  return `chat:${row?.message?.chat_id}`;
}

function countFiles(rootDir, fileName) {
  const result = [];
  if (!fs.existsSync(rootDir)) return result;
  const stack = [rootDir];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(entryPath);
      else if (entry.name === fileName) result.push(entryPath);
    }
  }
  return result;
}

function safeRate(numerator, denominator) {
  if (!denominator) return 0;
  return Number((numerator / denominator).toFixed(4));
}

function countSessionEventFilesWithEvents(sessionEventFiles) {
  return sessionEventFiles.filter((filePath) => readJsonl(filePath).length > 0).length;
}

function incrementCounter(counter, key) {
  const normalizedKey = String(key || "unknown");
  counter[normalizedKey] = Number(counter[normalizedKey] ?? 0) + 1;
}

function summarizeCandidateValidation(candidateRecords) {
  const candidateValidationBreakdown = {};
  const rejectionReasonBreakdown = {};
  const missingFieldBreakdown = {};
  let rejectedCandidateCount = 0;
  let readyForVerificationCount = 0;
  let queuedVerificationCount = 0;
  for (const candidate of candidateRecords) {
    const verdict = candidate?.programmatic_validation?.verdict ?? "unknown";
    incrementCounter(candidateValidationBreakdown, verdict);
    if (verdict === "ready_for_verification") {
      readyForVerificationCount += 1;
    }
    if (candidate?.processing_status === "pending_verification" || candidate?.verification_job_id) {
      queuedVerificationCount += 1;
    }
    if (verdict !== "rejected" && candidate?.processing_status !== "rejected") {
      continue;
    }
    rejectedCandidateCount += 1;
    const reasons = candidate?.programmatic_validation?.rejection_reasons
      ?? candidate?.verification?.rejection_reasons
      ?? [];
    if (Array.isArray(reasons) && reasons.length > 0) {
      for (const reason of reasons) {
        incrementCounter(rejectionReasonBreakdown, reason);
      }
    } else {
      incrementCounter(rejectionReasonBreakdown, "unknown");
    }
    const missingFields = candidate?.programmatic_validation?.missing_required_fields
      ?? candidate?.verification?.missing_required_fields
      ?? [];
    if (Array.isArray(missingFields)) {
      for (const field of missingFields) {
        incrementCounter(missingFieldBreakdown, field);
      }
    }
  }
  return {
    candidate_validation_breakdown: candidateValidationBreakdown,
    rejected_candidate_count: rejectedCandidateCount,
    ready_for_verification_count: readyForVerificationCount,
    queued_verification_count: queuedVerificationCount,
    rejection_reason_breakdown: rejectionReasonBreakdown,
    missing_field_breakdown: missingFieldBreakdown,
  };
}

function summarizeLint(lintResults) {
  const totals = {
    orphan_event_count: 0,
    missing_evidence_ref_count: 0,
    stale_claim_count: 0,
    quote_strength_count: 0,
    unresolved_objection_count: 0,
    overdue_commitment_count: 0,
    open_conflict_count: 0,
    orphan_block_count: 0,
    missing_cross_ref_count: 0,
    orphan_session_wiki_count: 0,
  };
  for (const result of lintResults) {
    for (const key of Object.keys(totals)) {
      totals[key] += Number(result?.[key] ?? 0);
    }
  }
  const lintBlockingCount =
    totals.open_conflict_count +
    totals.stale_claim_count +
    totals.missing_cross_ref_count +
    totals.orphan_session_wiki_count;
  const lintWarningCount =
    totals.orphan_event_count +
    totals.missing_evidence_ref_count +
    totals.quote_strength_count +
    totals.unresolved_objection_count +
    totals.overdue_commitment_count +
    totals.orphan_block_count;
  return {
    ...totals,
    lint_blocking_count: lintBlockingCount,
    lint_warning_count: lintWarningCount,
  };
}

function buildLayer1Verdict(layer1Binding) {
  const blockingFailures = [];
  const warnings = [];
  if (layer1Binding.binding_total === 0) {
    blockingFailures.push("layer1:no_ingress_messages");
  }
  if (layer1Binding.binding_bound === 0) {
    blockingFailures.push("layer1:no_task_bindings");
  }
  if (layer1Binding.target_task_binding_rate < 1) {
    blockingFailures.push("layer1:target_task_binding_incomplete");
  }
  return {
    status: blockingFailures.length === 0 ? "passed" : "needs_review",
    score: Number((layer1Binding.target_task_binding_rate * 100).toFixed(2)),
    blocking_failures: blockingFailures,
    warnings,
  };
}

function buildLayer2Verdict(layer2Events) {
  const blockingFailures = [];
  const warnings = [];
  if (layer2Events.verified_event_count === 0) {
    blockingFailures.push("layer2:no_verified_events");
  }
  if (layer2Events.candidate_event_count === 0) {
    warnings.push("layer2:no_candidate_events");
  }
  if (layer2Events.verification_rate < 0.8 && layer2Events.candidate_event_count > 0) {
    warnings.push("layer2:low_verification_rate");
  }
  return {
    status: blockingFailures.length === 0 ? "passed" : "needs_review",
    score: Number((Math.min(1, layer2Events.verification_rate) * 100).toFixed(2)),
    blocking_failures: blockingFailures,
    warnings,
  };
}

function buildLayer3Verdict(layer3Wiki, layer2Events) {
  const blockingFailures = [];
  const warnings = [];
  if (layer2Events.verified_event_count === 0) {
    blockingFailures.push("layer3:blocked_by_layer2_no_verified_events");
  }
  if (layer3Wiki.projected_task_count === 0) {
    blockingFailures.push("layer3:no_projected_task_wiki");
  }
  if (layer3Wiki.lint_blocking_count > 0) {
    blockingFailures.push("layer3:blocking_lint_findings");
  }
  if (layer3Wiki.lint_warning_count > 0) {
    warnings.push("layer3:lint_warnings_present");
  }
  const projectionScore = layer2Events.verified_event_count > 0 && layer3Wiki.projected_task_count > 0 ? 100 : 0;
  const lintPenalty = Math.min(20, layer3Wiki.lint_blocking_count * 5);
  return {
    status: layer2Events.verified_event_count === 0
      ? "blocked_by_layer2"
      : blockingFailures.length === 0
        ? "passed"
        : "needs_review",
    score: Math.max(0, Number((projectionScore - lintPenalty).toFixed(2))),
    blocking_failures: blockingFailures,
    warnings,
  };
}

function buildOverallHealth({ layer1Binding, layer2Events, layer3Wiki }) {
  const blockingFailures = [
    ...layer1Binding.blocking_failures,
    ...layer2Events.blocking_failures,
    ...layer3Wiki.blocking_failures,
  ];
  const warnings = [
    ...layer1Binding.warnings,
    ...layer2Events.warnings,
    ...layer3Wiki.warnings,
  ];
  const healthScore = Number((
    layer1Binding.score * 0.35 +
    layer2Events.score * 0.35 +
    layer3Wiki.score * 0.30
  ).toFixed(2));
  return {
    status: blockingFailures.length === 0 ? "passed" : "needs_review",
    blocking_failures: blockingFailures,
    warnings,
    health_score: Math.max(0, Math.min(100, healthScore)),
  };
}

function renderRuntimeEvalReport({ caseContext, caseDir, stateDir, replayDir, reportsDir, layerMetrics, predictions }) {
  const reportPath = path.join(reportsDir, "task_wiki_runtime_eval.md");
  const lines = [
    "# Task Wiki Runtime Eval",
    "",
    "## 如何阅读结果",
    "",
    "- 这份报告只评估真实 Task Wiki 三层 runtime 是否健康跑通，不判断 query answer 的语义胜负。",
    "- `candidate_events` 表示 Layer 2 从消息中抽到了候选事件。",
    "- `verified_events` 表示候选事件通过验证并进入 Layer 3 projector。",
    "- `status=passed` 只代表三层健康门槛通过；完整 benchmark 效能仍看 Phase 2/3 的 gold、replay 和 value eval。",
    "",
    "## Summary",
    "",
    `- case_id: ${caseContext.case_id}`,
    `- task_id: ${caseContext.task_id}`,
    `- case_dir: ${path.relative(repoRoot, caseDir)}`,
    `- state_dir: ${path.relative(repoRoot, stateDir)}`,
    `- status: ${layerMetrics.overall.status}`,
    `- health_score: ${layerMetrics.overall.health_score}`,
    `- score_formula: Layer1 * 35% + Layer2 * 35% + Layer3 * 30%`,
    "",
    "## Layer 1: Task Binding",
    "",
    `- status: ${layerMetrics.layer1_binding.status}`,
    `- score: ${layerMetrics.layer1_binding.score}`,
    `- binding_total: ${layerMetrics.layer1_binding.binding_total}`,
    `- binding_bound: ${layerMetrics.layer1_binding.binding_bound}`,
    `- binding_rate: ${layerMetrics.layer1_binding.binding_rate}`,
    `- target_task_binding_rate: ${layerMetrics.layer1_binding.target_task_binding_rate}`,
    `- skipped_count: ${layerMetrics.layer1_binding.skipped_count}`,
    `- blocking_failures: ${layerMetrics.layer1_binding.blocking_failures.length ? layerMetrics.layer1_binding.blocking_failures.join(", ") : "none"}`,
    `- warnings: ${layerMetrics.layer1_binding.warnings.length ? layerMetrics.layer1_binding.warnings.join(", ") : "none"}`,
    "",
    "Layer 1 失败时优先检查：",
    "",
    "- `data/openclaw_message_ingress.jsonl` 是否存在目标 task id 或可绑定上下文。",
    "- `input/case_context.json` 的 `task_id` 是否和 replay 消息一致。",
    "",
    "## Layer 2: Event Extraction / Verification",
    "",
    `- status: ${layerMetrics.layer2_events.status}`,
    `- score: ${layerMetrics.layer2_events.score}`,
    `- ingested_count: ${layerMetrics.layer2_events.ingested_count}`,
    `- candidate_event_count: ${layerMetrics.layer2_events.candidate_event_count}`,
    `- verified_event_count: ${layerMetrics.layer2_events.verified_event_count}`,
    `- verification_rate: ${layerMetrics.layer2_events.verification_rate}`,
    `- session_count: ${layerMetrics.layer2_events.session_count}`,
    `- sessions_with_events: ${layerMetrics.layer2_events.sessions_with_events}`,
    `- ready_for_verification_count: ${layerMetrics.layer2_events.ready_for_verification_count}`,
    `- queued_verification_count: ${layerMetrics.layer2_events.queued_verification_count}`,
    `- rejected_candidate_count: ${layerMetrics.layer2_events.rejected_candidate_count}`,
    `- blocking_failures: ${layerMetrics.layer2_events.blocking_failures.length ? layerMetrics.layer2_events.blocking_failures.join(", ") : "none"}`,
    `- warnings: ${layerMetrics.layer2_events.warnings.length ? layerMetrics.layer2_events.warnings.join(", ") : "none"}`,
    "",
    "### Candidate Rejection Breakdown",
    "",
    `- candidate_validation_breakdown: ${JSON.stringify(layerMetrics.layer2_events.candidate_validation_breakdown)}`,
    `- rejection_reason_breakdown: ${JSON.stringify(layerMetrics.layer2_events.rejection_reason_breakdown)}`,
    `- missing_field_breakdown: ${JSON.stringify(layerMetrics.layer2_events.missing_field_breakdown)}`,
    "",
    "Layer 2 失败时优先检查：",
    "",
    "- `runtime/task_wiki_state/**/candidate_events.jsonl` 是否为空。",
    "- `runtime/task_wiki_state/**/session_events.jsonl` 是否有 verified 事件。",
    "- `data/openclaw_message_ingress.jsonl` 的正文是否被正确剥离 speaker prefix。",
    "",
    "## Layer 3: Wiki Projection / Lint",
    "",
    `- status: ${layerMetrics.layer3_wiki.status}`,
    `- score: ${layerMetrics.layer3_wiki.score}`,
    `- task_root_count: ${layerMetrics.layer3_wiki.task_root_count}`,
    `- projected_task_count: ${layerMetrics.layer3_wiki.projected_task_count}`,
    `- projection_status: ${layerMetrics.layer3_wiki.projection_status}`,
    `- lint_blocking_count: ${layerMetrics.layer3_wiki.lint_blocking_count}`,
    `- lint_warning_count: ${layerMetrics.layer3_wiki.lint_warning_count}`,
    `- blocking_failures: ${layerMetrics.layer3_wiki.blocking_failures.length ? layerMetrics.layer3_wiki.blocking_failures.join(", ") : "none"}`,
    `- warnings: ${layerMetrics.layer3_wiki.warnings.length ? layerMetrics.layer3_wiki.warnings.join(", ") : "none"}`,
    "",
    "Layer 3 失败时优先检查：",
    "",
    "- `runtime/task_wiki_state/**/task_wiki_state.json` 是否生成。",
    "- `runtime/task_wiki_state/**/task_wiki.md` 是否生成。",
    "- `runtime/task_wiki_state/**/lint_state.json` 的 blocking findings。",
    "",
    "## Overall Health",
    "",
    `- blocking_failures: ${layerMetrics.overall.blocking_failures.length ? layerMetrics.overall.blocking_failures.join(", ") : "none"}`,
    `- warnings: ${layerMetrics.overall.warnings.length ? layerMetrics.overall.warnings.join(", ") : "none"}`,
    "",
    "## Output Files",
    "",
    `- summary: ${path.relative(repoRoot, path.join(replayDir, "summary.json"))}`,
    `- layer_metrics: ${path.relative(repoRoot, path.join(replayDir, "layer_metrics.json"))}`,
    `- predictions: ${path.relative(repoRoot, path.join(replayDir, "task_wiki_runtime_predictions.json"))}`,
    `- report: ${path.relative(repoRoot, reportPath)}`,
    "",
    "## Runtime Trace",
    "",
    `- verification_result_count: ${predictions.verification_results.length}`,
    `- lint_result_count: ${predictions.lint_results.length}`,
    "",
  ];
  return lines.join("\n");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!["auto", "llm", "rule", "off"].includes(args.semanticGold)) {
    throw new Error(`非法 --semantic-gold 模式：${args.semanticGold}。可选值：auto、llm、rule、off。`);
  }
  const caseDir = resolveCaseDir(args);
  const stateDir = args.stateDir
    ? path.resolve(repoRoot, args.stateDir)
    : path.join(caseDir, "runtime", "task_wiki_state");
  const replayDir = path.join(caseDir, "runtime", "task_wiki_replay");
  const reportsDir = path.join(caseDir, "reports");
  const ingressPath = path.join(caseDir, "data", "openclaw_message_ingress.jsonl");
  const collectedPath = path.join(caseDir, "data", "collected_messages.jsonl");
  const caseContext = readJson(path.join(caseDir, "input", "case_context.json"));
  const ingressRows = readJsonl(ingressPath);
  const collectedRows = readJsonl(collectedPath);
  if (!ingressRows.length) {
    throw new Error(`No replay ingress rows found: ${ingressPath}`);
  }
  if (args.requireLlm && args.semanticGold === "llm" && !process.env.OPENAI_API_KEY) {
    throw new Error("--require-llm was set, but OPENAI_API_KEY is not configured in the process env");
  }

  fs.rmSync(stateDir, { recursive: true, force: true });
  fs.mkdirSync(stateDir, { recursive: true });
  process.env.OPENCLAW_STATE_DIR = stateDir;
  process.env.OPENCLAW_FEISHU_TASK_WIKI_DISABLE_ASYNC_VERIFIER = "1";

  const { resolveTaskBindingForInbound } = require(path.join(repoRoot, "extensions/feishu-task-wiki/openclaw-lark/src/task-banding/task-binding-store.js"));
  const { maybeIngestTaskSourceSession, runVerificationJobs } = require(path.join(repoRoot, "extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.js"));
  const { updateTaskWikiFromVerifiedEvents } = require(path.join(repoRoot, "extensions/feishu-task-wiki/openclaw-lark/src/task-wiki/projector.js"));
  const { runTaskWikiLint } = require(path.join(repoRoot, "extensions/feishu-task-wiki/openclaw-lark/src/task-wiki/lint.js"));

  const sessionDirs = new Set();
  const bindingMetrics = { total: 0, bound: 0, skipped: 0, targetTaskBound: 0 };
  const ingestMetrics = { ingested: 0, skipped: 0, candidateEvents: 0, verificationJobsQueued: 0 };

  for (const row of ingressRows) {
    const message = row.message ?? {};
    const text = extractMessageText(row);
    const sourceType = sourceTypeFor(row);
    const sourceId = sourceIdFor(row, sourceType);
    bindingMetrics.total += 1;
    const taskBinding = resolveTaskBindingForInbound({
      accountId: "benchmark",
      sourceType,
      sourceId,
      chatId: message.chat_id || null,
      threadId: message.thread_id || null,
      rootId: message.root_id || null,
      rootMessageText: `${caseContext.task_id} ${text}`,
      chatTitle: `${caseContext.task_id} runtime eval`,
      allowInitialize: true,
    });
    if (!taskBinding) {
      bindingMetrics.skipped += 1;
      continue;
    }
    bindingMetrics.bound += 1;
    if (taskBinding.task?.taskKey === String(caseContext.task_id)) {
      bindingMetrics.targetTaskBound += 1;
    }
    const ingest = await maybeIngestTaskSourceSession({
      accountId: "benchmark",
      taskBinding,
      sourceType,
      sourceId,
      chatId: message.chat_id || null,
      threadId: message.thread_id || null,
      rootId: message.root_id || null,
      messageId: message.message_id,
      senderId: row.sender?.sender_id?.open_id,
      senderName: row.sender?.sender_name,
      content: text,
      createTime: message.create_time || new Date().toISOString(),
      sourceLocator: row.benchmark_trace?.source_ref || sourceId,
    });
    if (ingest.skipped) {
      ingestMetrics.skipped += 1;
      continue;
    }
    ingestMetrics.ingested += 1;
    ingestMetrics.candidateEvents += Number(ingest.candidateEventCount ?? 0);
    ingestMetrics.verificationJobsQueued += Number(ingest.verificationJobsQueued ?? 0);
    if (ingest.sessionDir) sessionDirs.add(ingest.sessionDir);
  }

  const verificationResults = [];
  for (const sessionDir of sessionDirs) {
    verificationResults.push({ sessionDir, ...(await runVerificationJobs({ sessionDir })) });
    await updateTaskWikiFromVerifiedEvents({ sessionDir });
  }
  const taskRoot = path.join(stateDir, "feishu-task-wiki", "tasks");
  const taskDirs = fs.existsSync(taskRoot)
    ? fs.readdirSync(taskRoot).map((name) => path.join(taskRoot, name)).filter((item) => fs.statSync(item).isDirectory())
    : [];
  const lintResults = [];
  for (const taskRootDir of taskDirs) {
    lintResults.push({ taskRootDir, ...(await runTaskWikiLint({ taskRootDir, appendLog: true })) });
  }

  const candidateFiles = countFiles(taskRoot, "candidate_events.jsonl");
  const sessionEventFiles = countFiles(taskRoot, "session_events.jsonl");
  const candidateRecords = candidateFiles.flatMap(readJsonl);
  const candidateEventCount = candidateRecords.length;
  const verifiedEventCount = sessionEventFiles.flatMap(readJsonl).length;
  const sessionsWithEvents = countSessionEventFilesWithEvents(sessionEventFiles);
  const lintSummary = summarizeLint(lintResults);
  const candidateValidationSummary = summarizeCandidateValidation(candidateRecords);
  const layer1Binding = {
    binding_total: bindingMetrics.total,
    binding_bound: bindingMetrics.bound,
    binding_rate: safeRate(bindingMetrics.bound, bindingMetrics.total),
    target_task_binding_rate: safeRate(bindingMetrics.targetTaskBound, bindingMetrics.total),
    skipped_count: bindingMetrics.skipped,
  };
  Object.assign(layer1Binding, buildLayer1Verdict(layer1Binding));
  const layer2Events = {
    ingested_count: ingestMetrics.ingested,
    skipped_count: ingestMetrics.skipped,
    candidate_events_returned_during_ingest: ingestMetrics.candidateEvents,
    verification_jobs_queued: ingestMetrics.verificationJobsQueued,
    candidate_event_count: candidateEventCount,
    verified_event_count: verifiedEventCount,
    verification_rate: safeRate(verifiedEventCount, candidateEventCount),
    session_count: sessionDirs.size,
    sessions_with_events: sessionsWithEvents,
    ...candidateValidationSummary,
  };
  Object.assign(layer2Events, buildLayer2Verdict(layer2Events));
  const layer3Wiki = {
    task_root_count: taskDirs.length,
    projected_task_count: taskDirs.length,
    projection_rate: safeRate(taskDirs.length, taskDirs.length || 1),
    projection_status: taskDirs.length > 0 ? "projected" : "missing",
    lint_result_count: lintResults.length,
    ...lintSummary,
  };
  Object.assign(layer3Wiki, buildLayer3Verdict(layer3Wiki, layer2Events));
  const overall = buildOverallHealth({
    layer1Binding,
    layer2Events,
    layer3Wiki,
  });
  const layerMetrics = {
    case_id: caseContext.case_id,
    task_id: caseContext.task_id,
    input: {
      ingress_count: ingressRows.length,
      collected_message_count: collectedRows.length,
    },
    layer1_binding: layer1Binding,
    layer2_events: layer2Events,
    layer3_wiki: layer3Wiki,
    overall,
  };
  const predictions = {
    case_id: caseContext.case_id,
    task_id: caseContext.task_id,
    state_dir: path.relative(repoRoot, stateDir),
    task_roots: taskDirs.map((dir) => path.relative(repoRoot, dir)),
    verification_results: verificationResults,
    lint_results: lintResults,
  };
  const summary = {
    case_dir: path.relative(repoRoot, caseDir),
    semantic_gold_mode: args.semanticGold,
    status: overall.status,
    health_score: overall.health_score,
    blocking_failures: overall.blocking_failures,
    warnings: overall.warnings,
    report_path: path.relative(repoRoot, path.join(reportsDir, "task_wiki_runtime_eval.md")),
    layer_metrics: layerMetrics,
  };
  writeJson(path.join(replayDir, "summary.json"), summary);
  writeJson(path.join(replayDir, "layer_metrics.json"), layerMetrics);
  writeJson(path.join(replayDir, "task_wiki_runtime_predictions.json"), predictions);
  writeText(
    path.join(reportsDir, "task_wiki_runtime_eval.md"),
    renderRuntimeEvalReport({
      caseContext,
      caseDir,
      stateDir,
      replayDir,
      reportsDir,
      layerMetrics,
      predictions,
    }),
  );
  if (args.json) {
    console.log(JSON.stringify(summary));
  } else if (args.quiet) {
    console.log(`status=${summary.status} health_score=${summary.health_score} report=${summary.report_path}`);
  } else {
    console.log(JSON.stringify(summary, null, 2));
  }
  if (summary.status !== "passed") {
    process.exitCode = 2;
  }
}

main().catch((error) => {
  console.error(error?.message || String(error));
  process.exit(1);
});
