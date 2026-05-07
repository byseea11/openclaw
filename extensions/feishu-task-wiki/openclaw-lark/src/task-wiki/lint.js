"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {
  normalizeText,
  readJsonFile,
  readJsonl,
  writeJson,
  ensureDir,
  getSessionWikiPaths,
  getTaskRootPaths,
  findSessionDirs,
  readLifecycleOverlay,
  appendTaskLog,
} = require("./shared.js");

const UNRESOLVED_OBJECTION_AGE_DAYS = 7;

function parseLooseDate(input) {
  const normalized = normalizeText(input);
  const direct = Date.parse(normalized);
  if (!Number.isNaN(direct)) {
    return direct;
  }
  const match = normalized.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/u);
  if (!match) {
    return null;
  }
  const now = new Date();
  const month = Number(match[1]);
  const day = Number(match[2]);
  return new Date(Date.UTC(now.getUTCFullYear(), month - 1, day, 0, 0, 0)).getTime();
}

function renderFindings(title, findings, formatter) {
  const lines = [`# ${title}`, ""];
  if (findings.length === 0) {
    lines.push("- 无");
    lines.push("");
    return `${lines.join("\n")}`;
  }
  for (const finding of findings) {
    lines.push(formatter(finding));
  }
  lines.push("");
  return lines.join("\n");
}

function claimOverreachesQuote(event) {
  const claim = normalizeText(event?.claim);
  const quote = normalizeText(event?.evidence_quote);
  if (!claim || !quote) {
    return false;
  }
  if (quote.includes(claim) || claim.includes(quote)) {
    return false;
  }
  const requiredFields = [
    event?.target,
    event?.time_target,
    event?.scope_target,
    event?.action,
    event?.owner,
    event?.objector,
    event?.status,
  ]
    .map((value) => normalizeText(value))
    .filter(Boolean);
  if (requiredFields.some((field) => !quote.includes(field))) {
    return true;
  }
  const claimChars = new Set(claim.replace(/[^\p{Letter}\p{Number}\p{Script=Han}]+/gu, "").split(""));
  const quoteChars = new Set(quote.replace(/[^\p{Letter}\p{Number}\p{Script=Han}]+/gu, "").split(""));
  if (claimChars.size === 0 || quoteChars.size === 0) {
    return false;
  }
  let overlap = 0;
  for (const char of claimChars) {
    if (quoteChars.has(char)) {
      overlap += 1;
    }
  }
  return overlap / claimChars.size < 0.55;
}

function getTaskWikiSectionItems(taskWikiState) {
  const items = [];
  for (const sectionItems of Object.values(taskWikiState?.sections ?? {})) {
    items.push(...(Array.isArray(sectionItems) ? sectionItems : []));
  }
  return items;
}

