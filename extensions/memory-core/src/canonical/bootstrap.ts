import fs from "node:fs/promises";
import path from "node:path";
import type { OpenClawConfig } from "openclaw/plugin-sdk/core";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { canonicalizeV2 } from "./canonicalizer-v2.js";
import { extract } from "./extractor.js";
import { EXTRACTOR_VERSION } from "./schema.js";
import { getCanonicalStore } from "./store.js";

const log = createSubsystemLogger("memory");
const DAILY_MEMORY_FILE_RE = /^\d{4}-\d{2}-\d{2}\.md$/;

export type BootstrapCanonicalIndexResult = {
  filesScanned: number;
  eventsExtracted: number;
  recordsWritten: number;
};

async function fileExists(filePath: string): Promise<boolean> {
  try {
    const stat = await fs.stat(filePath);
    return stat.isFile();
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return false;
    }
    throw err;
  }
}

async function listBootstrapFiles(workspaceDir: string): Promise<string[]> {
  const files: string[] = [];
  const rootMemory = path.join(workspaceDir, "MEMORY.md");
  if (await fileExists(rootMemory)) {
    files.push(rootMemory);
  }
  const memoryDir = path.join(workspaceDir, "memory");
  try {
    const entries = await fs.readdir(memoryDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isFile() || !DAILY_MEMORY_FILE_RE.test(entry.name)) {
        continue;
      }
      files.push(path.join(memoryDir, entry.name));
    }
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") {
      throw err;
    }
  }
  return files.toSorted((left, right) => left.localeCompare(right));
}

function sourceRefForFile(workspaceDir: string, filePath: string, lineCount: number): string {
  const relPath = path.relative(workspaceDir, filePath).replaceAll("\\", "/");
  return `${relPath}#L1-L${Math.max(1, lineCount)}`;
}

export async function bootstrapCanonicalIndex(params: {
  cfg?: OpenClawConfig;
  agentId: string;
  workspaceDir: string;
  force?: boolean;
  progress?: (update: { completed: number; total: number; label?: string }) => void;
}): Promise<BootstrapCanonicalIndexResult> {
  const files = await listBootstrapFiles(params.workspaceDir);
  log.info(
    `canonical.bootstrap.start agent=${params.agentId} files=${files.length} force=${Boolean(params.force)}`,
  );
  const store = getCanonicalStore(params.agentId);
  if (params.force) {
    store.reset();
  }
  let recordsWritten = 0;
  let eventsExtracted = 0;
  for (const [index, filePath] of files.entries()) {
    const text = await fs.readFile(filePath, "utf-8");
    const lineCount = text.split(/\r?\n/).length;
    const sourceRef = sourceRefForFile(params.workspaceDir, filePath, lineCount);
    log.info(`canonical.bootstrap.file source_ref=${sourceRef}`);
    const extractStartedAt = Date.now();
    let extraction;
    try {
      extraction = await extract(text, sourceRef);
    } catch (err) {
      store.recordExtractorLatency(Date.now() - extractStartedAt);
      store.bumpMetric("extractFailures", 1);
      log.warn(
        `[canonical] bootstrap.extract_failed source_ref=${sourceRef} error=${String(err)}`,
      );
      throw err;
    }
    store.recordExtractorLatency(Date.now() - extractStartedAt);
    store.bumpMetric("extractSuccesses", 1);
    eventsExtracted += extraction.claims.length;
    if (extraction.should_extract && extraction.claims.length > 0) {
      const canonicalized = canonicalizeV2({
        sourceId: params.agentId,
        sourceRef,
        text,
        entries: [],
        extraction,
        sourcePlatform: "legacy",
        sourceKind: "legacy_event_record",
      });
      const persisted = await store.persistSemanticBatchV2({
        evidence: canonicalized.evidence,
        events: canonicalized.events,
      });
      recordsWritten += persisted.events.length;
    }
    params.progress?.({
      completed: index + 1,
      total: files.length,
      label: `Graph bootstrap ${path.basename(filePath)}`,
    });
  }
  store.setMeta("extractor_version", EXTRACTOR_VERSION);
  log.info(
    `canonical.bootstrap.done files=${files.length} events=${eventsExtracted} records=${recordsWritten}`,
  );
  return {
    filesScanned: files.length,
    eventsExtracted,
    recordsWritten,
  };
}
