"use strict";

const crypto = require("node:crypto");
const { requestJson, buildClientFromEnv } = require("./llm-client.js");

const EVENT_FIELD_REQUIREMENTS = {
  conclusion_event: ["conclusion", "target"],
  rationale_event: ["reason"],
  objection_event: ["objection", "objector", "target"],
  constraint_event: ["constraint", "target"],
  commitment_event: ["owner", "action"],
  status_event: ["status", "target"],
  time_event: ["time_target", "time_value", "certainty"],
  scope_event: ["scope_target"],
};

const ALLOWED_EVENT_TYPES = new Set(Object.keys(EVENT_FIELD_REQUIREMENTS));

function normalizeText(input) {
  return String(input ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

function splitIntoClauses(text) {
  return normalizeText(text)
    .split(/[。\n；;！？!?]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function createEventId(parts) {
  return `evt_${crypto.createHash("sha1").update(parts.join("|")).digest("hex").slice(0, 16)}`;
}

function cloneContextQuotes(contextEntries) {
  return contextEntries.map((entry) => ({
    entry_id: entry.entry_id,
    quote: entry.text,
    role: "disambiguation",
  }));
}

function buildBaseEvent(params) {
  const participants = [];
  if (params.entry?.sender_name) {
    participants.push(params.entry.sender_name);
  } else if (params.entry?.sender_id) {
    participants.push(params.entry.sender_id);
  }
  return {
    event_id: "",
    task_ref: params.task.taskKey,
    source_session_id: params.sourceSessionId,
    ingest_version: params.ingestVersion,
    event_type: "",
    claim: params.clause,
    core_entry_id: params.entry.entry_id,
    evidence_quote: params.clause,
    context_quotes: params.contextQuotes,
    participants,
    event_time: params.entry.create_time ?? new Date().toISOString(),
    source: {
      source_type: params.sourceType,
      source_id: params.sourceId,
      chat_id: params.chatId ?? null,
      thread_id: params.threadId ?? null,
      root_id: params.rootId ?? null,
      locator: params.sourceLocator ?? null,
    },
    confidence: 0.72,
    verification: {
      core_quote_found: false,
      claim_supported_by_quote: false,
      context_only_generation: false,
      single_atomic_claim: false,
      required_fields_complete: false,
      no_unsupported_inference: false,
      verdict: "candidate",
    },
  };
}

function makeEvent(params) {
  const event = {
    ...buildBaseEvent(params),
    ...params.extra,
    event_type: params.eventType,
  };
  event.event_id = createEventId([
    event.task_ref,
    event.source_session_id,
    String(event.ingest_version),
    event.event_type,
    event.core_entry_id,
    event.claim,
  ]);
  return event;
}

function extractTimeValue(clause) {
  const match =
    clause.match(/(\d{1,2}\s*月\s*\d{1,2}\s*日)/u)
    ?? clause.match(/(今天|明天|后天|本周|下周|周[一二三四五六日天]|月底)/u);
  return match?.[1] ?? null;
}

function extractCertainty(clause) {
  if (/暂定|先看|预计|先按/u.test(clause)) {
    return "暂定";
  }
  if (/确认|确定|锁定|定了/u.test(clause)) {
    return "确认";
  }
  if (/顺延|延期|延后/u.test(clause)) {
    return "顺延";
  }
  if (/不确定|待定|还没定/u.test(clause)) {
    return "不确定";
  }
  return "已提及";
}

function extractTargetHint(clause) {
  const explicitPatterns = [
    /((?:发布时间|发布日期|上线日期|上线时间|发布时间口径|对外口径))/u,
    /((?:迁移窗口风险|迁移窗口|风险))/u,
    /((?:范围|MVP 范围|影响范围))/u,
    /((?:目标日期|目标发布时间|目标时间|目标))/u,
  ];
  for (const pattern of explicitPatterns) {
    const match = clause.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }
  return null;
}

function extractObjectorHint(clause) {
  const subjectMatch = clause.match(/^([^，。；;]{1,20}?)(?:担心|反对|不同意|认为|提醒)/u);
  if (subjectMatch?.[1]) {
    return subjectMatch[1].trim();
  }
  return null;
}

function extractOwnerHint(clause) {
  const ownerMatch = clause.match(/([^，。；;]{1,16}?)(?:来|负责|会|跟进|推进)/u);
  return ownerMatch?.[1]?.trim() ?? null;
}

function extractTimeTargetHint(clause) {
  const explicitTarget = extractTargetHint(clause);
  if (explicitTarget) {
    return explicitTarget;
  }
  if (extractTimeValue(clause) && /目标/u.test(clause)) {
    const match = clause.match(/(目标(?:日期|发布时间|时间)?)/u);
    return match?.[1] ?? "目标";
  }
  return null;
}

function extractHeuristicFromClause(params) {
  const clause = params.clause;
  const events = [];
  const contextQuotes = cloneContextQuotes(params.contextEntries);
  const targetHint = extractTargetHint(clause);
  const objectorHint = extractObjectorHint(clause);
  const ownerHint = extractOwnerHint(clause);
  const timeTargetHint = extractTimeTargetHint(clause);

  if (targetHint && /先按|就按|结论|决定|统一.*口径|暂定|采用|确认为|先看/u.test(clause)) {
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "conclusion_event",
        extra: {
          conclusion: clause,
          target: targetHint,
        },
      }),
    );
  }

  if (/因为|原因是|主要是|由于/u.test(clause)) {
    const reason = clause.split(/因为|原因是|主要是|由于/u).slice(1).join("").trim() || clause;
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "rationale_event",
        extra: { reason },
      }),
    );
  }

  if (targetHint && objectorHint && /担心|不同意|反对|风险|问题是/u.test(clause)) {
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "objection_event",
        extra: {
          objection: clause,
          target: targetHint,
          objector: objectorHint,
        },
      }),
    );
  }

  if (targetHint && /不能|不允许|必须|只做|不做|禁止|先不支持|不要/u.test(clause)) {
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "constraint_event",
        extra: {
          constraint: clause,
          target: targetHint,
        },
      }),
    );
  }

  if (ownerHint && /我来|我负责|我会|今天会|明天会|负责|跟进|推进/u.test(clause)) {
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "commitment_event",
        extra: {
          owner: ownerHint,
          action: clause,
        },
      }),
    );
  }

  if (targetHint && /已经|已|还没|尚未|未|完成|卡住|阻塞|已完成|未完成/u.test(clause)) {
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "status_event",
        extra: {
          status: clause,
          target: targetHint,
        },
      }),
    );
  }

  const timeValue = extractTimeValue(clause);
  if (timeValue && timeTargetHint) {
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "time_event",
        extra: {
          time_target: timeTargetHint,
          time_value: timeValue,
          certainty: extractCertainty(clause),
        },
      }),
    );
  }

  if (targetHint && /本期只|只适用于|先在|MVP|范围|不包括|仅限于|阶段/u.test(clause)) {
    const included = clause.match(/只做([^，不。；;]+)/u)?.[1]?.trim();
    const excluded = clause.match(/不做([^，不。；;]+)/u)?.[1]?.trim();
    events.push(
      makeEvent({
        ...params,
        contextQuotes,
        eventType: "scope_event",
        extra: {
          scope_target: targetHint,
          included: included ? [included] : [],
          excluded: excluded ? [excluded] : [],
        },
      }),
    );
  }

  return events;
}