async function runTaskWikiLint(params) {
  const taskPaths = getTaskRootPaths(params.taskRootDir);
  ensureDir(taskPaths.lintDir);

  const overlay = readLifecycleOverlay(params.taskRootDir);
  const sessionDirs = findSessionDirs(params.taskRootDir);
  const indexState = readJsonFile(taskPaths.indexState, { pages: {}, topic_routes: [] });
  const taskWikiState = readJsonFile(taskPaths.taskWikiState, { sections: {}, related_blocks: [] });
  const sessionStates = [];
  const eventsById = new Map();
  const orphanEvents = [];
  const missingEvidenceRefs = [];
  const staleClaims = [];
  const unresolvedObjections = [];
  const overdueCommitments = [];
  const openConflicts = [];
  const orphanBlocks = [];
  const quoteStrengthFindings = [];
  const missingCrossRefs = [];
  const orphanSessionWikis = [];

  for (const sessionDir of sessionDirs) {
    const sessionPaths = getSessionWikiPaths(sessionDir);
    const sessionState = readJsonFile(sessionPaths.sessionWikiState, null);
    const sessionWikiMarkdown = (() => {
      try {
        return fs.readFileSync(sessionPaths.sessionWikiMarkdown, "utf8");
      } catch {
        return "";
      }
    })();
    const sessionEvents = readJsonl(sessionPaths.sessionEvents).filter(
      (event) => event?.verification?.verdict === "verified",
    );
    if (!sessionState) {
      continue;
    }
    sessionStates.push(sessionState);
    const referencedEvents = new Set();
    let hasEvidenceRef = false;
    for (const blockId of sessionState.block_order ?? []) {
      const block = sessionState.blocks?.[blockId];
      if (!block) {
        continue;
      }
      if (!Array.isArray(block.event_ids) || block.event_ids.length === 0) {
        orphanBlocks.push({
          source_session_id: sessionState.source_session_id,
          block_id: blockId,
          topic_title: block.topic_title,
        });
      }
      for (const eventId of block.event_ids ?? []) {
        referencedEvents.add(String(eventId));
      }
      if ((block.evidence_refs ?? []).length > 0) {
        hasEvidenceRef = true;
      }
      for (const slot of Object.keys(block.slots ?? {})) {
        for (const item of block.slots?.[slot] ?? []) {
          if (!item.event_ref || !sessionWikiMarkdown.includes(String(item.event_path ?? ""))) {
            missingCrossRefs.push({
              type: "missing_session_event_ref",
              source_session_id: sessionState.source_session_id,
              block_id: blockId,
              event_id: item.event_id,
            });
          }
          const invalidation = overlay.invalidatedEventMap.get(String(item.event_id));
          const supersession = overlay.supersededEventMap.get(String(item.event_id));
          const sourceRevocation = overlay.revokedSourceMap.get(String(sessionState.source_session_id));
          if (item.is_current && (invalidation || supersession || sourceRevocation)) {
            staleClaims.push({
              source_session_id: sessionState.source_session_id,
              block_id: blockId,
              topic_title: block.topic_title,
              event_id: item.event_id,
              reason: invalidation
                ? "invalidated_current"
                : supersession
                  ? "superseded_current"
                  : "revoked_source_current",
            });
          }
          if (slot === "objection" && item.is_current) {
            const ageMs = Date.now() - (Date.parse(item.event_time ?? "") || 0);
            if (ageMs > UNRESOLVED_OBJECTION_AGE_DAYS * 24 * 60 * 60 * 1000) {
              unresolvedObjections.push({
                source_session_id: sessionState.source_session_id,
                block_id: blockId,
                topic_title: block.topic_title,
                claim: item.claim,
                event_id: item.event_id,
              });
            }
          }
          if (slot === "commitment" && item.is_current) {
            const siblingTimeItems = block.slots?.time ?? [];
            const dueTs = siblingTimeItems
              .map((timeItem) => parseLooseDate(timeItem.claim))
              .find((value) => value != null);
            if (dueTs != null && dueTs < Date.now()) {
              overdueCommitments.push({
                source_session_id: sessionState.source_session_id,
                block_id: blockId,
                topic_title: block.topic_title,
                claim: item.claim,
                event_id: item.event_id,
              });
            }
          }
        }
      }
    }
    if (!hasEvidenceRef) {
      missingEvidenceRefs.push({
        type: "missing_evidence_refs",
        source_session_id: sessionState.source_session_id,
        relative_page_path: sessionState.relative_page_path,
      });
    }
    for (const event of sessionEvents) {
      eventsById.set(String(event.event_id), {
        ...event,
        source_session_id: sessionState.source_session_id,
        relative_page_path: sessionState.relative_page_path,
      });
      if (claimOverreachesQuote(event)) {
        quoteStrengthFindings.push({
          source_session_id: sessionState.source_session_id,
          event_id: event.event_id,
          claim: event.claim,
          evidence_quote: event.evidence_quote,
        });
      }
      if (!referencedEvents.has(String(event.event_id))) {
        orphanEvents.push({
          source_session_id: sessionState.source_session_id,
          event_id: event.event_id,
          claim: event.claim,
        });
      }
    }
    const listedInIndex = Boolean(indexState.pages?.[sessionState.source_session_id]);
    const linkedInTaskWiki = (taskWikiState.related_blocks ?? []).some(
      (block) => block?.source_session_id === sessionState.source_session_id,
    );
    if (!listedInIndex && !linkedInTaskWiki) {
      orphanSessionWikis.push({
        type: "orphan_session_wiki",
        source_session_id: sessionState.source_session_id,
        relative_page_path: sessionState.relative_page_path,
      });
    }
  }

  const currentConclusionsByTopic = new Map();
  for (const sessionState of sessionStates) {
    for (const blockId of sessionState.block_order ?? []) {
      const block = sessionState.blocks?.[blockId];
      if (!block) {
        continue;
      }
      const currentConclusions = (block.slots?.conclusion ?? []).filter((item) => item.is_current);
      if (currentConclusions.length === 0) {
        continue;
      }
      const bucket = currentConclusionsByTopic.get(String(block.topic_key)) ?? [];
      bucket.push(...currentConclusions.map((item) => ({
        topic_title: block.topic_title,
        claim: item.claim,
        event_id: item.event_id,
        source_session_id: sessionState.source_session_id,
      })));
      currentConclusionsByTopic.set(String(block.topic_key), bucket);
    }
  }
  for (const [topicKey, items] of currentConclusionsByTopic.entries()) {
    const distinctClaims = [...new Set(items.map((item) => normalizeText(item.claim)))];
    if (distinctClaims.length > 1) {
      openConflicts.push({
        topic_key: topicKey,
        topic_title: items[0]?.topic_title ?? topicKey,
        claims: items,
      });
    }
  }

  for (const item of getTaskWikiSectionItems(taskWikiState)) {
    if (!item?.block_link) {
      missingCrossRefs.push({
        type: "missing_task_block_link",
        source_session_id: item?.source_session_id ?? "unknown",
        event_id: item?.event_id ?? "unknown",
        block_link: null,
      });
      continue;
    }
    const [pagePath, anchor] = String(item.block_link).split("#");
    const page = Object.values(indexState.pages ?? {}).find((entry) => entry?.relative_page_path === pagePath);
    const hasAnchor = (page?.blocks ?? []).some((block) => block?.anchor_id === anchor);
    if (!page || !hasAnchor) {
      missingCrossRefs.push({
        type: "broken_task_block_link",
        source_session_id: item?.source_session_id ?? "unknown",
        event_id: item?.event_id ?? "unknown",
        block_link: item.block_link,
      });
    }
  }

  for (const page of Object.values(indexState.pages ?? {})) {
    for (const block of page.blocks ?? []) {
      const sessionState = sessionStates.find((entry) => entry.source_session_id === page.source_session_id);
      const exists = sessionState?.block_order?.some((blockId) => sessionState.blocks?.[blockId]?.anchor_id === block.anchor_id);
      if (!exists) {
        missingCrossRefs.push({
          type: "broken_index_block_link",
          source_session_id: page.source_session_id,
          block_link: `${page.relative_page_path}#${block.anchor_id}`,
        });
      }
    }
  }

  const lintState = {
    version: 1,
    generated_at: new Date().toISOString(),
    orphan_event_count: orphanEvents.length,
    missing_evidence_ref_count: missingEvidenceRefs.length,
    stale_claim_count: staleClaims.length,
    quote_strength_count: quoteStrengthFindings.length,
    unresolved_objection_count: unresolvedObjections.length,
    overdue_commitment_count: overdueCommitments.length,
    open_conflict_count: openConflicts.length,
    orphan_block_count: orphanBlocks.length,
    missing_cross_ref_count: missingCrossRefs.length,
    orphan_session_wiki_count: orphanSessionWikis.length,
    findings: {
      orphan_events: orphanEvents,
      missing_evidence_refs: missingEvidenceRefs,
      stale_claims: staleClaims,
      quote_strength: quoteStrengthFindings,
      unresolved_objections: unresolvedObjections,
      overdue_commitments: overdueCommitments,
      open_conflicts: openConflicts,
      orphan_blocks: orphanBlocks,
      missing_cross_refs: missingCrossRefs,
      orphan_session_wikis: orphanSessionWikis,
    },
  };

  writeJson(taskPaths.lintState, lintState);
  fs.writeFileSync(
    taskPaths.openConflicts,
    renderFindings("Open Conflicts", openConflicts, (finding) =>
      `- ${finding.topic_title}: ${finding.claims.map((item) => item.claim).join(" | ")}`),
    "utf8",
  );
  fs.writeFileSync(
    taskPaths.staleClaims,
    renderFindings("Stale Claims", [...staleClaims, ...quoteStrengthFindings], (finding) =>
      finding.reason
        ? `- ${finding.topic_title} / ${finding.event_id}: ${finding.reason}`
        : `- ${finding.event_id}: claim may exceed quote | ${finding.claim} | quote=${finding.evidence_quote}`),
    "utf8",
  );
  fs.writeFileSync(
    taskPaths.orphanEvents,
    renderFindings("Orphan Events", [...orphanEvents, ...missingEvidenceRefs, ...orphanBlocks, ...missingCrossRefs, ...orphanSessionWikis], (finding) =>
      finding.type
        ? finding.type === "missing_evidence_refs"
          ? `- missing evidence refs: ${finding.relative_page_path}`
          : finding.type === "orphan_session_wiki"
            ? `- orphan session wiki: ${finding.relative_page_path}`
            : `- missing cross ref ${finding.type}: ${finding.block_link ?? finding.block_id ?? finding.source_session_id}`
        : finding.event_id
          ? `- orphan event ${finding.event_id}: ${finding.claim}`
          : `- orphan block ${finding.block_id}: ${finding.topic_title}`),
    "utf8",
  );
  fs.writeFileSync(
    taskPaths.unresolvedObjections,
    renderFindings("Unresolved Objections", unresolvedObjections, (finding) =>
      `- ${finding.topic_title}: ${finding.claim}`),
    "utf8",
  );
  fs.writeFileSync(
    taskPaths.overdueCommitments,
    renderFindings("Overdue Commitments", overdueCommitments, (finding) =>
      `- ${finding.topic_title}: ${finding.claim}`),
    "utf8",
  );

  if (params.appendLog) {
    appendTaskLog(params.taskRootDir, "lint", `${openConflicts.length + staleClaims.length + quoteStrengthFindings.length + orphanEvents.length + missingEvidenceRefs.length + missingCrossRefs.length + orphanSessionWikis.length + unresolvedObjections.length + overdueCommitments.length + orphanBlocks.length} findings`);
  }

  return lintState;
}

module.exports = {
  runTaskWikiLint,
};
