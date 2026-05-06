"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const YAML = require("yaml");
const { buildClientFromEnv, requestJson } = require("../task-events/llm-client.js");
const {
  readJsonFile,
  readJsonl,
  writeJson,
  ensureDir,
  sortByEventTimeDescending,
  getSessionWikiPaths,
  getTaskRootFromSessionDir,
  getTaskRootPaths,
  relativeSessionWikiPath,
  readLifecycleOverlay,
  resolveEventLifecycle,
  appendTaskLog,
} = require("./shared.js");

const SLOT_ORDER = [
  "conclusion",
  "rationale",
  "objection",
  "constraint",
  "commitment",
  "status",
  "time",
  "scope",
];

const SLOT_HEADINGS = {
  conclusion: "Conclusion",
  rationale: "Rationale",
  objection: "Objection / Risk",
  constraint: "Constraint",
  commitment: "Commitment",
  status: "Status",
  time: "Time",
  scope: "Scope",
};

const EVENT_SLOT = {
  conclusion_event: "conclusion",
  rationale_event: "rationale",
  objection_event: "objection",
  constraint_event: "constraint",
  commitment_event: "commitment",
  status_event: "status",
  time_event: "time",
  scope_event: "scope",
};

const EVENT_TYPE_LABEL = {
  conclusion_event: "结论",
  rationale_event: "理由",
  objection_event: "异议",
  constraint_event: "约束",
  commitment_event: "承诺",
  status_event: "状态",
  time_event: "时间",
  scope_event: "范围",
};

const TOPIC_ROUTE_ORDER = ["发布时间", "风险", "行动项", "约束", "时间线", "范围", "状态", "决策"];

