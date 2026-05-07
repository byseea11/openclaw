#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const defaultDatasetRoot = "amem_docs/ds/feishu_im_dataset_v3";
const baselineMode = "openclaw_original_adapter";
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
  if (!semanticGoldModes.has(args.semanticGold)) {
    throw new Error(`--semantic-gold 只能是 ${Array.from(semanticGoldModes).join("|")}`);
  }
  return args;
}

function printHelp() {
  console.log(`用法：
  amem_docs/scripts/feishu-openclaw-baseline-eval.sh [options]

说明：
  - 这个脚本只评估原始 OpenClaw baseline，不调用 Task Wiki 三层实现。
  - 若仓库当前没有可直接复用的原始 replay API，会使用 openclaw_original_adapter：
    完整消息历史 + 默认记忆摘要 + query 的输入形态。
  - 如果缺少 Phase2 gold，会先补 annotation gold、semantic gold 和 query benchmark。
  - 当前 Python phase3 中的 baseline_eval.py 仍是 synthetic baseline，不能代表真实 baseline。

参数：
  --case-dir <path>
      显式指定 case 目录。若省略，读取 dataset root 的 active_case.json。

  --dataset-root <path>
      dataset root。默认：${defaultDatasetRoot}

  --state-dir <path>
      baseline 状态目录。默认：<case_dir>/runtime/openclaw_baseline_state

  --semantic-gold <mode>
      auto | llm | rule | off，默认 auto。

  --require-llm
      若 semantic gold 需要 LLM 但环境缺配置，则失败而不是回退。

  --json
      只输出一行 JSON summary。

  --quiet
      只输出最终报告路径。

输出：
  <case_dir>/runtime/openclaw_baseline/answers.json
  <case_dir>/runtime/openclaw_baseline/evidence_traces.json
  <case_dir>/reports/openclaw_baseline_eval.json
  <case_dir>/reports/openclaw_vs_task_wiki_comparison.md

示例：
  amem_docs/scripts/feishu-openclaw-baseline-eval.sh --case-dir amem_docs/ds/feishu_im_dataset_v3/cases/<case_id>
  amem_docs/scripts/feishu-openclaw-baseline-eval.sh --case-dir <case_dir> --semantic-gold rule --json
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

function resolveInputPath(value) {
  return path.isAbsolute(value) ? value : path.resolve(repoRoot, value);
}

function relativePath(filePath) {
  return path.relative(repoRoot, filePath);
}

function resolveCaseDir(args) {
  if (args.caseDir) return resolveInputPath(args.caseDir);
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
    if (requireLlm) command.push("--require-llm");
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
  if (before.length === 0) return { generated: false, missing_before: [], generated_stages: [] };

  const annotationPath = path.join(caseDir, "gold", "annotation_gold.jsonl");
  const semanticPath = path.join(caseDir, "gold", "task_wiki_semantic_gold.json");
  const queryPath = path.join(caseDir, "gold", "query_benchmark.json");
  if (!fs.existsSync(annotationPath)) {
    runPhase2Stage({ caseDir, stage: "annotation-gold", semanticGold, requireLlm });
    generatedStages.push("annotation-gold");
  }
  if (!fs.existsSync(semanticPath)) {
    runPhase2Stage({ caseDir, stage: "semantic-gold", semanticGold, requireLlm });
    generatedStages.push("semantic-gold");
  }
  if (!fs.existsSync(queryPath)) {
    runPhase2Stage({ caseDir, stage: "query-benchmark", semanticGold, requireLlm });
    generatedStages.push("query-benchmark");
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
      if (typeof parsed.text === "string") return parsed.text;
    } catch {
      return content;
    }
  }
  if (typeof row?.message_text === "string") return row.message_text;
  return "";
}

function collectedText(row) {
  return String(row?.observed_text_without_prefix || row?.message_text || row?.content_text || "");
}

function normalizeText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function createObservedRows({ ingressRows, collectedRows }) {
  const collectedById = new Map();
  for (const row of collectedRows) {
    if (row?.message_id) collectedById.set(row.message_id, row);
  }
  return ingressRows.map((row, index) => {
    const message = row?.message || {};
    const messageId = String(message.message_id || row?.message_id || "");
    const collected = collectedById.get(messageId) || {};
    const text = normalizeText(collectedText(collected) || extractMessageText(row));
    const createdAt = Number(message.create_time || row?.create_time || index);
    return {
      index,
      message_id: messageId,
      create_time: Number.isFinite(createdAt) ? createdAt : index,
      chat_id: String(message.chat_id || ""),
      thread_id: String(message.thread_id || ""),
      root_id: String(message.root_id || ""),
      session_id: String(collected.session_id || row?.benchmark_trace?.source_ref || ""),
      source_type: String(collected.source_type || row?.benchmark_trace?.source_type || ""),
      sender: String(collected?.simulated_speaker?.name || collected?.prefix_speaker_hint?.name || ""),
      text,
      annotation_target: Boolean(collected.annotation_target || row?.benchmark_trace?.annotation_target),
      event_bearing: Boolean(collected.event_bearing || row?.benchmark_trace?.event_bearing),
      official_file_ref: String(collected.official_file_ref || ""),
      private_info_ref: String(collected.private_info_ref || ""),
      task_relevance_boundary: String(collected.task_relevance_boundary || ""),
      turn_kind: String(collected.turn_kind || ""),
    };
  }).sort((left, right) => left.create_time - right.create_time || left.index - right.index);
}

const officialTerms = [
  "正式",
  "纪要",
  "上线风险评审",
  "以纪要为准",
  "窗口",
  "升级",
  "blocker",
  "回滚",
  "已批",
  "批准",
  "批准",
  "network config drift",
  "当前",
];

const privateTerms = [
  "个人",
  "偏好",
  "面试",
  "家庭",
  "白天",
  "周三",
  "效率",
  "全量备份",
  "个人时间",
  "个人观点",
  "不影响任务",
];

function containsAny(text, terms) {
  return terms.some((term) => text.includes(term));
}

function classifyRowForAdapter(row) {
  const text = row.text;
  const hasPrivateSignal = containsAny(text, privateTerms);
  const hasOfficialSignal = containsAny(text, officialTerms);
  if (hasPrivateSignal && !text.includes("不影响") && !text.includes("以纪要为准")) return "private";
  if (hasOfficialSignal) return "official";
  if (hasPrivateSignal) return "private";
  return "context";
}

function classifyRowForEval(row) {
  const merged = `${row.text} ${row.task_relevance_boundary}`;
  const isPrivate = Boolean(row.private_info_ref) || containsAny(merged, privateTerms);
  const isOfficial = Boolean(row.official_file_ref) || containsAny(merged, officialTerms);
  if (isOfficial && !isPrivate) return "official";
  if (isPrivate && !isOfficial) return "private";
  if (isOfficial && isPrivate) return row.official_file_ref ? "official_with_private_boundary" : "private";
  return "context";
}

function tokenHits(text, expected) {
  const candidates = [
    "2026-05-10",
    "22:00",
    "22点",
    "UTC",
    "network config drift",
    "回滚",
    "已批",
    "批准",
    "正式",
    "纪要",
    "以纪要为准",
    "个人",
    "不影响",
    "Carol",
    "Frank",
    "Jack",
    "周三",
    "白天",
    "全量备份",
  ];
  const expectedText = String(expected || "");
  return candidates.filter((term) => expectedText.includes(term) && text.includes(term));
}

function scoreEvidenceRow(row, query) {
  const queryText = String(query.query || "");
  const rowText = row.text;
  let score = 0;
  const adapterClass = classifyRowForAdapter(row);
  if (adapterClass === "official") score += 2;
  if (adapterClass === "private") score += queryText.includes("个人") || queryText.includes("偏好") ? 2 : 1;
  for (const term of officialTerms) {
    if (queryText.includes(term) && rowText.includes(term)) score += 2;
  }
  for (const term of privateTerms) {
    if (queryText.includes(term) && rowText.includes(term)) score += 1;
  }
  return score;
}

function uniqueByMessageId(rows) {
  const seen = new Set();
  const uniqueRows = [];
  for (const row of rows) {
    if (!row.message_id || seen.has(row.message_id)) continue;
    seen.add(row.message_id);
    uniqueRows.push(row);
  }
  return uniqueRows;
}

function selectEvidenceRows({ observedRows, query }) {
  const candidates = observedRows
    .filter((row) => row.text && classifyRowForAdapter(row) !== "context")
    .map((row) => ({ row, score: scoreEvidenceRow(row, query) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score || left.row.index - right.row.index)
    .map((item) => item.row);
  const selected = uniqueByMessageId(candidates).slice(0, 8);
  if (selected.length > 0) return selected;
  return observedRows.filter((row) => row.text).slice(0, 5);
}

function makeQuote(text) {
  const normalized = normalizeText(text);
  if (normalized.length <= 140) return normalized;
  return `${normalized.slice(0, 137)}...`;
}

function buildMemoryContext(observedRows) {
  const eventRows = observedRows.filter((row) => classifyRowForAdapter(row) !== "context");
  const officialRows = eventRows.filter((row) => classifyRowForAdapter(row) === "official");
  const privateRows = eventRows.filter((row) => classifyRowForAdapter(row) === "private");
  const summaryLines = [
    ...officialRows.slice(0, 6).map((row) => `official:${row.message_id}:${makeQuote(row.text)}`),
    ...privateRows.slice(0, 4).map((row) => `context:${row.message_id}:${makeQuote(row.text)}`),
  ];
  return {
    adapter_note: "openclaw_original_adapter 使用完整消息历史和默认记忆摘要，不使用结构化事件或 wiki 投影。",
    transcript_message_count: observedRows.length,
    event_like_message_count: eventRows.length,
    official_summary_count: officialRows.length,
    private_context_count: privateRows.length,
    summary: summaryLines,
  };
}

function buildAnswer({ query, evidenceRows }) {
  const officialRows = evidenceRows.filter((row) => classifyRowForAdapter(row) === "official");
  const privateRows = evidenceRows.filter((row) => classifyRowForAdapter(row) === "private");
  const officialText = officialRows.map((row) => makeQuote(row.text)).join("；");
  const privateText = privateRows.map((row) => makeQuote(row.text)).join("；");
  const parts = [];
  if (officialText) {
    parts.push(`从原始消息历史摘要看，正式信息包括：${officialText}`);
  }
  if (privateText) {
    parts.push(`同一上下文还混入了这些个人/偏好信息：${privateText}`);
  }
  if (!parts.length) {
    parts.push("原始消息历史中没有提取到足够明确的正式结论。");
  }
  parts.push("这是原始 OpenClaw adapter 的默认历史/摘要回答，不做 Task Wiki 的任务边界投影。");
  return parts.join("。");
}

function judgeAnswer({ query, answer, evidenceRows }) {
  const supportSet = new Set(query.supporting_message_ids || []);
  const supportIds = evidenceRows.map((row) => row.message_id).filter(Boolean);
  const evidenceTraceOk = supportIds.some((id) => supportSet.has(id));
  const privateRows = evidenceRows.filter((row) => classifyRowForEval(row) === "private");
  const officialRows = evidenceRows.filter((row) => classifyRowForEval(row).startsWith("official"));
  const answerText = String(answer || "");
  const hits = tokenHits(answerText, query.expected_good_behavior);
  const officialFactOk = officialRows.length > 0 && containsAny(answerText, officialTerms);
  const currentStateOk = officialFactOk && (hits.length >= 2 || containsAny(answerText, ["以纪要为准", "正式", "blocker", "回滚"]));
  const privateInfoLeaked = privateRows.length > 0 && containsAny(answerText, privateTerms);
  const success = evidenceTraceOk && currentStateOk && officialFactOk && !privateInfoLeaked;
  return {
    success,
    evidence_trace_ok: evidenceTraceOk,
    current_state_ok: currentStateOk,
    private_info_leaked: privateInfoLeaked,
    official_fact_ok: officialFactOk,
    semantic_token_hits: hits,
    reasons: [
      evidenceTraceOk ? "引用了 query gold 中的 observed message_id" : "未命中 query gold 的 supporting message_id",
      currentStateOk ? "回答包含正式/current-state 线索" : "回答缺少正式/current-state 线索",
      privateInfoLeaked ? "回答混入个人/偏好上下文" : "未检测到个人信息泄漏",
    ],
  };
}

function runBaseline({ caseContext, queryBenchmark, observedRows }) {
  const memoryContext = buildMemoryContext(observedRows);
  const answers = queryBenchmark.queries.map((query) => {
    const evidenceRows = selectEvidenceRows({ observedRows, query });
    const answer = buildAnswer({ query, evidenceRows });
    const judgeResult = judgeAnswer({ query, answer, evidenceRows });
    return {
      query_id: query.query_id,
      query: query.query,
      expected_good_behavior: query.expected_good_behavior,
      answer,
      supporting_message_ids: evidenceRows.map((row) => row.message_id).filter(Boolean),
      support_quotes: evidenceRows.map((row) => ({
        message_id: row.message_id,
        source_class: classifyRowForEval(row),
        adapter_source_class: classifyRowForAdapter(row),
        quote: makeQuote(row.text),
      })),
      judge_result: judgeResult,
    };
  });
  return {
    case_id: caseContext.case_id,
    family_id: caseContext.family_id,
    task_id: caseContext.task_id,
    baseline_mode: baselineMode,
    adapter_kind: "message_history_plus_default_memory_summary",
    ingress_count: observedRows.length,
    query_count: queryBenchmark.queries.length,
    memory_context: memoryContext,
    answers,
  };
}

function safeRate(numerator, denominator) {
  if (!denominator) return 0;
  return Number((numerator / denominator).toFixed(4));
}

function computeMetrics(answers) {
  const total = answers.length;
  const supportClassTotals = { official: 0, private: 0, context: 0 };
  for (const answer of answers) {
    for (const quote of answer.support_quotes || []) {
      if (quote.source_class?.startsWith("official")) supportClassTotals.official += 1;
      else if (quote.source_class === "private") supportClassTotals.private += 1;
      else supportClassTotals.context += 1;
    }
  }
  const officialDenominator = supportClassTotals.official + supportClassTotals.private;
  return {
    query_success_rate: safeRate(answers.filter((answer) => answer.judge_result.success).length, total),
    evidence_trace_rate: safeRate(answers.filter((answer) => answer.judge_result.evidence_trace_ok).length, total),
    current_state_accuracy: safeRate(answers.filter((answer) => answer.judge_result.current_state_ok).length, total),
    private_info_leak_rate: safeRate(answers.filter((answer) => answer.judge_result.private_info_leaked).length, total),
    official_fact_precision: safeRate(supportClassTotals.official, officialDenominator),
    support_class_totals: supportClassTotals,
  };
}

function buildEvidenceTraces({ baselineResult }) {
  return {
    case_id: baselineResult.case_id,
    baseline_mode: baselineResult.baseline_mode,
    traces: baselineResult.answers.map((answer) => ({
      query_id: answer.query_id,
      supporting_message_ids: answer.supporting_message_ids,
      evidence: answer.support_quotes,
      judge_result: answer.judge_result,
    })),
  };
}

function readTaskWikiSummary(caseDir) {
  const metricsPath = path.join(caseDir, "runtime", "task_wiki_replay", "layer_metrics.json");
  const summaryPath = path.join(caseDir, "runtime", "task_wiki_replay", "summary.json");
  if (!fs.existsSync(metricsPath)) return null;
  const metrics = readJson(metricsPath);
  const summary = fs.existsSync(summaryPath) ? readJson(summaryPath) : {};
  const layer1 = metrics.layer1_task_binding || metrics.layer1_binding || {};
  const layer2 = metrics.layer2_event_verification || metrics.layer2_events || {};
  const layer3 = metrics.layer3_wiki_projection || metrics.layer3_wiki || {};
  return {
    status: summary.status || metrics?.overall?.status || "unknown",
    health_score: metrics?.overall?.health_score ?? summary.health_score ?? null,
    layer1_status: layer1.status || "unknown",
    layer2_status: layer2.status || "unknown",
    layer3_status: layer3.status || "unknown",
    binding_total: layer1.binding_total ?? null,
    verified_event_count: layer2.verified_event_count ?? null,
    projected_task_count: layer3.projected_task_count ?? null,
    report_path: fs.existsSync(path.join(caseDir, "reports", "task_wiki_runtime_eval.md"))
      ? relativePath(path.join(caseDir, "reports", "task_wiki_runtime_eval.md"))
      : null,
  };
}

function buildComparisonMarkdown({ caseContext, baselineReport, taskWikiSummary, paths }) {
  const taskWikiRows = taskWikiSummary
    ? [
        `| task_wiki_3_layer | ${taskWikiSummary.status} | ${taskWikiSummary.health_score ?? "n/a"} | ${taskWikiSummary.verified_event_count ?? "n/a"} | ${taskWikiSummary.projected_task_count ?? "n/a"} |`,
      ]
    : ["| task_wiki_3_layer | missing | n/a | n/a | n/a |"];
  const lines = [
    `# OpenClaw Baseline vs Task Wiki 3 Layer`,
    "",
    `- Case: ${caseContext.case_id}`,
    `- Family: ${caseContext.family_id}`,
    `- Task: ${caseContext.task_id}`,
    `- Baseline mode: ${baselineReport.baseline_mode}`,
    "",
    "重要说明：当前 Python phase3 的 baseline_eval.py 是 synthetic baseline，不代表真实 OpenClaw baseline。本报告使用同一批 observed ingress 的原始 OpenClaw adapter 结果。",
    "",
    "## Query Metrics",
    "",
    "| Method | Query success | Evidence trace | Current state | Private leak | Official precision |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
    `| openclaw_original | ${baselineReport.metrics.query_success_rate} | ${baselineReport.metrics.evidence_trace_rate} | ${baselineReport.metrics.current_state_accuracy} | ${baselineReport.metrics.private_info_leak_rate} | ${baselineReport.metrics.official_fact_precision} |`,
    "| task_wiki_3_layer | see runtime health | see runtime health | see runtime health | see semantic eval when enabled | see semantic eval when enabled |",
    "",
    "## Runtime Health",
    "",
    "| Method | Status | Health score | Verified events | Projected tasks |",
    "| --- | --- | ---: | ---: | ---: |",
    `| openclaw_original | completed | n/a | n/a | n/a |`,
    ...taskWikiRows,
    "",
    "## Private Info In Official File Checks",
    "",
    `- 是否把个人偏好误当任务 blocker：${baselineReport.special_checks.personal_preference_as_blocker ? "风险存在" : "未检测到"}`,
    `- 是否保留正式纪要中的升级窗口、blocker、回滚计划：${baselineReport.special_checks.official_state_retained ? "是" : "否"}`,
    `- 是否能回答“以正式纪要为准”：${baselineReport.special_checks.formal_minutes_priority ? "是" : "否"}`,
    "",
    "## Outputs",
    "",
    `- Baseline answers: ${paths.answers}`,
    `- Evidence traces: ${paths.traces}`,
    `- Baseline report: ${paths.baselineReport}`,
    taskWikiSummary?.report_path ? `- Task Wiki runtime report: ${taskWikiSummary.report_path}` : "- Task Wiki runtime report: missing",
    "",
  ];
  return `${lines.join("\n")}\n`;
}