function extractCandidateEventsHeuristic(params) {
  const events = [];
  for (const entry of params.coreEntries) {
    for (const clause of splitIntoClauses(entry.text)) {
      events.push(
        ...extractHeuristicFromClause({
          task: params.task,
          sourceSessionId: params.sourceSessionId,
          ingestVersion: params.ingestVersion,
          entry,
          clause,
          contextEntries: params.contextEntries,
          sourceType: params.sourceType,
          sourceId: params.sourceId,
          chatId: params.chatId,
          threadId: params.threadId,
          rootId: params.rootId,
          sourceLocator: params.sourceLocator,
        }),
      );
    }
  }
  return dedupeEvents(events);
}

function dedupeEvents(events) {
  const seen = new Set();
  const result = [];
  for (const event of events) {
    const key = [
      event.event_type,
      event.core_entry_id,
      normalizeText(event.claim),
      normalizeText(event.evidence_quote),
    ].join("|");
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(event);
  }
  return result;
}

function ensureEventId(event) {
  if (event.event_id && typeof event.event_id === "string") {
    return event;
  }
  const normalized = {
    ...event,
  };
  normalized.event_id = createEventId([
    normalized.task_ref,
    normalized.source_session_id,
    String(normalized.ingest_version),
    normalized.event_type,
    normalized.core_entry_id,
    normalized.claim,
  ]);
  return normalized;
}