function normalizeText(input) {
  return String(input ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeKey(input) {
  return normalizeText(input).toLowerCase();
}

function slugify(input) {
  const normalized = String(input ?? "")
    .replace(/^task:/u, "")
    .replace(/[^A-Za-z0-9._\u4e00-\u9fff-]+/gu, "_")
    .replace(/^_+|_+$/gu, "")
    .slice(0, 64);
  const digest = crypto
    .createHash("sha1")
    .update(String(input ?? ""))
    .digest("hex")
    .slice(0, 8);
  return `${normalized || "item"}-${digest}`;
}

function renderLink(label, target) {
  return `[[${target}|${label}]]`;
}

function buildMarker(key, phase) {
  return `<!-- ${key}:${phase} -->`;
}

function renderMarkedSection(key, bodyLines) {
  return [buildMarker(key, "start"), ...bodyLines, buildMarker(key, "end")].join("\n");
}

function replaceMarkedSection(content, key, nextSection) {
  const startMarker = buildMarker(key, "start");
  const endMarker = buildMarker(key, "end");
  const startIndex = content.indexOf(startMarker);
  const endIndex = content.indexOf(endMarker);
  if (startIndex < 0 || endIndex < 0 || endIndex < startIndex) {
    return null;
  }
  const afterEnd = endIndex + endMarker.length;
  return `${content.slice(0, startIndex)}${nextSection}${content.slice(afterEnd)}`;
}

function removeMarkedSection(content, key) {
  return replaceMarkedSection(content, key, "");
}

function inferSemanticTopicSeed(event) {
  const joined = normalizeText(
    [
      event?.target,
      event?.time_target,
      event?.scope_target,
      event?.action,
      event?.claim,
      event?.evidence_quote,
    ]
      .filter(Boolean)
      .join(" "),
  );
  if (!joined) {
    return "";
  }
  if (/销售|客户|承诺/u.test(joined)) {
    return "销售承诺风险";
  }
  if (/迁移窗口|回滚脚本|checklist|灰度|blocker|阻塞|风险/u.test(joined)) {
    return "发布阻塞风险";
  }
  if (/发布时间|发布日期|上线|发版|5 月 [0-9]+ 日|5月[0-9]+日/u.test(joined)) {
    return "发布时间口径";
  }
  if (/接口文档|文档同步|文档|wiki|知识库/u.test(joined) && /我会|同步|补齐|更新/u.test(joined)) {
    return "文档同步行动项";
  }
  if (/范围|裁剪|scope/u.test(joined)) {
    return "方案范围裁剪";
  }
  return "";
}

function extractEventSubject(event) {
  const semanticSeed = inferSemanticTopicSeed(event);
  if (semanticSeed) {
    return semanticSeed;
  }
  switch (event?.event_type) {
    case "time_event":
      return normalizeText(event?.time_target ?? "");
    case "scope_event":
      return normalizeText(event?.scope_target ?? "");
    case "commitment_event":
      return normalizeText(event?.action ?? "");
    case "conclusion_event":
    case "rationale_event":
    case "objection_event":
    case "constraint_event":
    case "status_event":
      return normalizeText(event?.target ?? "");
    default:
      return "";
  }
}

function extractEventCoarseKey(event) {
  const subject = extractEventSubject(event);
  if (subject) {
    return normalizeKey(subject);
  }
  const slot = EVENT_SLOT[event?.event_type] ?? "status";
  return `${slot}:${event?.event_type ?? "event"}:${event?.core_entry_id ?? event?.event_id ?? "entry"}`;
}

function fallbackTopicTitleForEvent(event) {
  const semanticSeed = inferSemanticTopicSeed(event);
  if (semanticSeed) {
    return semanticSeed;
  }
  const subject = extractEventSubject(event);
  if (subject) {
    return subject;
  }
  return EVENT_TYPE_LABEL[event?.event_type] ?? "协作事项";
}

async function assignTopicsWithLLM(params) {
  const fallbackAssignments = params.events.map((event) => ({
    event_id: event.event_id,
    topic_key: extractEventCoarseKey(event),
    topic_title: fallbackTopicTitleForEvent(event),
  }));
  if (!buildClientFromEnv()) {
    return fallbackAssignments;
  }
  const previousAssignments =
    params.previousState?.block_order
      ?.map((blockId) => params.previousState.blocks?.[blockId])
      ?.filter(Boolean)
      ?.flatMap((block) =>
        (block.event_ids ?? []).map((eventId) => ({
          event_id: eventId,
          topic_key: block.topic_key,
          topic_title: block.topic_title,
        })),
      ) ?? [];
  try {
    const result = await requestJson({
      systemPrompt: [
        "You are normalizing verified task-wiki events into Memory Block topics.",
        "Return one JSON object only.",
        "Do not change event facts, do not invent new facts, and do not drop events.",
        "You may only assign each event into a short Chinese topic_key/topic_title so semantically equivalent events share the same topic.",
        "Prefer stable Chinese topic titles such as 发布时间口径, 销售承诺风险, 接口文档行动项, 方案范围裁剪.",
      ].join("\n"),
      userPrompt: JSON.stringify({
        task: {
          task_id: params.taskId,
          task_key: params.taskKey,
        },
        previous_assignments: previousAssignments,
        events: params.events.map((event) => ({
          event_id: event.event_id,
          event_type: event.event_type,
          coarse_key: extractEventCoarseKey(event),
          suggested_topic_title: fallbackTopicTitleForEvent(event),
          claim: event.claim,
          key_field:
            event.target ?? event.time_target ?? event.scope_target ?? event.action ?? null,
          evidence_quote: event.evidence_quote,
        })),
        output_schema: {
          assignments: [
            {
              event_id: "string",
              topic_key: "short Chinese topic key",
              topic_title: "short Chinese topic title",
            },
          ],
        },
      }),
      temperature: 0.1,
      maxTokens: 1200,
    });
    const assignments = Array.isArray(result?.assignments) ? result.assignments : [];
    const assignmentMap = new Map();
    for (const assignment of assignments) {
      if (!assignment?.event_id) {
        continue;
      }
      const topicKey = normalizeText(assignment.topic_key);
      const topicTitle = normalizeText(assignment.topic_title);
      if (!topicKey || !topicTitle) {
        continue;
      }
      assignmentMap.set(String(assignment.event_id), {
        event_id: String(assignment.event_id),
        topic_key: topicKey,
        topic_title: topicTitle,
      });
    }
    return params.events.map((event) => {
      const assigned = assignmentMap.get(String(event.event_id));
      if (assigned) {
        return assigned;
      }
      return {
        event_id: event.event_id,
        topic_key: extractEventCoarseKey(event),
        topic_title: fallbackTopicTitleForEvent(event),
      };
    });
  } catch {
    return fallbackAssignments;
  }
}

function buildSlotItems(events, pagePath) {
  const itemsBySlot = Object.fromEntries(SLOT_ORDER.map((slot) => [slot, []]));
  const newestBySubject = new Map();
  const sessionEventsPath = pagePath.replace(/session_wiki\.md$/u, "session_events.jsonl");
  const sessionMarkdownPath = pagePath.replace(/session_wiki\.md$/u, "session.md");
  for (const event of sortByEventTimeDescending(events)) {
    const slot = EVENT_SLOT[event.event_type];
    if (!slot) {
      continue;
    }
    const lifecycle = event.lifecycle ?? { lifecycle_status: "active", lifecycle_reason: null };
    const subjectKey = normalizeKey(extractEventSubject(event) || event.claim || event.event_id);
    const currentKey = `${slot}|${subjectKey}`;
    const isCurrent = lifecycle.lifecycle_status === "active" && !newestBySubject.has(currentKey);
    if (isCurrent) {
      newestBySubject.set(currentKey, event.event_id);
    }
    itemsBySlot[slot].push({
      event_id: event.event_id,
      event_type: event.event_type,
      claim: event.claim,
      event_time: event.event_time,
      evidence_quote: event.evidence_quote,
      event_path: `${sessionEventsPath}#${event.event_id}`,
      event_ref: renderLink(String(event.event_id), `${sessionEventsPath}#${event.event_id}`),
      entry_ref: event.core_entry_id
        ? renderLink(String(event.core_entry_id), `${sessionMarkdownPath}#${event.core_entry_id}`)
        : null,
      core_entry_id: event.core_entry_id ?? null,
      subject_key: subjectKey,
      is_current: isCurrent,
      lifecycle_status: lifecycle.lifecycle_status,
      lifecycle_reason: lifecycle.lifecycle_reason,
      target: event.target ?? null,
      time_target: event.time_target ?? null,
      scope_target: event.scope_target ?? null,
      action: event.action ?? null,
      owner: event.owner ?? null,
      objector: event.objector ?? null,
      status: event.status ?? null,
      certainty: event.certainty ?? null,
    });
  }
  return itemsBySlot;
}

function routePriority(route) {
  const index = TOPIC_ROUTE_ORDER.indexOf(route);
  return index >= 0 ? index : TOPIC_ROUTE_ORDER.length + 1;
}

function inferTopicRoute(block) {
  const topicTitle = normalizeText(block?.topic_title ?? "");
  const topicKey = normalizeText(block?.topic_key ?? "");
  const slots = new Set(block?.slots ?? []);
  const searchable = `${topicTitle} ${topicKey}`;
  if (slots.has("objection") || /风险|异议|担心|阻塞|blocker/u.test(searchable)) {
    return "风险";
  }
  if (/发布|上线|日期|时间|排期|里程碑/u.test(searchable)) {
    return "发布时间";
  }
  if (slots.has("commitment") || /行动|待办|接口文档|跟进|落实/u.test(searchable)) {
    return "行动项";
  }
  if (slots.has("constraint") || /约束|口径|禁止|边界|规则/u.test(searchable)) {
    return "约束";
  }
  if (slots.has("time") || /时间|窗口|timeline|截止/u.test(searchable)) {
    return "时间线";
  }
  if (slots.has("scope") || /范围|scope|裁剪/u.test(searchable)) {
    return "范围";
  }
  if (slots.has("status") || /状态|进度|灰度/u.test(searchable)) {
    return "状态";
  }
  return "决策";
}

function inferBlockStatus(slots) {
  const slotItems = SLOT_ORDER.flatMap((slot) => slots[slot] ?? []);
  const activeItems = slotItems.filter((item) => item.lifecycle_status === "active");
  const historicalItems = slotItems.filter((item) => item.lifecycle_status === "historical");
  const invalidItems = slotItems.filter((item) => item.lifecycle_status === "invalid");
  if (activeItems.length === 0 && historicalItems.length === 0 && invalidItems.length > 0) {
    return invalidItems.some((item) => item.lifecycle_reason === "source_revoked")
      ? "archived"
      : "invalidated";
  }
  if (activeItems.length === 0 && historicalItems.length > 0) {
    return "historical";
  }
  const currentStatusItems = slots.status.filter((item) => item.is_current);
  const currentObjections = slots.objection.filter((item) => item.is_current);
  const currentConstraints = slots.constraint.filter((item) => item.is_current);
  if (
    currentStatusItems.some((item) => /完成|已完成|关闭|解决/u.test(item.claim)) &&
    currentObjections.length === 0
  ) {
    return "resolved";
  }
  if (
    currentObjections.length > 0 ||
    currentConstraints.length > 0 ||
    currentStatusItems.some((item) => /未|尚未|卡住|阻塞|风险/u.test(item.claim))
  ) {
    return "open";
  }
  return "active";
}

function uniqueStrings(values) {
  const seen = new Set();
  const output = [];
  for (const value of values) {
    const normalized = normalizeText(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

function uniqueNormalized(items) {
  const seen = new Set();
  const output = [];
  for (const item of items) {
    const normalized = normalizeText(item);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

function fallbackSummary(kind, params) {
  if (kind === "block") {
    const currentClaims = uniqueNormalized(
      SLOT_ORDER.flatMap((slot) =>
        params.slots[slot].filter((item) => item.is_current).map((item) => item.claim),
      ),
    );
    if (currentClaims.length > 0) {
      return currentClaims.slice(0, 2).join("；");
    }
    return `该记忆块当前围绕${params.topicTitle}展开。`;
  }
  if (kind === "session") {
    const topicTitles = uniqueNormalized(
      params.blocks.map((block) => block.topic_title).filter(Boolean),
    );
    if (topicTitles.length > 0) {
      return `这次讨论主要涉及：${topicTitles.slice(0, 4).join("、")}。`;
    }
    return "本次 session 暂无已验证的结构化记忆块。";
  }
  if (kind === "task") {
    const topicTitles = uniqueNormalized(
      params.blocks.map((block) => block.topic_title).filter(Boolean),
    );
    if (topicTitles.length > 0) {
      return `当前任务重点集中在：${topicTitles.slice(0, 5).join("、")}。`;
    }
    return `当前任务 ${params.taskKey} 暂无可汇总的已验证当前状态。`;
  }
  return "暂无摘要。";
}

async function requestSummary(kind, params) {
  if (!buildClientFromEnv()) {
    return fallbackSummary(kind, params);
  }
  try {
    const result = await requestJson({
      systemPrompt: [
        "You generate short Chinese summaries for Feishu Task Wiki pages.",
        "Return one JSON object only.",
        "Do not invent new facts and do not mention anything not grounded in the provided verified events.",
      ].join("\n"),
      userPrompt: JSON.stringify({
        kind,
        payload: params.payload,
        output_schema: {
          summary: "short Chinese summary",
        },
      }),
      temperature: 0.1,
      maxTokens: 300,
    });
    const summary = normalizeText(result?.summary);
    if (summary) {
      return summary;
    }
  } catch {
    // Fall back below.
  }
  return fallbackSummary(kind, params.fallback);
}

function blockSignature(block) {
  return JSON.stringify({
    topic_key: block.topic_key,
    topic_title: block.topic_title,
    event_ids: block.event_ids,
    slots: Object.fromEntries(
      SLOT_ORDER.map((slot) => [
        slot,
        block.slots[slot].map((item) => ({
          event_id: item.event_id,
          is_current: item.is_current,
        })),
      ]),
    ),
  });
}

function renderSlotItemMarkdown(item) {
  let prefix = "[历史]";
  if (item.lifecycle_status === "invalid") {
    prefix = item.lifecycle_reason === "source_revoked" ? "[来源失效]" : "[失效]";
  } else if (item.is_current) {
    prefix = "[当前]";
  }
  const lines = [`- ${prefix} ${item.claim}`, `  - Event Ref: ${item.event_ref}`];
  if (item.entry_ref) {
    lines.push(`  - Entry Ref: ${item.entry_ref}`);
  }
  lines.push(`  - Quote: ${item.evidence_quote}`);
  return lines.join("\n");
}

function renderSlotItemList(items) {
  if (!items.length) {
    return "- 无";
  }
  return items.map((item) => renderSlotItemMarkdown(item)).join("\n");
}

function renderSlotMarkdown(slotItems) {
  if (!slotItems.length) {
    return "- 无";
  }
  const currentItems = slotItems.filter((item) => item.is_current);
  const historyItems = slotItems.filter((item) => !item.is_current);
  const lines = ["##### Current", renderSlotItemList(currentItems)];
  if (historyItems.length > 0) {
    lines.push("", "##### History", renderSlotItemList(historyItems));
  }
  return lines.join("\n");
}

function renderSessionSummarySection(summary) {
  return renderMarkedSection("session-summary", ["## Session Summary", summary, ""]);
}

function renderSessionWikiBlock(block, index) {
  const lines = [
    `<a id="${block.anchor_id}"></a>`,
    `### Memory Block ${index + 1}: ${block.topic_title}`,
    "",
    "#### Summary",
    block.summary,
    "",
  ];
  for (const slot of SLOT_ORDER) {
    const slotItems = block.slots[slot] ?? [];
    if (slotItems.length === 0) {
      continue;
    }
    lines.push(`#### ${SLOT_HEADINGS[slot]}`);
    lines.push(renderSlotMarkdown(slotItems));
    lines.push("");
  }
  lines.push("#### Evidence References");
  for (const ref of block.evidence_refs) {
    lines.push(`- ${ref.event_id} → ${ref.event_path}`);
    if (ref.entry_ref) {
      lines.push(`  - Entry Ref: ${ref.entry_ref}`);
    }
    if (ref.quote) {
      lines.push(`  - Quote: ${ref.quote}`);
    }
  }
  lines.push("", "---", "");
  return renderMarkedSection(`block:${block.block_id}`, lines);
}

function renderSessionWikiMarkdown(state) {
  const lines = [
    `# Session Wiki: ${state.session_title}`,
    "",
    "## Metadata",
    `- Task: ${state.task_key}`,
    `- Source Type: ${state.source_type}`,
    `- Source Scope: ${state.source_scope}`,
    `- Time Range: ${state.time_range.start ?? "unknown"} ~ ${state.time_range.end ?? "unknown"}`,
    `- Participants: ${(state.participants ?? []).join("、") || "unknown"}`,
    "",
    renderSessionSummarySection(state.session_summary),
    "## Memory Blocks",
    "",
  ];
  state.block_order.forEach((blockId, index) => {
    const block = state.blocks[blockId];
    if (!block) {
      return;
    }
    lines.push(renderSessionWikiBlock(block, index));
  });
  return `${lines.join("\n").trim()}\n`;
}

async function projectSessionWiki(params) {
  const sessionPaths = getSessionWikiPaths(params.sessionDir);
  const taskRootDir = getTaskRootFromSessionDir(params.sessionDir);
  const overlay = readLifecycleOverlay(taskRootDir);
  const sessionEvents = readJsonl(sessionPaths.sessionEvents)
    .filter((event) => event?.verification?.verdict === "verified")
    .map((event) => ({
      ...event,
      lifecycle: resolveEventLifecycle(event, overlay),
    }));
  const metadata = YAML.parse(fs.readFileSync(sessionPaths.metadata, "utf8"));
  const previousState = readJsonFile(sessionPaths.sessionWikiState, null);
  const relativePagePath = relativeSessionWikiPath(params.sessionDir);

  const topicAssignments = await assignTopicsWithLLM({
    taskId: metadata.task_id,
    taskKey: metadata.task_key,
    events: sessionEvents,
    previousState,
  });
  const topicMap = new Map(topicAssignments.map((item) => [String(item.event_id), item]));
  const eventsByTopic = new Map();
  for (const event of sessionEvents) {
    const assigned = topicMap.get(String(event.event_id)) ?? {
      topic_key: extractEventCoarseKey(event),
      topic_title: fallbackTopicTitleForEvent(event),
    };
    const bucketKey = assigned.topic_key;
    const bucket = eventsByTopic.get(bucketKey) ?? {
      topic_key: assigned.topic_key,
      topic_title: assigned.topic_title,
      events: [],
    };
    bucket.events.push(event);
    eventsByTopic.set(bucketKey, bucket);
  }

  const nextBlocks = {};
  const blockOrder = [];
  const changedBlockIds = [];
  const previousBlocks = previousState?.blocks ?? {};
  for (const bucket of [...eventsByTopic.values()].sort((left, right) =>
    left.topic_title.localeCompare(right.topic_title, "zh-Hans-CN"),
  )) {
    const blockId = `block-${slugify(bucket.topic_key)}`;
    const anchorId = `block-${slugify(bucket.topic_key)}`;
    const slots = buildSlotItems(bucket.events, relativePagePath);
    const baseBlock = {
      block_id: blockId,
      anchor_id: anchorId,
      topic_key: bucket.topic_key,
      topic_title: bucket.topic_title,
      event_ids: sortByEventTimeDescending(bucket.events).map((event) => event.event_id),
      slots,
      status: inferBlockStatus(slots),
      evidence_refs: sortByEventTimeDescending(bucket.events).map((event) => ({
        event_id: event.event_id,
        event_path: `${relativePagePath.replace(/session_wiki\.md$/u, "session_events.jsonl")}#${event.event_id}`,
        entry_ref: event.core_entry_id
          ? renderLink(
              String(event.core_entry_id),
              `${relativePagePath.replace(/session_wiki\.md$/u, "session.md")}#${event.core_entry_id}`,
            )
          : null,
        quote: event.evidence_quote ?? "",
      })),
    };
    const previousBlock = previousBlocks[blockId];
    const previousSignature = previousBlock ? blockSignature(previousBlock) : null;
    const nextSignature = blockSignature(baseBlock);
    const changed = previousSignature !== nextSignature;
    let summary = previousBlock?.summary ?? "";
    if (changed) {
      summary = await requestSummary("block", {
        payload: {
          topic_title: bucket.topic_title,
          status: baseBlock.status,
          current_items: SLOT_ORDER.flatMap((slot) =>
            slots[slot]
              .filter((item) => item.is_current)
              .map((item) => ({
                slot,
                claim: item.claim,
                evidence_quote: item.evidence_quote,
              })),
          ),
        },
        fallback: {
          topicTitle: bucket.topic_title,
          slots,
        },
      });
      changedBlockIds.push(blockId);
    }
    nextBlocks[blockId] = {
      ...baseBlock,
      summary,
    };
    blockOrder.push(blockId);
  }

  const removedBlockIds = Object.keys(previousBlocks).filter((blockId) => !nextBlocks[blockId]);
  const changedTopicKeys = uniqueStrings([
    ...changedBlockIds.map((blockId) => nextBlocks[blockId]?.topic_key).filter(Boolean),
    ...removedBlockIds.map((blockId) => previousBlocks[blockId]?.topic_key).filter(Boolean),
  ]);
  const blocksForSummary = blockOrder.map((blockId) => nextBlocks[blockId]).filter(Boolean);
  const sessionSummary = await requestSummary("session", {
    payload: {
      task_key: metadata.task_key,
      source_type: metadata.source_type,
      blocks: blocksForSummary.map((block) => ({
        topic_title: block.topic_title,
        status: block.status,
        summary: block.summary,
      })),
    },
    fallback: {
      blocks: blocksForSummary,
    },
  });

  const state = {
    version: 1,
    task_id: metadata.task_id,
    task_key: metadata.task_key,
    source_session_id: metadata.source_session_id,
    source_scope: metadata.source_scope,
    source_type: metadata.source_type,
    source_id: metadata.source_id,
    session_title: metadata.source_session_id,
    time_range: metadata.time_range ?? { start: null, end: null },
    participants: metadata.participants ?? [],
    relative_page_path: relativePagePath,
    session_summary: sessionSummary,
    block_order: blockOrder,
    blocks: nextBlocks,
    lifecycle_summary: {
      active_event_count: sessionEvents.filter(
        (event) => event.lifecycle?.lifecycle_status === "active",
      ).length,
      historical_event_count: sessionEvents.filter(
        (event) => event.lifecycle?.lifecycle_status === "historical",
      ).length,
      invalid_event_count: sessionEvents.filter(
        (event) => event.lifecycle?.lifecycle_status === "invalid",
      ).length,
    },
    updated_at: new Date().toISOString(),
  };

  writeJson(sessionPaths.sessionWikiState, state);
  patchSessionWikiMarkdown({
    filePath: sessionPaths.sessionWikiMarkdown,
    taskRootDir,
    previousState,
    nextState: state,
    changedBlockIds,
    removedBlockIds,
  });

  return {
    taskRootDir,
    sessionState: state,
    previousState,
    changedBlockIds,
    removedBlockIds,
    changedTopicKeys,
  };
}

function renderIndexMarkdown(state) {
  const pageEntries = Object.values(state.pages).sort((left, right) =>
    String(left.relative_page_path).localeCompare(String(right.relative_page_path), "zh-Hans-CN"),
  );
  const totalBlocks = pageEntries.reduce((sum, page) => sum + (page.blocks?.length ?? 0), 0);
  const lines = [
    `# ${state.task_key} Index`,
    "",
    renderMarkedSection("index-overview", [
      "## Task Overview",
      `- Task: ${state.task_key}`,
      `- Current Task Wiki: ${renderLink("task_wiki.md", "task_wiki.md")}`,
      `- Session Count: ${pageEntries.length}`,
      `- Memory Block Count: ${totalBlocks}`,
      "",
    ]),
    "## Wiki Page Index",
    "",
    renderMarkedSection("wiki-page:task_wiki", [
      `### ${renderLink("task_wiki.md", "task_wiki.md")}`,
      "任务当前状态总览。",
      "",
    ]),
  ];
  for (const page of pageEntries) {
    lines.push(
      renderMarkedSection(`wiki-page:${page.source_session_id}`, [
        `### ${renderLink(page.relative_page_path, page.relative_page_path)}`,
        page.summary || "该 session 的一手 Wiki 页面。",
        "",
        ...page.blocks.flatMap((block) => [
          `- ${renderLink(`${page.relative_page_path}#${block.anchor_id}`, `${page.relative_page_path}#${block.anchor_id}`)}`,
          `  - Topic: ${block.topic_title}`,
          `  - Status: ${block.status}`,
          `  - Slots: ${block.slots.join(", ")}`,
          `  - Summary: ${block.summary}`,
          "",
        ]),
      ]),
    );
  }
  lines.push("## Topic Routes");
  lines.push("");
  for (const route of state.topic_routes) {
    lines.push(
      renderMarkedSection(`topic-route:${slugify(route.topic_title)}`, [
        `### ${route.topic_title}`,
        ...route.block_links.map((link) => `- ${renderLink(link.label, link.target)}`),
        "",
      ]),
    );
  }
  return `${lines.join("\n").trim()}\n`;
}

function updateTaskYaml(taskRootDir, params) {
  const taskPaths = getTaskRootPaths(taskRootDir);
  fs.writeFileSync(
    taskPaths.taskYaml,
    YAML.stringify({
      task_id: params.taskId,
      task_key: params.taskKey,
      session_count: params.sessionCount,
      block_count: params.blockCount,
      updated_at: new Date().toISOString(),
    }),
    "utf8",
  );
}

async function projectTaskIndex(params) {
  const taskPaths = getTaskRootPaths(params.taskRootDir);
  const originalState = readJsonFile(taskPaths.indexState, {
    version: 1,
    task_id: params.sessionState.task_id,
    task_key: params.sessionState.task_key,
    pages: {},
    topic_routes: [],
  });
  const previousState = JSON.parse(JSON.stringify(originalState));

  const pageRecord = {
    source_session_id: params.sessionState.source_session_id,
    relative_page_path: params.sessionState.relative_page_path,
    summary: params.sessionState.session_summary,
    blocks: params.sessionState.block_order.map((blockId) => {
      const block = params.sessionState.blocks[blockId];
      return {
        block_id: block.block_id,
        anchor_id: block.anchor_id,
        topic_key: block.topic_key,
        topic_title: block.topic_title,
        status: block.status,
        slots: SLOT_ORDER.filter((slot) => (block.slots[slot] ?? []).length > 0),
        summary: block.summary,
      };
    }),
    updated_at: new Date().toISOString(),
  };
  previousState.pages[params.sessionState.source_session_id] = pageRecord;

  const topicMap = new Map();
  for (const page of Object.values(previousState.pages)) {
    for (const block of page.blocks ?? []) {
      if (block.status === "archived" || block.status === "invalidated") {
        continue;
      }
      const routeTitle = inferTopicRoute(block);
      const bucket = topicMap.get(routeTitle) ?? {
        topic_key: routeTitle,
        topic_title: routeTitle,
        block_links: [],
      };
      bucket.block_links.push({
        label: `${block.topic_title} (${page.source_session_id})`,
        target: `${page.relative_page_path}#${block.anchor_id}`,
      });
      topicMap.set(routeTitle, bucket);
    }
  }
  previousState.topic_routes = [...topicMap.values()]
    .map((route) => ({
      ...route,
      block_links: route.block_links.sort((left, right) =>
        left.label.localeCompare(right.label, "zh-Hans-CN"),
      ),
    }))
    .sort((left, right) => {
      const priorityDelta = routePriority(left.topic_title) - routePriority(right.topic_title);
      if (priorityDelta !== 0) {
        return priorityDelta;
      }
      return left.topic_title.localeCompare(right.topic_title, "zh-Hans-CN");
    });
  previousState.updated_at = new Date().toISOString();

  const previousPages = originalState.pages ?? {};
  const previousRoutes = originalState.topic_routes ?? [];
  const changedPageKeys = uniqueStrings(
    Object.keys(previousState.pages).filter(
      (key) => pageSignature(previousPages[key]) !== pageSignature(previousState.pages[key]),
    ),
  );
  const changedRouteTitles = uniqueStrings(
    previousState.topic_routes
      .filter((route) => {
        const previousRoute = previousRoutes.find(
          (entry) => entry.topic_title === route.topic_title,
        );
        return routeSignature(previousRoute) !== routeSignature(route);
      })
      .map((route) => route.topic_title),
  );

  writeJson(taskPaths.indexState, previousState);
  patchIndexMarkdown({
    filePath: taskPaths.indexMarkdown,
    taskRootDir: params.taskRootDir,
    previousState: originalState,
    nextState: previousState,
    changedPageKeys,
    changedRouteTitles,
  });
  const sessionCount = Object.keys(previousState.pages).length;
  const blockCount = Object.values(previousState.pages).reduce(
    (sum, page) => sum + (page.blocks?.length ?? 0),
    0,
  );
  updateTaskYaml(params.taskRootDir, {
    taskId: previousState.task_id,
    taskKey: previousState.task_key,
    sessionCount,
    blockCount,
  });
  return {
    ...previousState,
    changedPageKeys,
    changedRouteTitles,
  };
}

function buildTaskCurrentItem(slot, block, item, sessionState) {
  const eventPath = `${sessionState.relative_page_path.replace(/session_wiki\.md$/u, "session_events.jsonl")}#${item.event_id}`;
  return {
    slot,
    topic_key: block.topic_key,
    topic_title: block.topic_title,
    subject_key: item.subject_key,
    claim: item.claim,
    event_id: item.event_id,
    event_time: item.event_time,
    evidence_quote: item.evidence_quote,
    event_path: eventPath,
    event_ref: renderLink(String(item.event_id), eventPath),
    source_session_id: sessionState.source_session_id,
    session_wiki_path: sessionState.relative_page_path,
    block_anchor: block.anchor_id,
    block_link: `${sessionState.relative_page_path}#${block.anchor_id}`,
    block_summary: block.summary,
  };
}

function currentItemGroupKey(item) {
  return [
    item.slot,
    normalizeKey(item.topic_key),
    normalizeKey(item.subject_key || item.topic_key || item.claim),
  ].join("|");
}

function chooseNewestCurrentItems(items) {
  const grouped = new Map();
  for (const item of sortByEventTimeDescending(items)) {
    const key = currentItemGroupKey(item);
    if (!grouped.has(key)) {
      grouped.set(key, item);
    }
  }
  return [...grouped.values()];
}

function renderTaskWikiMarkdown(state) {
  const lines = [`# Task Wiki: ${state.task_key}`, ""];
  const renderSectionItems = (items) => {
    if (!items.length) {
      return ["- 无"];
    }
    return items.flatMap((item) => [
      `- ${item.claim} (${renderLink(item.topic_title, item.block_link)})`,
      `  - Block Ref: ${renderLink(item.topic_title, item.block_link)}`,
      `  - Event Ref: ${item.event_ref}`,
    ]);
  };
  const renderTaskSection = (key, title, items) =>
    renderMarkedSection(`task-section:${key}`, [title, ...renderSectionItems(items), ""]);
  lines.push(
    renderMarkedSection("task-summary", ["## Current Summary", state.current_summary, ""]),
  );
  lines.push(renderTaskSection("conclusion", "## Current Conclusions", state.sections.conclusion));
  lines.push(
    renderMarkedSection("task-section:key-decisions", [
      "## Key Decisions",
      ...(state.related_blocks.length
        ? state.related_blocks.map(
            (block) => `- ${renderLink(block.topic_title, block.block_link)}：${block.summary}`,
          )
        : ["- 无"]),
      "",
    ]),
  );
  lines.push(renderTaskSection("rationale", "## Rationales", state.sections.rationale));
  lines.push(renderTaskSection("objection", "## Objections / Risks", state.sections.objection));
  lines.push(renderTaskSection("constraint", "## Constraints", state.sections.constraint));
  lines.push(renderTaskSection("commitment", "## Commitments", state.sections.commitment));
  lines.push(renderTaskSection("time", "## Timeline", state.sections.time));
  lines.push(
    renderMarkedSection("task-section:related-blocks", [
      "## Related Session Wikis / Memory Blocks",
      ...(state.related_blocks.length
        ? state.related_blocks.map(
            (block) =>
              `- ${renderLink(block.topic_title, block.block_link)} (${renderLink(block.source_session_id, block.session_wiki_path)})`,
          )
        : ["- 无"]),
      "",
    ]),
  );
  lines.push("");
  return `${lines.join("\n").trim()}\n`;
}

function pageSignature(page) {
  return JSON.stringify(page);
}

function routeSignature(route) {
  return JSON.stringify(route);
}

function sectionSignature(items) {
  return JSON.stringify(items);
}

function writeMarkdownWithFallback(params) {
  try {
    const existing = fs.existsSync(params.filePath)
      ? fs.readFileSync(params.filePath, "utf8")
      : null;
    if (!existing) {
      fs.writeFileSync(params.filePath, params.fullContent, "utf8");
      return false;
    }
    const patched = params.tryPatch(existing);
    if (typeof patched !== "string") {
      fs.writeFileSync(params.filePath, params.fullContent, "utf8");
      if (params.taskRootDir && params.fallbackDetail) {
        appendTaskLog(params.taskRootDir, "fallback_rebuild", params.fallbackDetail);
      }
      return true;
    }
    fs.writeFileSync(params.filePath, patched, "utf8");
    return false;
  } catch {
    fs.writeFileSync(params.filePath, params.fullContent, "utf8");
    if (params.taskRootDir && params.fallbackDetail) {
      appendTaskLog(params.taskRootDir, "fallback_rebuild", params.fallbackDetail);
    }
    return true;
  }
}

function patchSessionWikiMarkdown(params) {
  const nextBlocksById = new Map(
    params.nextState.block_order.map((blockId) => [blockId, params.nextState.blocks[blockId]]),
  );
  return writeMarkdownWithFallback({
    filePath: params.filePath,
    fullContent: renderSessionWikiMarkdown(params.nextState),
    taskRootDir: params.taskRootDir,
    fallbackDetail: params.nextState.relative_page_path,
    tryPatch(existing) {
      if (
        JSON.stringify(params.previousState?.block_order ?? []) !==
        JSON.stringify(params.nextState.block_order)
      ) {
        return null;
      }
      let updated = existing;
      if (params.previousState?.session_summary !== params.nextState.session_summary) {
        updated = replaceMarkedSection(
          updated,
          "session-summary",
          renderSessionSummarySection(params.nextState.session_summary),
        );
        if (updated == null) {
          return null;
        }
      }
      for (const blockId of params.changedBlockIds) {
        const block = nextBlocksById.get(blockId);
        const blockIndex = params.nextState.block_order.indexOf(blockId);
        if (!block || blockIndex < 0) {
          return null;
        }
        updated = replaceMarkedSection(
          updated,
          `block:${blockId}`,
          renderSessionWikiBlock(block, blockIndex),
        );
        if (updated == null) {
          return null;
        }
      }
      for (const blockId of params.removedBlockIds) {
        updated = removeMarkedSection(updated, `block:${blockId}`);
        if (updated == null) {
          return null;
        }
      }
      return updated;
    },
  });
}

function renderIndexPageSection(page) {
  return renderMarkedSection(`wiki-page:${page.source_session_id}`, [
    `### ${renderLink(page.relative_page_path, page.relative_page_path)}`,
    page.summary || "该 session 的一手 Wiki 页面。",
    "",
    ...page.blocks.flatMap((block) => [
      `- ${renderLink(`${page.relative_page_path}#${block.anchor_id}`, `${page.relative_page_path}#${block.anchor_id}`)}`,
      `  - Topic: ${block.topic_title}`,
      `  - Status: ${block.status}`,
      `  - Slots: ${block.slots.join(", ")}`,
      `  - Summary: ${block.summary}`,
      "",
    ]),
  ]);
}

function renderIndexRouteSection(route) {
  return renderMarkedSection(`topic-route:${slugify(route.topic_title)}`, [
    `### ${route.topic_title}`,
    ...route.block_links.map((link) => `- ${renderLink(link.label, link.target)}`),
    "",
  ]);
}

function renderIndexOverviewSection(state) {
  const pageEntries = Object.values(state.pages);
  const totalBlocks = pageEntries.reduce((sum, page) => sum + (page.blocks?.length ?? 0), 0);
  return renderMarkedSection("index-overview", [
    "## Task Overview",
    `- Task: ${state.task_key}`,
    `- Current Task Wiki: ${renderLink("task_wiki.md", "task_wiki.md")}`,
    `- Session Count: ${pageEntries.length}`,
    `- Memory Block Count: ${totalBlocks}`,
    "",
  ]);
}

function patchIndexMarkdown(params) {
  return writeMarkdownWithFallback({
    filePath: params.filePath,
    fullContent: renderIndexMarkdown(params.nextState),
    taskRootDir: params.taskRootDir,
    fallbackDetail: "index.md",
    tryPatch(existing) {
      const prevPageKeys = Object.keys(params.previousState?.pages ?? {}).sort();
      const nextPageKeys = Object.keys(params.nextState.pages ?? {}).sort();
      const prevRouteKeys = (params.previousState?.topic_routes ?? [])
        .map((route) => route.topic_title)
        .sort();
      const nextRouteKeys = params.nextState.topic_routes.map((route) => route.topic_title).sort();
      if (
        JSON.stringify(prevPageKeys) !== JSON.stringify(nextPageKeys) ||
        JSON.stringify(prevRouteKeys) !== JSON.stringify(nextRouteKeys)
      ) {
        return null;
      }
      let updated = replaceMarkedSection(
        existing,
        "index-overview",
        renderIndexOverviewSection(params.nextState),
      );
      if (updated == null) {
        return null;
      }
      for (const pageKey of params.changedPageKeys) {
        const page = params.nextState.pages[pageKey];
        if (!page) {
          return null;
        }
        updated = replaceMarkedSection(
          updated,
          `wiki-page:${pageKey}`,
          renderIndexPageSection(page),
        );
        if (updated == null) {
          return null;
        }
      }
      for (const routeTitle of params.changedRouteTitles) {
        const route = params.nextState.topic_routes.find(
          (entry) => entry.topic_title === routeTitle,
        );
        if (!route) {
          return null;
        }
        updated = replaceMarkedSection(
          updated,
          `topic-route:${slugify(routeTitle)}`,
          renderIndexRouteSection(route),
        );
        if (updated == null) {
          return null;
        }
      }
      return updated;
    },
  });
}

function renderTaskSummarySection(summary) {
  return renderMarkedSection("task-summary", ["## Current Summary", summary, ""]);
}

function renderTaskSectionBlock(key, title, items) {
  return renderMarkedSection(`task-section:${key}`, [
    title,
    ...(items.length
      ? items.flatMap((item) => [
          `- ${item.claim} (${renderLink(item.topic_title, item.block_link)})`,
          `  - Block Ref: ${renderLink(item.topic_title, item.block_link)}`,
          `  - Event Ref: ${item.event_ref}`,
        ])
      : ["- 无"]),
    "",
  ]);
}

function renderTaskKeyDecisionsSection(relatedBlocks) {
  return renderMarkedSection("task-section:key-decisions", [
    "## Key Decisions",
    ...(relatedBlocks.length
      ? relatedBlocks.map(
          (block) => `- ${renderLink(block.topic_title, block.block_link)}：${block.summary}`,
        )
      : ["- 无"]),
    "",
  ]);
}

function renderTaskRelatedBlocksSection(relatedBlocks) {
  return renderMarkedSection("task-section:related-blocks", [
    "## Related Session Wikis / Memory Blocks",
    ...(relatedBlocks.length
      ? relatedBlocks.map(
          (block) =>
            `- ${renderLink(block.topic_title, block.block_link)} (${renderLink(block.source_session_id, block.session_wiki_path)})`,
        )
      : ["- 无"]),
    "",
  ]);
}

function patchTaskWikiMarkdown(params) {
  return writeMarkdownWithFallback({
    filePath: params.filePath,
    fullContent: renderTaskWikiMarkdown(params.nextState),
    taskRootDir: params.taskRootDir,
    fallbackDetail: "task_wiki.md",
    tryPatch(existing) {
      let updated = replaceMarkedSection(
        existing,
        "task-summary",
        renderTaskSummarySection(params.nextState.current_summary),
      );
      if (updated == null) {
        return null;
      }
      for (const sectionKey of params.changedSectionKeys) {
        const titleMap = {
          conclusion: "## Current Conclusions",
          rationale: "## Rationales",
          objection: "## Objections / Risks",
          constraint: "## Constraints",
          commitment: "## Commitments",
          time: "## Timeline",
        };
        if (!titleMap[sectionKey]) {
          continue;
        }
        updated = replaceMarkedSection(
          updated,
          `task-section:${sectionKey}`,
          renderTaskSectionBlock(
            sectionKey,
            titleMap[sectionKey],
            params.nextState.sections[sectionKey] ?? [],
          ),
        );
        if (updated == null) {
          return null;
        }
      }
      if (params.changedRelatedBlocks) {
        updated = replaceMarkedSection(
          updated,
          "task-section:key-decisions",
          renderTaskKeyDecisionsSection(params.nextState.related_blocks),
        );
        if (updated == null) {
          return null;
        }
        updated = replaceMarkedSection(
          updated,
          "task-section:related-blocks",
          renderTaskRelatedBlocksSection(params.nextState.related_blocks),
        );
        if (updated == null) {
          return null;
        }
      }
      return updated;
    },
  });
}

async function projectTaskWiki(params) {
  const taskPaths = getTaskRootPaths(params.taskRootDir);
  const previousState = readJsonFile(taskPaths.taskWikiState, {
    version: 1,
    task_id: params.sessionState.task_id,
    task_key: params.sessionState.task_key,
    sources: {},
    sections: Object.fromEntries(SLOT_ORDER.map((slot) => [slot, []])),
    related_blocks: [],
  });

  const sourceRecord = {
    source_session_id: params.sessionState.source_session_id,
    session_wiki_path: params.sessionState.relative_page_path,
    blocks: params.sessionState.block_order.map((blockId) => {
      const block = params.sessionState.blocks[blockId];
      const currentItems = Object.fromEntries(
        SLOT_ORDER.map((slot) => [
          slot,
          (block.slots[slot] ?? [])
            .filter((item) => item.is_current)
            .map((item) => buildTaskCurrentItem(slot, block, item, params.sessionState)),
        ]),
      );
      return {
        block_id: block.block_id,
        topic_key: block.topic_key,
        topic_title: block.topic_title,
        summary: block.summary,
        status: block.status,
        block_link: `${params.sessionState.relative_page_path}#${block.anchor_id}`,
        session_wiki_path: params.sessionState.relative_page_path,
        source_session_id: params.sessionState.source_session_id,
        current_items: currentItems,
      };
    }),
    updated_at: new Date().toISOString(),
  };
  previousState.sources[params.sessionState.source_session_id] = sourceRecord;

  const sections = Object.fromEntries(SLOT_ORDER.map((slot) => [slot, []]));
  const relatedBlocks = [];
  for (const source of Object.values(previousState.sources)) {
    for (const block of source.blocks ?? []) {
      relatedBlocks.push({
        topic_key: block.topic_key,
        topic_title: block.topic_title,
        summary: block.summary,
        block_link: block.block_link,
        session_wiki_path: block.session_wiki_path,
        source_session_id: block.source_session_id,
        status: block.status,
      });
      for (const slot of SLOT_ORDER) {
        sections[slot].push(...(block.current_items?.[slot] ?? []));
      }
    }
  }
  for (const slot of SLOT_ORDER) {
    sections[slot] = chooseNewestCurrentItems(sections[slot]);
  }
  const currentSummary = await requestSummary("task", {
    payload: {
      task_key: params.sessionState.task_key,
      current_sections: Object.fromEntries(
        SLOT_ORDER.map((slot) => [
          slot,
          sections[slot].slice(0, 5).map((item) => ({
            topic_title: item.topic_title,
            claim: item.claim,
          })),
        ]),
      ),
    },
    fallback: {
      taskKey: params.sessionState.task_key,
      blocks: relatedBlocks,
    },
  });

  const nextState = {
    version: 1,
    task_id: params.sessionState.task_id,
    task_key: params.sessionState.task_key,
    sources: previousState.sources,
    sections,
    current_summary: currentSummary,
    related_blocks: relatedBlocks.sort((left, right) =>
      left.topic_title.localeCompare(right.topic_title, "zh-Hans-CN"),
    ),
    updated_at: new Date().toISOString(),
  };

  const changedSectionKeys = SLOT_ORDER.filter(
    (slot) =>
      sectionSignature(previousState.sections?.[slot] ?? []) !==
      sectionSignature(nextState.sections?.[slot] ?? []),
  );
  const changedRelatedBlocks =
    sectionSignature(previousState.related_blocks ?? []) !==
    sectionSignature(nextState.related_blocks ?? []);

  writeJson(taskPaths.taskWikiState, nextState);
  patchTaskWikiMarkdown({
    filePath: taskPaths.taskWikiMarkdown,
    taskRootDir: params.taskRootDir,
    nextState,
    changedSectionKeys,
    changedRelatedBlocks,
  });
  return {
    ...nextState,
    changedSectionKeys,
    changedRelatedBlocks,
  };
}

async function updateTaskWikiFromVerifiedEvents(params) {
  const projectedSession = await projectSessionWiki({ sessionDir: params.sessionDir });
  const taskRootDir = projectedSession.taskRootDir;
  ensureDir(taskRootDir);
  const indexState = await projectTaskIndex({
    taskRootDir,
    sessionState: projectedSession.sessionState,
  });
  const taskWikiState = await projectTaskWiki({
    taskRootDir,
    sessionState: projectedSession.sessionState,
  });
  appendTaskLog(taskRootDir, "update", projectedSession.sessionState.relative_page_path);
  appendTaskLog(taskRootDir, "refresh", "index.md");
  appendTaskLog(taskRootDir, "refresh", "task_wiki.md");
  try {
    // Lazy load to avoid pulling lint code into the hot path unless needed.
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS subtree on purpose
    const { runTaskWikiLint } = require("./lint.js");
    await runTaskWikiLint({ taskRootDir, appendLog: true });
  } catch {
    // Do not block third-stage projection on lint failures.
  }
  return {
    changedBlockIds: projectedSession.changedBlockIds,
    removedBlockIds: projectedSession.removedBlockIds,
    sessionState: projectedSession.sessionState,
    indexState,
    taskWikiState,
  };
}

module.exports = {
  projectSessionWiki,
  projectTaskIndex,
  projectTaskWiki,
  updateTaskWikiFromVerifiedEvents,
};