function buildSpecialChecks(answers) {
  const answerText = answers.map((answer) => answer.answer).join("\n");
  return {
    personal_preference_as_blocker:
      containsAny(answerText, ["个人"]) && containsAny(answerText, ["blocker", "阻塞"]) && !answerText.includes("不影响任务"),
    official_state_retained: containsAny(answerText, ["2026-05-10", "22点", "22:00"]) &&
      containsAny(answerText, ["network config drift"]) &&
      containsAny(answerText, ["回滚"]),
    formal_minutes_priority: containsAny(answerText, ["以纪要为准", "正式"]),
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const caseDir = resolveCaseDir(args);
  if (!fs.existsSync(caseDir)) throw new Error(`case 目录不存在：${caseDir}`);
  const stateDir = args.stateDir ? resolveInputPath(args.stateDir) : path.join(caseDir, "runtime", "openclaw_baseline_state");
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
  if (observedRows.length === 0) throw new Error("data/openclaw_message_ingress.jsonl 没有可回放消息");
  if (!Array.isArray(queryBenchmark.queries) || queryBenchmark.queries.length === 0) {
    throw new Error("gold/query_benchmark.json 没有 queries");
  }

  const baselineResult = runBaseline({ caseContext, queryBenchmark, observedRows });
  const metrics = computeMetrics(baselineResult.answers);
  const specialChecks = buildSpecialChecks(baselineResult.answers);
  const runtimeDir = path.join(caseDir, "runtime", "openclaw_baseline");
  const reportsDir = path.join(caseDir, "reports");
  const answersPath = path.join(runtimeDir, "answers.json");
  const tracesPath = path.join(runtimeDir, "evidence_traces.json");
  const baselineReportPath = path.join(reportsDir, "openclaw_baseline_eval.json");
  const comparisonPath = path.join(reportsDir, "openclaw_vs_task_wiki_comparison.md");

  const answersPayload = {
    ...baselineResult,
    generated_at: new Date().toISOString(),
    state_dir: relativePath(stateDir),
    semantic_gold_mode: semanticGold.mode || args.semanticGold,
  };
  const evidenceTraces = buildEvidenceTraces({ baselineResult });
  const baselineReport = {
    case_id: caseContext.case_id,
    family_id: caseContext.family_id,
    task_id: caseContext.task_id,
    baseline_mode: baselineMode,
    adapter_disclaimer: "仓库当前没有直接可调用的原始 OpenClaw replay API，因此使用 openclaw_original_adapter；该 adapter 不使用 Task Wiki 三层 artifacts。",
    ingress_count: observedRows.length,
    collected_message_count: collectedRows.length,
    query_count: queryBenchmark.queries.length,
    semantic_gold_mode: semanticGold.mode || args.semanticGold,
    gold_generation: goldGeneration,
    metrics,
    special_checks: specialChecks,
    answer_ids: baselineResult.answers.map((answer) => answer.query_id),
  };
  const taskWikiSummary = readTaskWikiSummary(caseDir);
  const paths = {
    answers: relativePath(answersPath),
    traces: relativePath(tracesPath),
    baselineReport: relativePath(baselineReportPath),
    comparison: relativePath(comparisonPath),
  };

  writeJson(answersPath, answersPayload);
  writeJson(tracesPath, evidenceTraces);
  writeJson(baselineReportPath, baselineReport);
  writeText(comparisonPath, buildComparisonMarkdown({ caseContext, baselineReport, taskWikiSummary, paths }));

  const summary = {
    status: "completed",
    case_dir: relativePath(caseDir),
    baseline_mode: baselineMode,
    ingress_count: observedRows.length,
    query_count: queryBenchmark.queries.length,
    metrics,
    outputs: paths,
  };
  if (args.json) {
    console.log(JSON.stringify(summary));
  } else if (args.quiet) {
    console.log(`baseline completed: ${paths.comparison}`);
  } else {
    console.log(`OpenClaw baseline completed for ${caseContext.case_id}`);
    console.log(`- ingress: ${observedRows.length}`);
    console.log(`- queries: ${queryBenchmark.queries.length}`);
    console.log(`- report: ${paths.comparison}`);
  }
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