function normalizeCandidateEvent(raw, params) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const eventType = String(raw.event_type ?? "").trim();
  if (!ALLOWED_EVENT_TYPES.has(eventType)) {
    return null;
  }
  const normalized = {
    ...buildBaseEvent({
      task: params.task,
      sourceSessionId: params.sourceSessionId,
      ingestVersion: params.ingestVersion,
      entry: params.coreEntries.find((entry) => entry.entry_id === raw.core_entry_id) ?? params.coreEntries[0],
      clause: String(raw.claim ?? raw.evidence_quote ?? "").trim(),
      contextQuotes: Array.isArray(raw.context_quotes)
        ? raw.context_quotes
            .filter((item) => item && typeof item === "object")
            .map((item) => ({
              entry_id: item.entry_id ?? null,
              quote: String(item.quote ?? ""),
              role: item.role ?? "disambiguation",
            }))
        : [],
      sourceType: params.sourceType,
      sourceId: params.sourceId,
      chatId: params.chatId,
      threadId: params.threadId,
      rootId: params.rootId,
      sourceLocator: params.sourceLocator,
    }),
    ...raw,
    event_type: eventType,
    task_ref: params.task.taskKey,
    source_session_id: params.sourceSessionId,
    ingest_version: params.ingestVersion,
    participants: Array.isArray(raw.participants)
      ? raw.participants.map((item) => String(item))
      : [],
    context_quotes: Array.isArray(raw.context_quotes)
      ? raw.context_quotes.filter((item) => item && typeof item === "object").map((item) => ({
          entry_id: item.entry_id ?? null,
          quote: String(item.quote ?? ""),
          role: item.role ?? "disambiguation",
        }))
      : [],
  };
  return ensureEventId(normalized);
}

function buildExtractionPrompts(params) {
  return {
    systemPrompt: [
      "你是飞书 Task Wiki 第二层的事件抽取器。",
      "你的任务是从 TRIGGER 中抽取最小 typed candidate_event。",
      "TRIGGER 负责触发 event，SUPPORT 和 CONTEXT 只允许做指代消歧，不能作为独立证据。",
      "不要使用 current_state_context。",
      "只允许输出一个 JSON object，格式为 {\"events\":[...]}。",
      "event_type 只能是：conclusion_event, rationale_event, objection_event, constraint_event, commitment_event, status_event, time_event, scope_event。",
      "每条 event 必须包含：event_type, claim, core_entry_id, evidence_quote。",
      "不得补全原文没有说的 owner、deadline、target、强度。",
      "如果无法确定，就不要生成该 event。",
    ].join("\n"),
    userPrompt: JSON.stringify(
      {
        task: {
          task_id: params.task.taskId,
          task_key: params.task.taskKey,
          task_title: params.task.taskTitle,
        },
        source_session_id: params.sourceSessionId,
        ingest_version: params.ingestVersion,
        trigger_entries: params.coreEntries,
        support_entries: params.supportEntries ?? [],
        context_entries: params.contextEntries,
      },
      null,
      2,
    ),
  };
}

async function extractCandidateEventsWithLLM(params) {
  if (!buildClientFromEnv()) {
    return extractCandidateEventsHeuristic(params);
  }
  try {
    const prompts = buildExtractionPrompts(params);
    const result = await requestJson({
      systemPrompt: prompts.systemPrompt,
      userPrompt: prompts.userPrompt,
      temperature: 0.1,
      maxTokens: 2200,
    });
    if (!Array.isArray(result?.events)) {
      throw new Error("Invalid LLM extractor response: events must be an array");
    }
    const rawEvents = result.events;
    const normalized = rawEvents
      .map((event) => normalizeCandidateEvent(event, params))
      .filter(Boolean);
    return dedupeEvents(normalized);
  } catch {
    return extractCandidateEventsHeuristic(params);
  }
}

function verifyLocation(event, coreEntries) {
  const entry = coreEntries.find((item) => item.entry_id === event.core_entry_id);
  if (!entry) {
    return { ok: false, quoteMatchType: "missing_entry" };
  }
  const normalizedEntry = normalizeText(entry.text);
  const normalizedQuote = normalizeText(event.evidence_quote);
  return {
    ok: Boolean(normalizedQuote) && normalizedEntry.includes(normalizedQuote),
    quoteMatchType: normalizedEntry.includes(normalizedQuote) ? "exact" : "missing_quote",
  };
}

function verifySchema(event) {
  if (!ALLOWED_EVENT_TYPES.has(event.event_type)) {
    return false;
  }
  const required = EVENT_FIELD_REQUIREMENTS[event.event_type] ?? [];
  if (!normalizeText(event.claim) || !normalizeText(event.evidence_quote) || !normalizeText(event.core_entry_id)) {
    return false;
  }
  return required.every((field) => {
    const value = event[field];
    if (Array.isArray(value)) {
      return value.length > 0;
    }
    return typeof value === "string" ? Boolean(value.trim()) : value != null;
  });
}

function verifyAtomicity(event) {
  const quote = normalizeText(event.evidence_quote);
  if (!quote) {
    return false;
  }
  const facts = quote.split(/，并且|，同时|，然后|并且|同时|然后/u).filter(Boolean);
  return facts.length <= 2;
}

function validateCandidateEvent(event, coreEntries) {
  const location = verifyLocation(event, coreEntries);
  const requiredFieldsComplete = verifySchema(event);
  const singleAtomicClaim = verifyAtomicity(event);
  const validationVerdict =
    location.ok && requiredFieldsComplete && singleAtomicClaim
      ? "ready_for_verification"
      : location.ok && requiredFieldsComplete
        ? "needs_review"
        : "rejected";
  return {
    ...ensureEventId(event),
    verification: {
      ...(event.verification ?? {}),
      core_quote_found: location.ok,
      claim_supported_by_quote: false,
      context_only_generation: false,
      single_atomic_claim: singleAtomicClaim,
      required_fields_complete: requiredFieldsComplete,
      no_unsupported_inference: false,
      verdict: validationVerdict === "rejected" ? "rejected" : "candidate",
      resolved_core_entry_id: location.ok ? event.core_entry_id : null,
      quote_match_type: location.quoteMatchType,
    },
    programmatic_validation: {
      verdict: validationVerdict,
      evidence_quote_in_core: location.ok,
      required_fields_complete: requiredFieldsComplete,
      single_atomic_claim: singleAtomicClaim,
    },
  };
}

function fieldSupportedOutsideQuote(field, normalizedValue, supportEntries, contextEntries) {
  if (!normalizedValue) {
    return false;
  }
  const SUPPORTABLE_FIELDS = new Set(["target", "time_target", "scope_target"]);
  if (!SUPPORTABLE_FIELDS.has(field)) {
    return false;
  }
  const pools = [...(supportEntries ?? []), ...(contextEntries ?? [])];
  return pools.some((entry) => normalizeText(entry?.text ?? "").includes(normalizedValue));
}

function verifyClaimSupportHeuristic(event, supportEntries, contextEntries) {
  const quote = normalizeText(event.evidence_quote);
  if (!quote) {
    return { supported: false, unsupportedParts: ["evidence_quote"], reason: "evidence_quote 为空" };
  }
  const unsupportedParts = [];
  for (const field of EVENT_FIELD_REQUIREMENTS[event.event_type] ?? []) {
    const value = event[field];
    if (typeof value === "string") {
      const normalized = normalizeText(value);
      if (
        normalized
        && !quote.includes(normalized)
        && !normalizeText(event.claim).includes(normalized)
        && !fieldSupportedOutsideQuote(field, normalized, supportEntries, contextEntries)
      ) {
        unsupportedParts.push(field);
      }
    }
    if (Array.isArray(value) && value.length > 0) {
      const missing = value.some((item) => {
        const normalized = normalizeText(item);
        return (
          normalized
          && !quote.includes(normalized)
          && !normalizeText(event.claim).includes(normalized)
          && !fieldSupportedOutsideQuote(field, normalized, supportEntries, contextEntries)
        );
      });
      if (missing) {
        unsupportedParts.push(field);
      }
    }
  }
  return {
    supported: unsupportedParts.length === 0,
    unsupportedParts,
    reason: unsupportedParts.length === 0 ? "" : `unsupported fields: ${unsupportedParts.join(", ")}`,
  };
}

function buildVerifierPrompts(params) {
  return {
    systemPrompt: [
      "你是飞书 Task Wiki 第二层 verifier。",
      "你不会重新抽取事件，只会判断给定 candidate_event 是否足以成为 verified session_event。",
      "输入只包括 core_entries、context_entries 和 candidate_event。",
      "context 只能用于消歧，不能作为独立证据。",
      "不能使用 runtime task 或说话人默认补齐字段。",
      "如果字段不被 evidence_quote 或允许的 context 直接支撑，不能判 verified。",
      "只允许输出一个 JSON object，格式为 {\"verdict\":\"verified|needs_review|rejected\",\"claim_supported\":true|false,\"unsupported_parts\":[],\"reason\":\"...\"}。",
    ].join("\n"),
    userPrompt: JSON.stringify(
      {
        trigger_entries: params.coreEntries,
        support_entries: params.supportEntries ?? [],
        context_entries: params.contextEntries,
        candidate_event: params.candidateEvent,
      },
      null,
      2,
    ),
  };
}

async function verifyCandidateEventWithLLM(params) {
  if (!buildClientFromEnv()) {
    return null;
  }
  const prompts = buildVerifierPrompts(params);
  const result = await requestJson({
    systemPrompt: prompts.systemPrompt,
    userPrompt: prompts.userPrompt,
    temperature: 0,
    maxTokens: 1200,
  });
  const verdict = String(result?.verdict ?? "").trim();
  if (!verdict) {
    return null;
  }
  return {
    verdict,
    claim_supported: Boolean(result?.claim_supported),
    unsupported_parts: Array.isArray(result?.unsupported_parts) ? result.unsupported_parts.map((item) => String(item)) : [],
    reason: String(result?.reason ?? ""),
  };
}

async function verifyCandidateEvent(params) {
  const event = params.candidateEvent;
  const validation = event.programmatic_validation ?? validateCandidateEvent(event, params.coreEntries).programmatic_validation;
  if (validation.verdict === "rejected") {
    return {
      ...event,
      verification: {
        ...(event.verification ?? {}),
        verdict: "rejected",
        claim_supported_by_quote: false,
        no_unsupported_inference: false,
      },
    };
  }

  const llmResult = await verifyCandidateEventWithLLM(params).catch(() => null);
  const heuristicSupport = verifyClaimSupportHeuristic(event, params.supportEntries, params.contextEntries);
  const claimSupportedByQuote = llmResult ? Boolean(llmResult.claim_supported) : heuristicSupport.supported;
  const unsupportedParts = llmResult?.unsupported_parts?.length
    ? llmResult.unsupported_parts
    : heuristicSupport.unsupportedParts;
  const verifierVerdict = llmResult?.verdict || (heuristicSupport.supported ? "verified" : "needs_review");
  const finalVerdict =
    validation.verdict === "needs_review"
      ? "needs_review"
      : verifierVerdict === "verified" && claimSupportedByQuote
        ? "verified"
        : verifierVerdict === "rejected"
          ? "rejected"
          : "needs_review";

  return {
    ...event,
    verification: {
      ...(event.verification ?? {}),
      claim_supported_by_quote: claimSupportedByQuote,
      no_unsupported_inference: claimSupportedByQuote,
      unsupported_parts: unsupportedParts,
      verifier_reason: llmResult?.reason ?? heuristicSupport.reason,
      verdict: finalVerdict,
    },
  };
}

function extractCandidateEvents(params) {
  return extractCandidateEventsHeuristic(params);
}

module.exports = {
  extractCandidateEvents,
  extractCandidateEventsHeuristic,
  extractCandidateEventsWithLLM,
  validateCandidateEvent,
  verifyCandidateEvent,
};
